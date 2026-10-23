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
from ground_station.app.joystick import JoystickController
from ground_station.app.link import Link
from ground_station.app.logger import SessionLogger
from ground_station.app.protocol import CmdDrive, CmdMsg, CmdServo, EventMsg
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
    # Phase 6: which input source may drive while a tab is in control.
    # Backend-authoritative (not just a UI convention) so "joystick drives
    # only if input=Joystick is selected" is an actual safety guarantee --
    # joystick.py always decodes frames for status/UI, but its drive output
    # only reaches last_ui_cmd when input_mode == "joystick" below.
    input_mode = "keyboard"
    joystick = JoystickController(config.get("control", {}))
    # docs/02 §6.9: the GS sets CMD_ESTOP on the *next 3* CmdMsgs then
    # clears it (latch lives on the rover) -- a UI estop:true request bumps
    # this counter rather than staying latched forever.
    estop_remaining = 0
    estop_reset_pending = False
    # F13/F20: one writer. Both the periodic heartbeat tick and an
    # out-of-band immediate E-STOP send go through _build_and_send_cmd()
    # under this lock, so two CmdMsg frames can never interleave on the
    # wire and seq always increments exactly once per frame actually sent.
    send_lock = asyncio.Lock()
    heartbeat_wake = asyncio.Event()

    async def _ingest_loop() -> None:
        async for frame in link.frames():
            recv_wall_ms = time.time() * 1000.0
            session_logger.log_raw_bytes("rx", frame.payload)
            try:
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
                elif frame.kind == wire.SK_JOYSTICK:
                    joy_frame = wire.decode_joystick(frame.payload)
                    joystick.on_frame(joy_frame, recv_wall_ms)
                    await _drain_joystick_events_and_estop()
            except Exception:  # noqa: BLE001 -- F3: never let one bad frame
                # kill telemetry ingestion for the rest of the session. An
                # exception here previously propagated out of this task,
                # which asyncio would just log as "unhandled task exception"
                # and the task would die silently -- no more TELEM would
                # ever reach the UI again, with no visible error.
                log.exception("unexpected error ingesting frame (kind=%s), dropping it", frame.kind)

    async def _scan_timeout_loop() -> None:
        while True:
            await asyncio.sleep(SCAN_TIMEOUT_POLL_S)
            state.poll_scan_timeouts(int(time.time() * 1000))

    async def _joystick_timeout_loop() -> None:
        while True:
            await asyncio.sleep(SCAN_TIMEOUT_POLL_S)
            joystick.poll_timeout(time.time() * 1000.0)
            await _drain_joystick_events_and_estop()

    async def _drain_joystick_events_and_estop() -> None:
        """Either stick's button -> immediate E-STOP (safety exception, same
        path as the UI E-STOP button, works with no tab in control); any
        calibration/lost/fault state change -> one GS-synthesized event
        (never spammed every tick -- joystick.py only arms these one-shot)."""
        nonlocal estop_remaining
        code = joystick.take_pending_event()
        if code is not None:
            state.events.append(EventMsg(
                t=now_ms(), seq=0, level="warn", code=code,
                msg=f"joystick: {code.lower()}",
            ))
        if joystick.take_pending_estop():
            estop_remaining = 3
            await _build_and_send_cmd(source="immediate")
            heartbeat_wake.set()

    async def _build_and_send_cmd(*, source: str = "heartbeat") -> None:
        """Build one fresh CmdMsg from current intent and write it to the
        wire now. Shared by the periodic heartbeat tick and the immediate
        E-STOP send path (F13/F20) -- send_lock makes the two mutually
        exclusive, so seq always advances by exactly one per frame actually
        written and no two frames can interleave on the serial port.
        `source` ("heartbeat" or "immediate") is recorded on `state` purely
        for tests to verify which path actually delivered a given frame."""
        nonlocal estop_remaining, estop_reset_pending
        async with send_lock:
            send_estop = estop_remaining > 0
            if send_estop:
                estop_remaining -= 1
            send_estop_reset = estop_reset_pending
            estop_reset_pending = False  # one-shot, like estop_remaining
            # Phase 6: joystick drive only reaches the rover while a tab is
            # in control, that tab picked Joystick, and calibration/fault
            # checks say it's safe -- otherwise fall back to whatever the UI
            # (keyboard, or neutral) last asked for. Never mixed per-axis.
            if (
                controlling_ws is not None
                and input_mode == "joystick"
                and joystick.status == "ok"
            ):
                drive = CmdDrive(l=joystick.drive_l, r=joystick.drive_r)
            else:
                drive = CmdDrive(**last_ui_cmd["drive"])
            cmd = CmdMsg(
                t=now_ms(),
                seq=next_cmd_seq(),
                drive=drive,
                mode=last_ui_cmd["mode"],
                servo=CmdServo(**last_ui_cmd["servo"]),
                estop=send_estop,
                estop_reset=send_estop_reset,
                buzzer=last_ui_cmd["buzzer"],
                request_hello=state.needs_hello_request(),
            )
            state.last_sent_cmd_source = source  # tests only
            await link.send_cmd(cmd)
            sent_wall_ms = time.time() * 1000.0
            state.record_cmd_sent(cmd.seq, sent_wall_ms)
            session_logger.log_message("tx", cmd, sent_wall_ms)
            session_logger.log_raw_bytes("tx", wire.encode_cmd(cmd))

    async def _cmd_heartbeat_loop() -> None:
        while True:
            await _build_and_send_cmd(source="heartbeat")
            heartbeat_wake.clear()
            try:
                # an immediate send (F20) already covered this tick's work;
                # skip straight to waiting out the rest of the period instead
                # of sending again right away.
                await asyncio.wait_for(heartbeat_wake.wait(), timeout=Link.HEARTBEAT_PERIOD_S)
            except asyncio.TimeoutError:
                pass

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
            asyncio.create_task(_joystick_timeout_loop()),
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
            "control": config.get("control", {}),
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
        nonlocal controlling_ws, estop_remaining, estop_reset_pending, input_mode
        await ws.accept()
        ui_sockets.add(ws)
        # F21: control is NOT granted here just because nobody else has it
        # -- that would auto-promote every tab that reconnects after a
        # backend restart (ws.js retries on close) to controller, with no
        # operator action. Assignment happens once the client's first
        # "hello" message says whether this is a fresh page load (may
        # become controller if none exists) or an automatic reconnect
        # (always stays a viewer; TAKE CONTROL is a deliberate action).

        async def _push_snapshots() -> None:
            while True:
                snapshot = state.snapshot(
                    now_wall_ms=time.time() * 1000.0,
                    connected=link.is_connected(),
                    serial_port=link.active_port(),
                )
                snapshot["in_control"] = ws is controlling_ws
                snapshot["controller_present"] = controlling_ws is not None
                snapshot["joystick"] = joystick.to_block()
                snapshot["input_mode"] = input_mode if ws is controlling_ws else None
                # P6: lets the controlling tab's buzzer button show whether
                # a press is actually being sent, not just its own mousedown
                # CSS state (which could desync from reality -- e.g. a
                # dropped mouseup, or control changing hands mid-press).
                snapshot["buzzer_sent"] = bool(last_ui_cmd["buzzer"])
                await ws.send_json(snapshot)
                await asyncio.sleep(SNAPSHOT_PERIOD_S)

        push_task = asyncio.create_task(_push_snapshots())
        try:
            while True:
                data = await ws.receive_json()
                msg_type = data.get("type")
                if msg_type == "hello":
                    # F21: only a fresh page load (reconnect=False) may be
                    # auto-granted control, and only if nobody has it.
                    if not data.get("reconnect") and controlling_ws is None:
                        controlling_ws = ws
                    continue
                if msg_type == "take_control":
                    if controlling_ws is None:
                        controlling_ws = ws
                        last_ui_cmd["drive"] = {}
                        last_ui_cmd["servo"] = {}
                        last_ui_cmd["buzzer"] = False
                        # mode is intentionally left as-is: the new controller
                        # inherits whatever mode the rover is currently in,
                        # same as it inherits drive=0 (safe) and buzzer=off
                        # (safe) -- unlike drive/buzzer there's no "neutral"
                        # mode to reset to, and silently switching modes on
                        # handoff (e.g. out of `assisted`) would itself be a
                        # surprise to the operator (F1).
                        # Phase 6: new controller always starts on Keyboard
                        # and sticks are ignored until re-centred -- prevents
                        # a stale/uncentred joystick from driving the instant
                        # control changes hands.
                        input_mode = "keyboard"
                        joystick.reset_calibration()
                    continue
                if msg_type == "set_input_mode":
                    # Phase 6: only the controlling tab may switch input --
                    # this is the server-side half of "joystick drives only
                    # if input=Joystick is selected" (the other half is the
                    # input_mode check in _build_and_send_cmd).
                    if ws is controlling_ws and data.get("mode") in ("joystick", "keyboard"):
                        input_mode = data["mode"]
                        if input_mode == "joystick":
                            joystick.reset_calibration()
                    continue
                if msg_type != "cmd":
                    continue
                # estop/estop_reset are a safety exception: honored from any
                # tab regardless of control state (docs/02 §6.9).
                # estop_reset is NOT: F20 restricts it to the controlling
                # tab -- only estop itself bypasses control gating.
                if data.get("estop"):
                    estop_remaining = 3
                    # F13/F20: don't wait for the next heartbeat tick --
                    # send this one immediately. It counts as the 1st of
                    # the 3 CMD_ESTOP-carrying CmdMsgs; the next 2 periodic
                    # ticks (now rescheduled a full period out) carry the
                    # rest, matching docs/02 §6.9's "next 3" exactly.
                    await _build_and_send_cmd(source="immediate")
                    heartbeat_wake.set()
                if data.get("estop_reset") and ws is controlling_ws:
                    estop_reset_pending = True
                    # P1 fix: a reset must also cancel any still-counting-
                    # down exemption window from an earlier estop:true (the
                    # "next 3 CmdMsgs" from docs/02 §6.9) -- otherwise a
                    # reset sent while estop_remaining > 0 clears the latch
                    # for one tick, then the very next heartbeat tick still
                    # sends estop=True (because estop_remaining hadn't been
                    # zeroed), re-latching it a moment later. A joystick
                    # button held through the reset reproduces this
                    # reliably: the button's own estop:true sets
                    # estop_remaining=3, and a reset sent within that
                    # ~300ms window used to silently get overridden.
                    estop_remaining = 0
                    joystick.on_estop_reset()
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
                if "speed_limit" in data:
                    # Shared by both input modes: keyboard applies it
                    # client-side to the drive values it sends; joystick.py
                    # applies it server-side to the raw stick readings.
                    joystick.speed_limit = max(0.0, min(1.0, float(data["speed_limit"])))
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
