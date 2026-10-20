"""Serial/socket link — pyserial serial_for_url() wrapper.

serial_for_url() accepts "COM5", "/dev/ttyUSB0" or "socket://127.0.0.1:8765"
so the same code drives real hardware and the simulator. "auto" scans USB
serial ports for one speaking the bridge's BRIDGE_STATUS heartbeat.

pyserial is blocking, so the actual port I/O runs in a background thread;
decoded frames are handed to asyncio via call_soon_threadsafe. The port
disappearing (unplugged bridge) is not fatal: the reader thread reports
disconnection and keeps retrying to reopen at reconnect_retry_s.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import AsyncIterator, Optional

import serial
from serial.tools import list_ports

from ground_station.app import wire
from ground_station.app.protocol import CmdMsg

log = logging.getLogger("link")

# Common ESP32 USB-UART bridge chips: CP210x, CH340, CH9102, FTDI.
ESP32_USB_VID_PIDS = {
    (0x10C4, 0xEA60),  # Silicon Labs CP210x
    (0x1A86, 0x7523),  # CH340
    (0x1A86, 0x55D4),  # CH9102
    (0x0403, 0x6001),  # FTDI FT232
}

AUTO_SCAN_TIMEOUT_S = 2.5


def _candidate_ports(any_port: bool) -> list[str]:
    ports = list(list_ports.comports())
    if any_port:
        return [p.device for p in ports]
    matches = [
        p.device for p in ports
        if (p.vid, p.pid) in ESP32_USB_VID_PIDS
    ]
    return matches


def _probe_port_for_bridge(device: str, baud: int, timeout_s: float) -> bool:
    """Open `device`, listen up to timeout_s for a valid BRIDGE_STATUS frame."""
    try:
        ser = serial.Serial(device, baudrate=baud, timeout=0.2)
    except (serial.SerialException, OSError) as exc:
        log.debug("auto-scan: cannot open %s: %s", device, exc)
        return False
    deadline = time.monotonic() + timeout_s
    buf = bytearray()
    try:
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if not chunk:
                continue
            buf.extend(chunk)
            while b"\x00" in buf:
                idx = buf.index(b"\x00")
                frame, buf = bytes(buf[:idx]), buf[idx + 1:]
                if not frame:
                    continue
                try:
                    sf = wire.decode_serial_frame(frame)
                except wire.WireError:
                    continue
                if sf.kind == wire.SK_BRIDGE_STATUS:
                    return True
        return False
    finally:
        ser.close()


def find_bridge_port(baud: int, *, any_port: bool = False) -> Optional[str]:
    """Scan candidate USB serial ports for one that speaks BRIDGE_STATUS."""
    for device in _candidate_ports(any_port):
        if _probe_port_for_bridge(device, baud, AUTO_SCAN_TIMEOUT_S):
            return device
    return None


class Link:
    """Owns one serial/socket connection; reconnects on failure.

    frames() yields decoded SerialFrame objects as they arrive. send_cmd()
    sets the CmdMsg sent on the next 10 Hz heartbeat tick. All I/O happens
    off the asyncio loop in a background thread.
    """

    HEARTBEAT_PERIOD_S = 0.1

    def __init__(
        self,
        url: str,
        *,
        baud: int = 921600,
        any_port: bool = False,
        reconnect_retry_s: float = 1.0,
    ) -> None:
        self._url = url
        self._baud = baud
        self._any_port = any_port
        self._reconnect_retry_s = reconnect_retry_s

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: "asyncio.Queue[wire.SerialFrame]" = asyncio.Queue()
        self._ser: Optional[serial.SerialBase] = None
        self._ser_lock = threading.Lock()
        self._connected = threading.Event()
        self._active_port: Optional[str] = None
        self._stop = threading.Event()

        self._pending_cmd: Optional[CmdMsg] = None
        self._pending_lock = threading.Lock()

        self._reader_thread: Optional[threading.Thread] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------- public ----

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="link-reader", daemon=True,
        )
        self._reader_thread.start()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
        with self._ser_lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass

    async def frames(self) -> AsyncIterator[wire.SerialFrame]:
        while True:
            yield await self._queue.get()

    async def send_cmd(self, cmd: CmdMsg) -> None:
        with self._pending_lock:
            self._pending_cmd = cmd

    def is_connected(self) -> bool:
        return self._connected.is_set()

    def active_port(self) -> Optional[str]:
        return self._active_port

    # ------------------------------------------------------- reader thread ----

    def _open(self) -> Optional[serial.SerialBase]:
        url = self._url
        if url == "auto":
            device = find_bridge_port(self._baud, any_port=self._any_port)
            if device is None:
                return None
            url = device
        try:
            ser = serial.serial_for_url(url, baudrate=self._baud, timeout=0.2)
        except (serial.SerialException, OSError) as exc:
            log.debug("open %s failed: %s", url, exc)
            return None
        self._active_port = url
        return ser

    def _reader_loop(self) -> None:
        buf = bytearray()
        while not self._stop.is_set():
            ser = self._open()
            if ser is None:
                self._connected.clear()
                time.sleep(self._reconnect_retry_s)
                continue

            with self._ser_lock:
                self._ser = ser
            self._connected.set()
            log.info("link connected: %s", self._active_port)
            buf.clear()

            try:
                while not self._stop.is_set():
                    chunk = ser.read(4096)
                    if chunk:
                        buf.extend(chunk)
                        while b"\x00" in buf:
                            idx = buf.index(b"\x00")
                            frame, buf[:] = bytes(buf[:idx]), buf[idx + 1:]
                            if frame:
                                self._handle_frame(frame)
            except (serial.SerialException, OSError) as exc:
                log.warning("link lost (%s): %s", self._active_port, exc)
            except AttributeError:
                # stop() closed the port (nulling pyserial's internal socket)
                # while this thread was mid-read; indistinguishable from a
                # normal disconnect from here.
                log.debug("link read interrupted by stop() (%s)", self._active_port)
            finally:
                self._connected.clear()
                with self._ser_lock:
                    self._ser = None
                try:
                    ser.close()
                except Exception:  # noqa: BLE001
                    pass
            if not self._stop.is_set():
                time.sleep(self._reconnect_retry_s)

    def _handle_frame(self, frame: bytes) -> None:
        try:
            sf = wire.decode_serial_frame(frame)
        except wire.WireError as exc:
            log.debug("dropping malformed frame: %s", exc)
            return
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, sf)

    # ------------------------------------------------------------- heartbeat ----

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self.HEARTBEAT_PERIOD_S)
            with self._pending_lock:
                cmd = self._pending_cmd
            if cmd is None:
                cmd = CmdMsg(t=0, seq=0, drive={"l": 0.0, "r": 0.0}, mode="idle", servo={})
            payload = wire.encode_cmd(cmd)
            frame = wire.encode_serial_frame(wire.SK_TX_TO_ROVER, 0, payload)
            with self._ser_lock:
                ser = self._ser
            if ser is None:
                continue
            try:
                ser.write(frame)
            except (serial.SerialException, OSError) as exc:
                log.debug("heartbeat write failed: %s", exc)
