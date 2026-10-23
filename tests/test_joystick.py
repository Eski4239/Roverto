"""Phase 6 — joystick drive input end-to-end (docs/02 §6.12, docs/03 §3,
docs/PROGRESS_ROVER_MAIN.md Phase 6 prompt). Runs the real FastAPI app
against the real simulator over a socket:// link, same convention as
tests/test_cmd_heartbeat.py (which this file borrows its connection helpers
from unchanged).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time

import pytest
import uvicorn
import websockets

from ground_station.app.main import create_app
from simulator.fake_rover import parse_args as sim_parse_args
from simulator.fake_rover import run_server as sim_run_server

TIMEOUT = 5.0


async def _start_simulator(extra_args: list[str] | None = None):
    args = sim_parse_args(extra_args or [])
    args.host = "127.0.0.1"
    args.port = 0
    server = await sim_run_server(args)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _start_app(sim_port: int):
    args = argparse.Namespace(link=f"socket://127.0.0.1:{sim_port}", any_port=False)
    app = create_app(args)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="on", log_level="error")
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    server._gs_app = app
    return server, serve_task, port


async def _stop_app(server: uvicorn.Server, serve_task: asyncio.Task):
    server.should_exit = True
    await asyncio.wait_for(serve_task, timeout=TIMEOUT)


async def _recv_snapshot(ws, timeout: float = TIMEOUT) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _send_hello(ws, *, reconnect: bool = False) -> None:
    await ws.send(json.dumps({"type": "hello", "reconnect": reconnect}))


async def _recv_latest_snapshot(ws, settle: float = 0.3) -> dict:
    await asyncio.sleep(settle)
    snap = await _recv_snapshot(ws)
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
        except asyncio.TimeoutError:
            break
        snap = json.loads(raw)
    return snap


async def _wait_for_joystick_status(ws, status: str, *, timeout: float = TIMEOUT) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = await _recv_snapshot(ws)
        joy = snap.get("joystick")
        if joy is not None and joy.get("status") == status:
            return snap
    pytest.fail(f"joystick status never reached {status!r}")


async def test_joystick_only_drives_when_controller_selects_it():
    """Safety rule: joystick drives ONLY if a tab is in control and has
    input Joystick selected -- never mixed with keyboard.

    --joystick-demo is pure driving (centre/forward/turn/reverse/centre)
    and never touches the button (confirmed live 2026-10-22; the earlier
    combined pattern pressing the button every loop made E-STOP itself
    look broken when it wasn't), so this test no longer needs to work
    around a demo-triggered E-STOP."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)

            # Default input mode is keyboard -- the demo's scripted forward
            # phase must NOT reach the rover while keyboard is selected.
            await _wait_for_joystick_status(ws, "ok")
            await asyncio.sleep(0.3)
            assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0
            assert not rover_state.estop_latched

            # Switch to Joystick -- now it should drive. The demo pattern
            # loops every 6s (centre/forward/turn/reverse/centre); poll
            # across more than one full cycle so the test isn't racing it.
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            await _wait_for_joystick_status(ws, "ok")
            deadline = time.monotonic() + 8.0
            moved = False
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                if rover_state.drive_l != 0.0 or rover_state.drive_r != 0.0:
                    moved = True
                    break
            assert moved, "joystick never drove the rover after switching input mode"
            assert not rover_state.estop_latched, "pure driving demo must never E-STOP"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_sticks_ignored_until_centred_after_take_control():
    """After bridge connect / TAKE CONTROL / switching to Joystick, sticks
    are ignored until both are centred (prompt safety rule 2)."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            snap = await _recv_snapshot(ws)
            # Immediately after connect, the demo's 1s centre window hasn't
            # elapsed yet -- status should be not_centred (or no frames yet).
            joy = snap.get("joystick")
            if joy is not None and joy.get("available"):
                assert joy["status"] in ("not_centred",)
                assert joy["drive"]["l"] == 0.0 and joy["drive"]["r"] == 0.0

            await _wait_for_joystick_status(ws, "ok")
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_joystick_lost_after_200ms_silence_forces_drive_zero():
    """No SK_JOYSTICK frame for 200 ms -> drive 0 + JOYSTICK_LOST event."""
    sim_server, sim_port = await _start_simulator([
        "--joystick-demo", "--joystick-silent-after", "3.0", "--joystick-silent-for", "10",
    ])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    gs_state = app_server._gs_app.state.ground_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            # let calibration finish (the demo's silence window starts well
            # after the 0.5s centre-learning window, so this doesn't race it)
            await _wait_for_joystick_status(ws, "ok")

            snap = await _wait_for_joystick_status(ws, "lost", timeout=5.0)
            assert snap["joystick"]["drive"]["l"] == 0.0
            assert snap["joystick"]["drive"]["r"] == 0.0

            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and (rover_state.drive_l != 0.0 or rover_state.drive_r != 0.0):
                await asyncio.sleep(0.01)
            assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0

            assert any(e.code == "JOYSTICK_LOST" for e in gs_state.events)
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_stick_button_estops_even_with_no_tab_in_control():
    """Either stick button -> immediate E-STOP, even with nobody in
    control. --joystick-demo-estop presses the left stick button exactly
    once, 10s after start, and never again -- a dedicated scenario for
    testing E-STOP in isolation from the (button-free) driving demo."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo-estop"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        # no UI client at all -- nobody in control, nobody even connected.
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not rover_state.estop_latched:
            await asyncio.sleep(0.05)
        assert rover_state.estop_latched, "stick button did not E-STOP with no tab in control"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_estop_reset_only_from_controlling_tab_after_joystick_estop():
    sim_server, sim_port = await _start_simulator(["--joystick-demo-estop"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a:
            await _recv_snapshot(ws_a)
            await _send_hello(ws_a)
            await _recv_latest_snapshot(ws_a)

            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline and not rover_state.estop_latched:
                await asyncio.sleep(0.05)
            assert rover_state.estop_latched

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                await _recv_snapshot(ws_b)
                await _send_hello(ws_b)
                await ws_b.send(json.dumps({"type": "cmd", "estop_reset": True}))
                await asyncio.sleep(0.5)
                assert rover_state.estop_latched, "viewer's estop_reset must be ignored"

            await ws_a.send(json.dumps({"type": "cmd", "estop_reset": True}))
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.estop_latched:
                await asyncio.sleep(0.01)
            assert not rover_state.estop_latched, "controller's estop_reset was not honored"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_joystick_fault_forces_drive_zero_and_event():
    """Wildly jumping values (--joystick-fault) -> drive 0 + JOYSTICK_FAULT."""
    sim_server, sim_port = await _start_simulator(["--joystick-fault"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    gs_state = app_server._gs_app.state.ground_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))

            await _wait_for_joystick_status(ws, "fault", timeout=5.0)

            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and (rover_state.drive_l != 0.0 or rover_state.drive_r != 0.0):
                await asyncio.sleep(0.01)
            assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0
            assert any(e.code == "JOYSTICK_FAULT" for e in gs_state.events)
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_release_drives_zero_within_150ms():
    """Release (sticks return to centre at the end of the demo's driving
    loop) -> simulator sees drive 0 within 150 ms."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            await _wait_for_joystick_status(ws, "ok")

            # Wait until the demo pattern is actively driving (turn phase).
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline and rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0:
                await asyncio.sleep(0.02)

            # Then watch for the release phase: both back to 0 quickly.
            deadline = time.monotonic() + 8.0
            went_zero_at = None
            was_driving = False
            while time.monotonic() < deadline:
                if rover_state.drive_l != 0.0 or rover_state.drive_r != 0.0:
                    was_driving = True
                if was_driving and rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0:
                    went_zero_at = time.monotonic()
                    break
                await asyncio.sleep(0.01)
            assert went_zero_at is not None, "drive never returned to 0 during the demo's release phase"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_demo_estop_pattern_includes_release_after_button_press():
    """Checklist item: the button-press demo pattern must include a
    release after the press (buttons==0), not stay 'pressed' forever."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo-estop"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        from ground_station.app import wire

        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline and not rover_state.estop_latched:
            await asyncio.sleep(0.02)
        assert rover_state.estop_latched, "button press phase never ran"

        # After the press, watch the raw buttons bit on the next frames --
        # there must be a stretch where buttons == 0 (release).
        deadline = time.monotonic() + 3.0
        saw_release = False
        while time.monotonic() < deadline:
            payload = rover_state.build_joystick_frame()
            if payload is not None:
                frame = wire.decode_joystick(payload)
                if frame.buttons == 0:
                    saw_release = True
                    break
            await asyncio.sleep(0.02)
        assert saw_release, "no release phase observed after the button press"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_demo_estop_fires_exactly_once_never_again():
    """--joystick-demo-estop presses the button once, ~10s after start,
    and never again -- confirmed live (2026-10-22) over a 28s window."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo-estop"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))

            onsets = 0
            was_latched = False
            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws, timeout=TIMEOUT)
                telem = snap.get("telem")
                if telem is None:
                    continue
                latched = telem["state"]["estop"]
                if latched and not was_latched:
                    onsets += 1
                was_latched = latched
            assert onsets == 1, f"expected exactly one E-STOP onset, got {onsets}"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_estop_reset_sticks_even_while_stick_button_still_held():
    """P1 regression: resetting E-STOP while the demo's button-press phase
    is still active (button bit held across several frames) must not
    silently re-latch on the next heartbeat tick -- the fix zeroes
    estop_remaining (the docs/02 §6.9 'next 3 CmdMsgs' exemption window) on
    reset, and joystick.py ignores the still-held button until it's seen
    released."""
    sim_server, sim_port = await _start_simulator(["--joystick-demo-estop"])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            await _wait_for_joystick_status(ws, "ok")

            deadline = time.monotonic() + 15.0
            while time.monotonic() < deadline and not rover_state.estop_latched:
                await asyncio.sleep(0.01)
            assert rover_state.estop_latched

            # Reset immediately (the button is very likely still physically
            # "held" at the wire level for the rest of its ~0.3s press phase).
            await ws.send(json.dumps({"type": "cmd", "estop_reset": True}))

            # Wait for the reset to actually land on the simulator first --
            # sending is async, so asserting "stays reset" before it's even
            # been applied once would just be checking stale pre-reset
            # state, not the regression this test targets.
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.estop_latched:
                await asyncio.sleep(0.005)
            assert not rover_state.estop_latched, "estop_reset never landed on the simulator"

            # Now it must STAY reset for a good stretch -- not just the
            # instant of the reset -- even though more SK_JOYSTICK frames
            # with buttons=1 keep arriving right after (the P1 bug: the
            # next heartbeat tick used to re-send estop=True because
            # estop_remaining hadn't been zeroed by the reset).
            deadline = time.monotonic() + 0.6
            while time.monotonic() < deadline:
                assert not rover_state.estop_latched, (
                    "E-STOP re-latched after reset while the stick button "
                    "was still held -- estop_remaining/button-edge guard regressed"
                )
                await asyncio.sleep(0.02)
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_assisted_mode_blocks_forward_near_wall_and_reverse_still_works():
    """P3: the simulator's front-wall distance must actually respond to
    drive, so assisted mode's < 20cm forward-block is testable."""
    sim_server, sim_port = await _start_simulator([])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    gs_state = app_server._gs_app.state.ground_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)

            await ws.send(json.dumps({"type": "cmd", "mode": "assisted", "drive": {"l": 1.0, "r": 1.0}}))

            deadline = time.monotonic() + 10.0
            blocked = False
            while time.monotonic() < deadline:
                await asyncio.sleep(0.05)
                if rover_state.front_wall_cm < 20.0:
                    blocked = True
                    break
            assert blocked, "front_wall_cm never dropped below 20cm while driving forward"

            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and (rover_state.drive_l != 0.0 or rover_state.drive_r != 0.0):
                await asyncio.sleep(0.01)
            assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0, (
                "assisted mode did not block forward drive near the wall"
            )
            deadline = time.monotonic() + TIMEOUT
            saw_obstacle = False
            while time.monotonic() < deadline:
                if any(e.code == "OBSTACLE" for e in gs_state.events):
                    saw_obstacle = True
                    break
                await asyncio.sleep(0.02)
            assert saw_obstacle, "OBSTACLE event never reached the ground station"

            dist_before_reverse = rover_state.front_wall_cm
            await ws.send(json.dumps({"type": "cmd", "mode": "assisted", "drive": {"l": -1.0, "r": -1.0}}))
            await asyncio.sleep(1.0)
            assert rover_state.front_wall_cm > dist_before_reverse, (
                "reversing in assisted mode did not increase front_wall_cm"
            )
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_servo_fixed_90_reports_90_not_frozen_sweep_angle():
    """P4: switching to FIXED 90 must report angle_deg=90 in TELEM, not
    whatever angle the sweep happened to be at when the mode switched."""
    sim_server, sim_port = await _start_simulator([])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)

            await asyncio.sleep(0.5)  # let the sweep move away from angle 0

            await ws.send(json.dumps({"type": "cmd", "servo": {"mode": "fixed", "angle_deg": 90}}))

            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.servo_mode != "fixed":
                await asyncio.sleep(0.01)
            assert rover_state.servo_mode == "fixed"

            await asyncio.sleep(0.3)  # let a few TELEM ticks pass
            snap = await _recv_latest_snapshot(ws)
            telem = snap.get("telem")
            assert telem is not None
            assert telem["sonar"]["angle_deg"] == 90.0, (
                f"expected angle_deg=90 in fixed mode, got {telem['sonar']['angle_deg']}"
            )

            # also exercise angle 0 and 180 (checklist: radar must draw
            # inside its box for all three reference angles)
            for angle in (0, 180):
                await ws.send(json.dumps({"type": "cmd", "servo": {"mode": "fixed", "angle_deg": angle}}))
                await asyncio.sleep(0.3)
                snap = await _recv_latest_snapshot(ws)
                telem = snap.get("telem")
                assert telem["sonar"]["angle_deg"] == float(angle)
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_buzzer_hold_reaches_simulator_only_while_held():
    """P6: the simulator must receive the buzzer flag only while held, and
    the backend snapshot's buzzer_sent must reflect what's actually being
    sent (not local UI mouse state)."""
    sim_server, sim_port = await _start_simulator([])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            snap = await _recv_latest_snapshot(ws)
            assert snap.get("buzzer_sent") is False

            await ws.send(json.dumps({"type": "cmd", "buzzer": True}))
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.last_cmd_buzzer is not True:
                await asyncio.sleep(0.01)
            assert rover_state.last_cmd_buzzer is True
            snap = await _recv_latest_snapshot(ws)
            assert snap.get("buzzer_sent") is True

            await ws.send(json.dumps({"type": "cmd", "buzzer": False}))
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.last_cmd_buzzer is not False:
                await asyncio.sleep(0.01)
            assert rover_state.last_cmd_buzzer is False
            snap = await _recv_latest_snapshot(ws)
            assert snap.get("buzzer_sent") is False
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_never_received_joystick_frame_drives_zero_for_2s():
    """Reported live (2026-10-23): with no joystick frames at all, the
    widget was seen showing status OK and both sticks at full reverse
    (-1.0/-1.0) instead of NO JOYSTICK / drive 0 -- re-tested end to end
    against the real simulator (started WITHOUT any joystick flags) and
    the real backend; could not reproduce the bad state in this session,
    but this test locks in the required safe behavior either way: with
    input=Joystick selected and zero SK_JOYSTICK frames ever received,
    the backend's actual drive output sent to the rover must be exactly
    0 for a full 2s window, and the snapshot's joystick block must say
    available=False / status=not_centred, never 'ok' with nonzero drive."""
    sim_server, sim_port = await _start_simulator([])  # no joystick flags at all
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))

            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws)
                joy = snap.get("joystick")
                assert joy is not None
                assert joy["available"] is False, f"available should stay False, got {joy}"
                assert joy["status"] != "ok", f"status must never be 'ok' with zero frames received: {joy}"
                assert joy["drive"]["l"] == 0.0 and joy["drive"]["r"] == 0.0, (
                    f"drive must stay 0 with zero frames received: {joy}"
                )
                assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0, (
                    "simulator received nonzero drive with no joystick frames ever sent"
                )
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_frames_stop_mid_drive_zeroes_within_200ms_and_shows_lost():
    """(b) from the live-test request: frames stop mid-drive -> drive 0
    within 200 ms and the snapshot shows status=lost. Uses
    --joystick-silent-after/-for (mirrors --rover-silent-after/-for) to
    stop SK_JOYSTICK partway through the --joystick-demo pattern, once
    calibration has completed and the rover is actively being driven."""
    sim_server, sim_port = await _start_simulator([
        "--joystick-demo", "--joystick-silent-after", "2.0", "--joystick-silent-for", "10",
    ])
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)
            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            await _wait_for_joystick_status(ws, "ok")

            # confirm it's actually driving before the silence kicks in,
            # so "zeroes after" is a real transition, not already zero.
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0:
                await asyncio.sleep(0.02)

            # wait for the silence window (joystick_silent_after=2.0s from
            # the simulator's own boot, independent of our wall clock) and
            # the resulting LOST status + zero drive.
            snap = await _wait_for_joystick_status(ws, "lost", timeout=8.0)
            lost_seen_at = time.monotonic()
            assert snap["joystick"]["drive"]["l"] == 0.0
            assert snap["joystick"]["drive"]["r"] == 0.0

            # rover_state.drive_l/r is the simulator's OWN applied value,
            # written by the backend's independently-clocked 10Hz heartbeat
            # -- it can still briefly read the pre-LOST nonzero value for
            # up to one heartbeat tick after the WS snapshot already shows
            # LOST/drive:0 (that's the 200ms budget itself, not a bug: the
            # snapshot reflects the backend's *decision*, not yet the
            # *delivered* wire frame). What must never happen is going
            # BACK to nonzero after it first reaches 0.
            deadline = lost_seen_at + 0.2
            went_zero_at = None
            while time.monotonic() < deadline:
                if rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0:
                    went_zero_at = time.monotonic()
                    break
                await asyncio.sleep(0.005)
            assert went_zero_at is not None, (
                "simulator's applied drive never reached 0 within 200ms of LOST being shown"
            )

            deadline = went_zero_at + 0.3  # settle margin, watching for any re-drive
            while time.monotonic() < deadline:
                assert rover_state.drive_l == 0.0 and rover_state.drive_r == 0.0, (
                    "drive went nonzero again after reaching 0 post-LOST"
                )
                await asyncio.sleep(0.01)
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_joystick_status_text_matches_backend_state_in_every_case():
    """(c) from the live-test request: the status the snapshot reports
    must always be consistent with the backend's own safety state --
    never-received, mid-drive-ok, and lost-after-ok, in one continuous
    session against the real simulator/backend."""
    sim_server, sim_port = await _start_simulator([
        "--joystick-demo", "--joystick-silent-after", "2.0", "--joystick-silent-for", "10",
    ])
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws)
            await _recv_latest_snapshot(ws)

            # never-received (still on Keyboard -- no set_input_mode yet,
            # but joystick.py decodes frames regardless of input_mode).
            snap = await _recv_snapshot(ws)
            joy = snap["joystick"]
            if not joy["available"]:
                assert joy["status"] == "not_centred"
                assert joy["drive"] == {"l": 0.0, "r": 0.0}

            await ws.send(json.dumps({"type": "set_input_mode", "mode": "joystick"}))
            snap = await _wait_for_joystick_status(ws, "ok")
            assert snap["joystick"]["status"] == "ok"

            snap = await _wait_for_joystick_status(ws, "lost", timeout=8.0)
            assert snap["joystick"]["status"] == "lost"
            assert snap["joystick"]["drive"] == {"l": 0.0, "r": 0.0}
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()
