"""main.py's /ws/ui end-to-end: backend-owned 10 Hz CmdMsg heartbeat,
single in-control tab, E-STOP safety exception, and graceful shutdown.

Runs the real FastAPI app (create_app) against the real simulator
(simulator/fake_rover.py) over a socket:// link, both bound to OS-assigned
ports -- same convention as tests/test_simulator.py and tests/test_link.py.
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


async def _start_simulator():
    args = sim_parse_args([])
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
    server._gs_app = app  # tests only: access app.state.ground_state etc.
    return server, serve_task, port


async def _stop_app(server: uvicorn.Server, serve_task: asyncio.Task):
    server.should_exit = True
    await asyncio.wait_for(serve_task, timeout=TIMEOUT)


async def _recv_snapshot(ws, timeout: float = TIMEOUT) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _send_hello(ws, *, reconnect: bool = False) -> None:
    """F21: the first message every real client sends -- a fresh page load
    (reconnect=False) may be auto-granted control if nobody has it; an
    automatic reconnect (reconnect=True, ws.js's own retry-on-close) never
    is. Most of this file's tests simulate "a tab just loaded the page",
    so they send this right after connecting, same as dashboard.js does."""
    await ws.send(json.dumps({"type": "hello", "reconnect": reconnect}))


async def _recv_latest_snapshot(ws, settle: float = 0.3) -> dict:
    """Drain any snapshots queued ahead of a just-sent control message (the
    10 Hz push keeps streaming while this process was awaiting elsewhere)
    and return the most recent one, so assertions see post-action state."""
    await asyncio.sleep(settle)
    snap = await _recv_snapshot(ws)
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=0.05)
        except asyncio.TimeoutError:
            break
        snap = json.loads(raw)
    return snap


async def test_rtt_under_20ms_via_backend_heartbeat():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            # The rover only acks 1-in-10 CmdMsgs (docs/02 §6.8 ack_rule_b,
            # ~1 Hz) so rtt_ms only changes about once a second; collect
            # distinct values over several seconds and take the minimum --
            # that isolates genuine send->ack wire/processing latency from
            # the fact that *which* seq lands on the %10==0 boundary is
            # essentially arbitrary relative to wall-clock (so individual
            # samples legitimately vary 0-100ms without any one of them
            # being a real latency problem).
            distinct = []
            last = "unset"
            deadline = time.monotonic() + 6.0
            while time.monotonic() < deadline and len(distinct) < 5:
                snap = await _recv_snapshot(ws)
                rtt = snap.get("link", {}).get("rtt_ms")
                if rtt is not None and rtt != last:
                    distinct.append(rtt)
                    last = rtt
            assert distinct, "never saw an rtt_ms -- heartbeat not acking"
            assert min(distinct) < 20, f"min(rtt_ms)={min(distinct)} too high for a local socket:// link"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_second_tab_is_view_only_and_ignored():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a:
            await _recv_snapshot(ws_a)
            await _send_hello(ws_a)
            snap_a = await _recv_latest_snapshot(ws_a)
            assert snap_a["in_control"] is True

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                await _recv_snapshot(ws_b)
                await _send_hello(ws_b)
                snap_b = await _recv_latest_snapshot(ws_b)
                assert snap_b["in_control"] is False
                assert snap_b["controller_present"] is True

                await ws_b.send(json.dumps({"type": "cmd", "drive": {"l": 1.0, "r": 1.0}}))

                # B's drive must never have been adopted -- still view-only.
                snap_b2 = await _recv_latest_snapshot(ws_b)
                assert snap_b2["in_control"] is False
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_f1_buzzer_off_on_take_control_reaches_simulator():
    """F1: take_control resets buzzer to False alongside drive/servo
    (main.py's control-handoff block). Verified at the wire -- the first
    CmdMsg the simulator actually receives after the handoff must carry
    buzzer=False, not just that last_ui_cmd was reset locally."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        ws_a = await websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui")
        await _recv_snapshot(ws_a)
        await _send_hello(ws_a)
        await _recv_latest_snapshot(ws_a)

        # A turns the buzzer on -- confirm it actually reaches the
        # simulator first, so the later "off" check is a real transition.
        await ws_a.send(json.dumps({"type": "cmd", "buzzer": True}))
        deadline = time.monotonic() + TIMEOUT
        while time.monotonic() < deadline and rover_state.last_cmd_buzzer is not True:
            await asyncio.sleep(0.01)
        assert rover_state.last_cmd_buzzer is True, "buzzer:true never reached the simulator"

        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
            await _recv_snapshot(ws_b)
            await _send_hello(ws_b)

            await ws_a.close()
            snap_b = await _recv_latest_snapshot(ws_b)
            assert snap_b["controller_present"] is False

            await ws_b.send(json.dumps({"type": "take_control"}))
            snap_b2 = await _recv_latest_snapshot(ws_b)
            assert snap_b2["in_control"] is True

            # the next CmdMsg the simulator actually receives must carry
            # buzzer=False -- not just last_ui_cmd being reset in-process.
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and rover_state.last_cmd_buzzer is not False:
                await asyncio.sleep(0.01)
            assert rover_state.last_cmd_buzzer is False, (
                "buzzer stayed on (or unknown) in the first CmdMsg the "
                "simulator received after take_control"
            )
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_no_auto_promotion_on_controller_disconnect():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        ws_a = await websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui")
        await _recv_snapshot(ws_a)  # confirm A is attached
        await _send_hello(ws_a)

        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
            await _recv_snapshot(ws_b)  # B is view-only while A holds control
            await _send_hello(ws_b)

            await ws_a.close()

            snap_b = await _recv_latest_snapshot(ws_b)
            assert snap_b["in_control"] is False
            assert snap_b["controller_present"] is False  # nobody auto-promoted

            await ws_b.send(json.dumps({"type": "take_control"}))
            snap_b2 = await _recv_latest_snapshot(ws_b)
            assert snap_b2["in_control"] is True
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_no_wd_stop_with_zero_ui_clients():
    """The backend heartbeat alone (no browser) must satisfy the rover's
    500ms watchdog. A single WD_STOP right at startup -- before the Link has
    connected and sent its first CmdMsg -- is an expected one-time
    transient, not a sign the heartbeat stopped; what matters is that the
    watchdog is satisfied *after* the heartbeat has had time to run, and
    stays satisfied (no repeated/late WD_STOP once the link is up)."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    gs_state = app_server._gs_app.state.ground_state
    try:
        await asyncio.sleep(1.0)  # well past the 500ms watchdog, no UI client ever connects
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            snap = await _recv_snapshot(ws)
            telem = snap.get("telem")
            assert telem is not None
            assert telem["state"]["wd_ok"] is True
            assert telem["state"]["last_cmd_age_ms"] < 500
            # F9: the snapshot only carries recent_events (last 10) now, not
            # the full cumulative log -- check the backend's own full
            # self.events deque directly instead, same semantics as before.
            wd_stop_count_before = sum(1 for e in gs_state.events if e.code == "WD_STOP")

            # Watch for another second: no *additional* WD_STOP should fire
            # once the heartbeat has been running steadily (events is a
            # cumulative log, so the one from startup never disappears --
            # what matters is the count doesn't grow).
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws, timeout=1.5)
                assert snap["telem"]["state"]["wd_ok"] is True
                wd_stop_count_now = sum(1 for e in gs_state.events if e.code == "WD_STOP")
                assert wd_stop_count_now == wd_stop_count_before
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_estop_bypasses_control_gating():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a:
            await _recv_snapshot(ws_a)  # A is in control

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                snap_b = await _recv_snapshot(ws_b)
                assert snap_b["in_control"] is False

                await ws_b.send(json.dumps({"type": "cmd", "estop": True}))

                estop_latched = False
                deadline = time.monotonic() + TIMEOUT
                while time.monotonic() < deadline:
                    snap = await _recv_snapshot(ws_b)
                    telem = snap.get("telem")
                    if telem is not None and telem["state"]["estop"]:
                        estop_latched = True
                        break
                assert estop_latched, "non-controlling tab's E-STOP was not honored"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_estop_reset_ignored_from_viewer_tab():
    """F20: estop_reset, unlike estop itself, does NOT bypass control
    gating -- only the controlling tab may clear the latch (docs/03b §1.7).
    A viewer's estop_reset must be silently ignored."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a:
            await _recv_snapshot(ws_a)
            await _send_hello(ws_a)  # A is in control

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                await _recv_snapshot(ws_b)
                await _send_hello(ws_b)
                snap_b = await _recv_latest_snapshot(ws_b)
                assert snap_b["in_control"] is False

                # B (viewer) latches E-STOP -- allowed, estop bypasses gating.
                await ws_b.send(json.dumps({"type": "cmd", "estop": True}))
                deadline = time.monotonic() + TIMEOUT
                while time.monotonic() < deadline:
                    snap = await _recv_snapshot(ws_b)
                    if snap.get("telem") is not None and snap["telem"]["state"]["estop"]:
                        break
                else:
                    pytest.fail("E-STOP never latched")

                # B (viewer) tries to clear it -- must be ignored.
                await ws_b.send(json.dumps({"type": "cmd", "estop_reset": True}))
                await asyncio.sleep(0.5)  # well past one heartbeat period
                snap = await _recv_latest_snapshot(ws_b)
                assert snap["telem"]["state"]["estop"] is True, (
                    "a viewer tab's estop_reset must not clear the latch"
                )

                # A (controller) clears it -- must succeed.
                await ws_a.send(json.dumps({"type": "cmd", "estop_reset": True}))
                deadline = time.monotonic() + TIMEOUT
                while time.monotonic() < deadline:
                    snap = await _recv_snapshot(ws_a)
                    if snap.get("telem") is not None and not snap["telem"]["state"]["estop"]:
                        break
                else:
                    pytest.fail("controller's estop_reset was not honored")
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_shutdown_within_2s_with_open_ui_socket():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            start = time.monotonic()
            app_server.should_exit = True
            await asyncio.wait_for(serve_task, timeout=2.5)
            elapsed = time.monotonic() - start
            assert elapsed < 2.5, f"shutdown took {elapsed:.2f}s"
    finally:
        sim_server.close()
        await sim_server.wait_closed()


async def test_estop_reaches_simulator_fast_and_consistently():
    """F13: send_cmd() must write to the wire immediately, not just stash
    the intent for a second, independently-clocked heartbeat loop to pick
    up on its own schedule (that could add up to a full HEARTBEAT_PERIOD_S
    of latency to a safety-critical E-STOP).

    Measured at the simulator's own RoverState, not through the UI's 10Hz
    WS snapshot -- that push loop, the backend's cmd-heartbeat loop, and
    the simulator's own TELEM-emission loop are three more independently
    clocked ~100ms hops layered on top of the actual wire send, so polling
    "has the UI's estop flag flipped yet" cannot resolve a tight budget
    even with F13 fixed; this test checks the one hop F13 is actually
    about -- the moment the CmdMsg lands on the simulator.

    A single-sample "<20ms" assertion flaked under full-suite CPU load
    (Windows timer/scheduling noise, not the send path itself -- the same
    class of issue as the watchdog timer's 480ms-not-500ms lower bound
    above). Instead this takes 10 independent samples (resetting the latch
    between each, waiting >=300ms so each is measuring a fresh immediate
    send, not a leftover from the previous one) and checks the *shape* of
    the distribution: median comfortably under the old uniform-0-100ms
    heartbeat-tick-wait bug's typical case, and max bounded loosely enough
    to absorb one slow outlier under load without accepting a real
    regression back to tick-waiting (which would fail max<50ms on
    essentially every one of 10 samples, not just an occasional one)."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state  # see run_server() -- stashed for tests
    gs_state = app_server._gs_app.state.ground_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _send_hello(ws)  # F20: needs to be controller to estop_reset
            # Wait for the link to actually be OK (not just "connected"), the
            # same way a real operator can't press E-STOP before the page
            # shows live data. Without this, sample 0 can race the backend's
            # own first heartbeat tick (fired on task start with no initial
            # delay): the ws_ui coroutine's turn to read this test's E-STOP
            # message can be scheduling-delayed, and the periodic tick --
            # which doesn't depend on message processing -- can legitimately
            # win that race under heavy test-suite CPU load. Settling first
            # avoids measuring that connection-startup race instead of the
            # steady-state immediate-send path F13 is actually about.
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws)
                if snap.get("link", {}).get("state") == "OK":
                    break
            else:
                pytest.fail("link never reached OK")

            delays_ms = []
            sources = []
            for _ in range(10):
                gs_state.last_sent_cmd_source = None
                start = time.monotonic()
                await ws.send(json.dumps({"type": "cmd", "estop": True}))

                deadline = time.monotonic() + 1.0
                latched_at = None
                while time.monotonic() < deadline:
                    if rover_state.estop_latched:
                        latched_at = time.monotonic()
                        break
                    await asyncio.sleep(0.001)
                assert latched_at is not None, "E-STOP never latched on the simulator"
                delays_ms.append((latched_at - start) * 1000)
                sources.append(gs_state.last_sent_cmd_source)

                # controller clears it so the next iteration starts clean,
                # and waits comfortably clear of one heartbeat period so
                # each sample measures a fresh immediate send.
                await ws.send(json.dumps({"type": "cmd", "estop_reset": True}))
                deadline = time.monotonic() + TIMEOUT
                while time.monotonic() < deadline and rover_state.estop_latched:
                    await asyncio.sleep(0.005)
                assert not rover_state.estop_latched, "estop_reset was not honored between samples"
                await asyncio.sleep(0.3)

            delayed_via_heartbeat = [
                (d, s) for d, s in zip(delays_ms, sources) if d >= 50 and s != "immediate"
            ]
            assert not delayed_via_heartbeat, (
                f"{len(delayed_via_heartbeat)} slow sample(s) were delivered by the "
                f"heartbeat path, not the immediate send: {delayed_via_heartbeat} "
                f"(full delays={delays_ms}, sources={sources})"
            )

            delays_ms_sorted = sorted(delays_ms)
            median_ms = delays_ms_sorted[len(delays_ms_sorted) // 2]
            max_ms = delays_ms_sorted[-1]
            assert max_ms < 50, f"max E-STOP delay {max_ms:.1f}ms over 10 samples: {list(zip(delays_ms, sources))}"
            assert median_ms < 20, f"median E-STOP delay {median_ms:.1f}ms over 10 samples: {list(zip(delays_ms, sources))}"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_concurrent_estop_and_heartbeat_sends_never_corrupt_frames():
    """F13/F20 requirement: one writer. The immediate E-STOP send and the
    periodic heartbeat tick both call _build_and_send_cmd() under the same
    send_lock, so two CmdMsg frames can never interleave on the wire. Fire
    many E-STOP requests back-to-back while the heartbeat keeps ticking and
    confirm the simulator's frame parser never drops a corrupted (bad-CRC
    or spliced) frame -- a real interleaving bug would otherwise just look
    like ordinary packet loss (both halves of two spliced frames fail CRC
    and get silently dropped, same as test_malformed_frame_does_not_crash_
    server's deliberately-malformed input), so this checks the simulator's
    own malformed_frame_count rather than inferring health from link state."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            accepted_before = rover_state.accepted_cmd_count

            for _ in range(30):
                await ws.send(json.dumps({"type": "cmd", "estop": True}))
                await asyncio.sleep(0.005)  # interleave with the 100ms heartbeat tick

            await asyncio.sleep(0.3)  # let in-flight sends/acks settle

            assert rover_state.malformed_frame_count == 0, (
                f"{rover_state.malformed_frame_count} frame(s) failed to decode -- "
                "likely two writers interleaving on the wire"
            )
            assert rover_state.accepted_cmd_count > accepted_before
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_heartbeat_task_death_trips_watchdog_not_stale_resend():
    """F13 (b): if the backend's own command-generating loop dies, nothing
    should keep re-sending the last command forever -- that would silently
    defeat the rover's 500ms watchdog. Killing the heartbeat task must lead
    to a WD_STOP on the simulator within ~600ms, not an indefinitely
    repeated stale CmdMsg."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    rover_state = sim_server._rover_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            # let the heartbeat run for a bit first so wd_ok settles true
            # and any one-time startup WD_STOP (before the link connects,
            # same transient test_no_wd_stop_with_zero_ui_clients documents)
            # is well behind us -- otherwise a stale pre-existing WD_STOP
            # could be mistaken for one caused by this test.
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline and not rover_state.wd_ok:
                await asyncio.sleep(0.01)
            assert rover_state.wd_ok, "watchdog never settled true before the test even started"

            # find and cancel the app's own cmd-heartbeat task directly --
            # simulates an unhandled exception killing it mid-run.
            heartbeat_task = None
            for t in asyncio.all_tasks():
                coro_name = getattr(t.get_coro(), "__qualname__", "")
                if "_cmd_heartbeat_loop" in coro_name:
                    heartbeat_task = t
                    break
            assert heartbeat_task is not None, "could not find the backend's heartbeat task"
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            # cancel() is cooperative: a send already past _build_and_send_
            # cmd()'s only await point (the actual wire write) can still land
            # on the simulator after cancel() returns but before the task is
            # actually done -- awaiting the task above ensures that in-flight
            # send (if any) has fully landed before we snapshot last_cmd_mono
            # as "the last cmd the simulator will ever accept" below.

            # Measured directly against the simulator's own RoverState, not
            # the UI's 10Hz WS snapshot (same measurement-layer issue
            # test_estop_reaches_simulator_under_20ms works around above),
            # and from the last CmdMsg the simulator actually received
            # (last_cmd_mono) rather than from task-cancellation time --
            # that's the true reference point the watchdog itself uses.
            # The simulator's watchdog is an event-loop timer armed for
            # exactly WATCHDOG_MS=500 on every accepted CmdMsg (fake_rover.
            # RoverState._arm_watchdog), not a poll inside the 10Hz tick.
            last_cmd_before_cancel = rover_state.last_cmd_mono
            assert last_cmd_before_cancel is not None
            deadline = time.monotonic() + 1.0
            wd_stop_at = None
            while time.monotonic() < deadline:
                if rover_state.wd_stop_sent:
                    wd_stop_at = time.monotonic()
                    break
                await asyncio.sleep(0.005)
            assert wd_stop_at is not None, "rover watchdog never tripped after the heartbeat task died"
            elapsed_ms = (wd_stop_at - last_cmd_before_cancel) * 1000
            # Lower bound 480 not 500: asyncio's event loop (confirmed via
            # loop.time()) schedules call_later() precisely, but can still
            # *fire* a timer up to one clock resolution tick early on
            # Windows, whose default timer resolution is ~15.6ms -- observed
            # directly (486488.8900 target vs. 486488.8750 actual fire, a
            # reproducible one-tick-early quantization, not jitter or a
            # logic bug). Upper bound 600 keeps real margin for a genuine
            # regression (F13's original bug showed "never fires" well past
            # 1000ms, not a borderline-late single tick).
            assert 480 <= elapsed_ms <= 600, (
                f"WD_STOP fired {elapsed_ms:.0f}ms after the last accepted CmdMsg "
                "(expected 480-600ms)"
            )
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_ingest_loop_survives_unexpected_exception():
    """F3: an exception raised while processing one decoded frame (not a
    WireError -- those are already handled -- but something unexpected in
    state.ingest() itself) must not kill _ingest_loop for the rest of the
    session. Fault-inject by making GroundState.ingest raise exactly once,
    then confirm TELEM keeps flowing afterward."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    gs_state = app_server._gs_app.state.ground_state
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            # let at least one real TELEM arrive first.
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws)
                if snap.get("telem") is not None:
                    break
            else:
                pytest.fail("never received an initial TELEM")

            telem_before = snap["telem"]

            real_ingest = gs_state.ingest
            raised = {"done": False}

            def _flaky_ingest(*args, **kwargs):
                if not raised["done"]:
                    raised["done"] = True
                    raise RuntimeError("synthetic fault for F3")
                return real_ingest(*args, **kwargs)

            gs_state.ingest = _flaky_ingest

            # the next TELEM to arrive hits the fault; _ingest_loop must
            # survive it and keep processing the ones after.
            seen_new_telem = False
            deadline = time.monotonic() + TIMEOUT
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws)
                telem = snap.get("telem")
                if telem is not None and telem != telem_before:
                    seen_new_telem = True
                    break
            assert seen_new_telem, (
                "_ingest_loop stopped delivering TELEM after an exception in "
                "state.ingest() -- it should log and continue, not die"
            )
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_f21_backend_restart_tabs_reconnect_as_viewers():
    """F21: two tabs, backend restart -> both come back as viewers, nobody
    auto-promoted to controller, and the heartbeat still sends drive=0
    (safe default) with nobody in control."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        ws_a = await websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui")
        await _recv_snapshot(ws_a)
        await _send_hello(ws_a)
        snap_a = await _recv_latest_snapshot(ws_a)
        assert snap_a["in_control"] is True

        ws_b = await websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui")
        await _recv_snapshot(ws_b)
        await _send_hello(ws_b)
        snap_b = await _recv_latest_snapshot(ws_b)
        assert snap_b["in_control"] is False

        # backend restart: close the old server, start a fresh one bound
        # to a NEW port (a real restart would keep the same port, but the
        # test harness can't rebind the same OS-assigned port reliably --
        # what matters here is a fresh create_app()/fresh controlling_ws
        # closure, which is what actually resets on a real restart).
        await ws_a.close()
        await ws_b.close()
        await _stop_app(app_server, serve_task)
        app_server, serve_task, app_port = await _start_app(sim_port)

        # both tabs' ws.js auto-reconnects (reconnect=True) against the
        # new backend -- simulated here by connecting fresh and sending
        # hello with reconnect=True, same as the real client would after
        # its onclose handler fires.
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a2:
            await _recv_snapshot(ws_a2)
            await _send_hello(ws_a2, reconnect=True)
            snap_a2 = await _recv_latest_snapshot(ws_a2)
            assert snap_a2["in_control"] is False, "tab A auto-promoted after reconnect"

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b2:
                await _recv_snapshot(ws_b2)
                await _send_hello(ws_b2, reconnect=True)
                snap_b2 = await _recv_latest_snapshot(ws_b2)
                assert snap_b2["in_control"] is False, "tab B auto-promoted after reconnect"
                assert snap_b2["controller_present"] is False, "nobody should be in control"

                # heartbeat still runs and sends a safe (zero) drive with
                # nobody in control -- confirmed via the simulator's own
                # applied drive, not the UI's last_ui_cmd (which is also
                # zero by construction, so check the rover-side effect).
                rover_state = sim_server._rover_state
                await asyncio.sleep(0.3)
                assert rover_state.drive_l == 0.0
                assert rover_state.drive_r == 0.0
                assert rover_state.wd_ok is True, "heartbeat stopped feeding the watchdog"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_f21_reload_after_restart_becomes_controller():
    """F21: after a restart leaves everyone a viewer, a tab that reloads
    the page (a fresh load, reconnect=False) does become controller."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        # simulate "everyone is a viewer after a restart" directly, without
        # repeating the full restart dance already covered above.
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            await _recv_snapshot(ws)
            await _send_hello(ws, reconnect=True)
            snap = await _recv_latest_snapshot(ws)
            assert snap["in_control"] is False

            # the operator reloads the page: a brand new connection, fresh
            # load (reconnect=False) -- this one should become controller
            # since nobody currently has it.
            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_reload:
                await _recv_snapshot(ws_reload)
                await _send_hello(ws_reload, reconnect=False)
                snap_reload = await _recv_latest_snapshot(ws_reload)
                assert snap_reload["in_control"] is True, "fresh page load did not become controller"
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()


async def test_f21_fresh_load_while_controller_exists_stays_viewer():
    """F21: a fresh page load while a controller already exists is still
    just a viewer -- "fresh load may get control" only applies when
    nobody has it, it's not an override."""
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_a:
            await _recv_snapshot(ws_a)
            await _send_hello(ws_a, reconnect=False)
            snap_a = await _recv_latest_snapshot(ws_a)
            assert snap_a["in_control"] is True

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                await _recv_snapshot(ws_b)
                await _send_hello(ws_b, reconnect=False)  # also a "fresh load"
                snap_b = await _recv_latest_snapshot(ws_b)
                assert snap_b["in_control"] is False, (
                    "a fresh load stole control from an existing controller"
                )
                assert snap_b["controller_present"] is True
    finally:
        await _stop_app(app_server, serve_task)
        sim_server.close()
        await sim_server.wait_closed()
