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
        ]
        try:
            yield
        finally:
            for t in tasks:
                t.cancel()
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

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket) -> None:
        await ws.accept()

        async def _push_snapshots() -> None:
            while True:
                snapshot = state.snapshot(
                    now_wall_ms=time.time() * 1000.0,
                    connected=link.is_connected(),
                    serial_port=link.active_port(),
                )
                await ws.send_json(snapshot)
                await asyncio.sleep(SNAPSHOT_PERIOD_S)

        push_task = asyncio.create_task(_push_snapshots())
        try:
            while True:
                data = await ws.receive_json()
                if data.get("type") != "cmd":
                    continue
                cmd = CmdMsg(
                    t=now_ms(),
                    seq=next_cmd_seq(),
                    drive=CmdDrive(**data.get("drive", {})),
                    mode=data.get("mode", "idle"),
                    servo=CmdServo(**data.get("servo", {})),
                    estop=data.get("estop", False),
                    estop_reset=data.get("estop_reset", False),
                    buzzer=data.get("buzzer", False),
                    request_hello=data.get("request_hello", False),
                )
                await link.send_cmd(cmd)
                sent_wall_ms = time.time() * 1000.0
                state.record_cmd_sent(cmd.seq, sent_wall_ms)
                session_logger.log_message("tx", cmd, sent_wall_ms)
                session_logger.log_raw_bytes("tx", wire.encode_cmd(cmd))
        except WebSocketDisconnect:
            pass
        finally:
            push_task.cancel()

    return app
