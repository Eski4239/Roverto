"""FastAPI app: routes, /ws/ui pushes a combined snapshot at 10 Hz, serves
web/ at http://localhost:8000.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import serial.tools.list_ports
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ground_station.app import wire
from ground_station.app.link import Link
from ground_station.app.logger import SessionLogger
from ground_station.app.protocol import CmdDrive, CmdMsg, CmdServo
from ground_station.app.state import GroundState, load_config

log = logging.getLogger("main")

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
CONFIG_PATH = APP_DIR / "config.toml"

CAMERA_PROBE_PERIOD_S = 5.0
SNAPSHOT_PERIOD_S = 0.1
SCAN_TIMEOUT_POLL_S = 0.1


def _now_ms_factory():
    """CmdMsg.t is the wire's t_ms (sender's millis() since boot, uint32),
    not wall-clock epoch time, which would overflow struct.pack's 'I'."""
    start = time.monotonic()

    def _now_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    return _now_ms


def _next_cmd_seq_factory():
    seq = 0

    def _next() -> int:
        nonlocal seq
        seq = (seq + 1) % 65536
        return seq

    return _next


def create_app(args: argparse.Namespace) -> FastAPI:
    config = load_config(CONFIG_PATH)
    state = GroundState()
    link = Link(
        args.link,
        baud=config["link"]["baud"],
        any_port=args.any_port,
        reconnect_retry_s=config["link"].get("reconnect_retry_s", 1.0),
    )
    session_logger = SessionLogger(Path(config["logging"]["log_dir"]))
    next_cmd_seq = _next_cmd_seq_factory()
    now_ms = _now_ms_factory()

    # Backend-owned 10 Hz command heartbeat (docs/02 §3.1 "this IS the
    # heartbeat"). Link.send_cmd() only latches the CmdMsg Link's own
    # internal loop keeps re-sending with an *unchanged* seq -- the rover
    # acks by seq value (docs/02 §6.8 "seq % 10 == 0"), so re-sending the
    # same seq forever would mean at most one fresh ack/RTT sample ever.
    # We instead generate a new CmdMsg (new seq) every tick ourselves, so
    # the ack/RTT cadence documented in §6.8 (~1 Hz) actually advances.
    # `last_ui_cmd` holds the latest intent from whichever tab is in
    # control (drive/mode/servo/buzzer); estop/estop_reset bypass control
    # entirely (safety) and are merged in from any connected tab.
    last_ui_cmd: dict = {"drive": {}, "mode": "idle", "servo": {}, "buzzer": False}
    ui_sockets: set[WebSocket] = set()
    controlling_ws: Optional[WebSocket] = None
    # docs/02 §6.9: the GS sets CMD_ESTOP on the *next 3* CmdMsgs then
    # clears it (latch lives on the rover) -- a UI estop:true request bumps
    # this counter rather than staying latched forever.
    estop_remaining = 0
    estop_reset_pending = False

    async def _ingest_loop() -> None:
        async for frame in link.frames():
            recv_wall_ms = time.time() * 1000.0
            session_logger.log_raw_bytes("rx", frame.payload)
            if frame.kind == wire.SK_RX_FROM_ROVER:
                try:
                    decoded = wire.decode_message(frame.payload)
                except wire.WireError as exc:
                    log.debug("dropping undecodable payload: %s", exc)
                    continue
                if isinstance(decoded, tuple):
                    scan, part, parts = decoded
                    state.ingest_scan_fragment(scan, part, parts, int(recv_wall_ms))
                    session_logger.log_message("rx", scan, recv_wall_ms)
                else:
                    state.ingest(decoded, rssi=frame.rssi, recv_wall_ms=recv_wall_ms)
                    session_logger.log_message("rx", decoded, recv_wall_ms)
            elif frame.kind == wire.SK_BRIDGE_STATUS:
                status = wire.decode_bridge_status(frame.payload)
                state.ingest(status, rssi=frame.rssi, recv_wall_ms=recv_wall_ms)

    async def _scan_timeout_loop() -> None:
        while True:
            await asyncio.sleep(SCAN_TIMEOUT_POLL_S)
            state.poll_scan_timeouts(int(time.time() * 1000))

    async def _cmd_heartbeat_loop() -> None:
        nonlocal estop_remaining, estop_reset_pending
        while True:
            send_estop = estop_remaining > 0
            if send_estop:
                estop_remaining -= 1
            send_estop_reset = estop_reset_pending
            estop_reset_pending = False  # one-shot, like estop_remaining
            cmd = CmdMsg(
                t=now_ms(),
                seq=next_cmd_seq(),
                drive=CmdDrive(**last_ui_cmd["drive"]),
                mode=last_ui_cmd["mode"],
                servo=CmdServo(**last_ui_cmd["servo"]),
                estop=send_estop,
                estop_reset=send_estop_reset,
                buzzer=last_ui_cmd["buzzer"],
                request_hello=state.needs_hello_request(),
            )
            await link.send_cmd(cmd)
            sent_wall_ms = time.time() * 1000.0
            state.record_cmd_sent(cmd.seq, sent_wall_ms)
            session_logger.log_message("tx", cmd, sent_wall_ms)
            session_logger.log_raw_bytes("tx", wire.encode_cmd(cmd))
            await asyncio.sleep(Link.HEARTBEAT_PERIOD_S)

    async def _camera_probe_loop() -> None:
        camera_url = config.get("camera", {}).get("camera_url")
        if not camera_url:
            return
        loop = asyncio.get_running_loop()
        while True:
            await loop.run_in_executor(None, state.probe_camera_once, camera_url)
            await asyncio.sleep(CAMERA_PROBE_PERIOD_S)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await link.start()
        tasks = [
            asyncio.create_task(_ingest_loop()),
            asyncio.create_task(_scan_timeout_loop()),
            asyncio.create_task(_camera_probe_loop()),
            asyncio.create_task(_cmd_heartbeat_loop()),
        ]
        try:
            yield
        finally:
            for ws in list(ui_sockets):
                try:
                    await ws.close()
                except Exception:
                    pass
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await link.stop()
            session_logger.close()

    app = FastAPI(lifespan=lifespan)
    app.state.ground_state = state
    app.state.link = link
    app.state.session_logger = session_logger

    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/ports")
    async def ports() -> list[dict]:
        return [
            {"device": p.device, "description": p.description}
            for p in serial.tools.list_ports.comports()
        ]

    @app.get("/config")
    async def get_config() -> dict:
        return {
            "pwm_max": config["motors"]["pwm_max"],
            "thresholds": config.get("thresholds", {}),
        }

    @app.get("/api/history")
    async def api_history(field: str, window: int = 300) -> dict:
        """Phase 5b expandable tiles: on-demand series for a chartable field
        (state.CHARTABLE_FIELDS), polled at 1 Hz only while a tile is open --
        kept out of the 10 Hz WS snapshot so an unopened tile costs nothing.

        `t` values are the GS's own receive wall-clock in ms, not the
        rover's t_ms (which resets to 0 on every rover reboot, D-015) --
        `window` slices relative to the newest sample, not now().
        """
        samples = state.chart_history(field)
        if samples:
            cutoff_ms = samples[-1][0] - window * 1000
            samples = [(t, v) for (t, v) in samples if t >= cutoff_ms]
        return {"t": [t for t, _ in samples], "v": [v for _, v in samples]}

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        nonlocal controlling_ws, estop_remaining, estop_reset_pending
        await ws.accept()
        ui_sockets.add(ws)
        if controlling_ws is None:
            controlling_ws = ws

        async def _push_snapshots() -> None:
            while True:
                snapshot = state.snapshot(
                    now_wall_ms=time.time() * 1000.0,
                    connected=link.is_connected(),
                    serial_port=link.active_port(),
                )
                snapshot["in_control"] = ws is controlling_ws
                snapshot["controller_present"] = controlling_ws is not None
                await ws.send_json(snapshot)
                await asyncio.sleep(SNAPSHOT_PERIOD_S)

        push_task = asyncio.create_task(_push_snapshots())
        try:
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type")
                if msg_type == "take_control":
                    if controlling_ws is None:
                        controlling_ws = ws
                        last_ui_cmd["drive"] = {}
                        last_ui_cmd["servo"] = {}
                    continue
                if msg_type != "cmd":
                    continue
                # estop/estop_reset are a safety exception: honored from any
                # tab regardless of control state (docs/02 §6.9).
                if data.get("estop"):
                    estop_remaining = 3
                if data.get("estop_reset"):
                    estop_reset_pending = True
                if ws is not controlling_ws:
                    continue
                if "drive" in data:
                    last_ui_cmd["drive"] = data["drive"]
                if "mode" in data:
                    last_ui_cmd["mode"] = data["mode"]
                if "servo" in data:
                    last_ui_cmd["servo"] = data["servo"]
                if "buzzer" in data:
                    last_ui_cmd["buzzer"] = bool(data["buzzer"])
        except WebSocketDisconnect:
            pass
        finally:
            ui_sockets.discard(ws)
            if controlling_ws is ws:
                controlling_ws = None
            push_task.cancel()
            try:
                await push_task
            except asyncio.CancelledError:
                pass

    return app
