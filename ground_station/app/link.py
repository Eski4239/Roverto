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
    writes the given CmdMsg to the wire immediately (off the asyncio loop,
    since pyserial's write() blocks) -- there is exactly one send path, so
    the caller's "sent" timestamp matches the real wire write, and nothing
    here ever re-sends a command on its own schedule: if nobody calls
    send_cmd(), nothing goes out, and the rover's watchdog is free to trip
    (F13 -- this used to be a second, independently-clocked heartbeat loop
    that kept re-sending whatever was last handed to it, which could defeat
    the watchdog if the caller's own heartbeat loop died).
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

        self._reader_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------- public ----

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="link-reader", daemon=True,
        )
        self._reader_thread.start()

    async def stop(self) -> None:
        self._stop.set()
        with self._ser_lock:
            if self._ser is not None:
                try:
                    self._ser.close()
                except Exception:  # noqa: BLE001
                    pass
        if self._reader_thread is not None:
            # closing the socket above unblocks the reader thread's pending
            # read() (raising the OSError caught at _reader_loop's except
            # clause) -- join so stop() doesn't return before that cleanup
            # (and the "link lost" log line it triggers) has actually run.
            await asyncio.get_running_loop().run_in_executor(
                None, self._reader_thread.join, 2.0
            )

    async def frames(self) -> AsyncIterator[wire.SerialFrame]:
        while True:
            yield await self._queue.get()

    async def send_cmd(self, cmd: CmdMsg) -> None:
        """Write `cmd` to the wire now, off the event loop (pyserial's
        write() blocks). The caller is expected to call this once per tick
        of its own heartbeat with a freshly-built CmdMsg -- there is no
        caching/resending here, so a dead caller means nothing is sent."""
        payload = wire.encode_cmd(cmd)
        frame = wire.encode_serial_frame(wire.SK_TX_TO_ROVER, 0, payload)
        with self._ser_lock:
            ser = self._ser
        if ser is None:
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, ser.write, frame)
        except (serial.SerialException, OSError) as exc:
            log.debug("send_cmd write failed: %s", exc)

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
                    # read(1) returns as soon as *any* byte is available (or
                    # the timeout elapses on silence) instead of blocking
                    # for a full 4096-byte buffer or the full timeout --
                    # pyserial's read(size) loops until it has `size` bytes
                    # or the timeout expires, so read(4096) on a link that
                    # only ever sends small frames was adding up to a full
                    # timeout's worth of latency to every frame.
                    chunk = ser.read(1)
                    if not chunk:
                        continue
                    waiting = ser.in_waiting
                    if waiting:
                        chunk += ser.read(waiting)
                    buf.extend(chunk)
                    while b"\x00" in buf:
                        idx = buf.index(b"\x00")
                        frame, buf[:] = bytes(buf[:idx]), buf[idx + 1:]
                        if frame:
                            self._handle_frame(frame)
            except (serial.SerialException, OSError) as exc:
                if self._stop.is_set():
                    log.debug("link closed by stop() (%s): %s", self._active_port, exc)
                else:
                    log.warning("link lost (%s): %s", self._active_port, exc)
            except (AttributeError, ValueError):
                # stop() closed the port (nulling pyserial's internal socket,
                # or leaving its fd at -1) while this thread was mid-read;
                # indistinguishable from a normal disconnect from here.
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
