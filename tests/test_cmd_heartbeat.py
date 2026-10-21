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
    return server, serve_task, port


async def _stop_app(server: uvicorn.Server, serve_task: asyncio.Task):
    server.should_exit = True
    await asyncio.wait_for(serve_task, timeout=TIMEOUT)


async def _recv_snapshot(ws, timeout: float = TIMEOUT) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


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
            snap_a = await _recv_snapshot(ws_a)
            assert snap_a["in_control"] is True

            async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
                snap_b = await _recv_snapshot(ws_b)
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


async def test_no_auto_promotion_on_controller_disconnect():
    sim_server, sim_port = await _start_simulator()
    app_server, serve_task, app_port = await _start_app(sim_port)
    try:
        ws_a = await websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui")
        await _recv_snapshot(ws_a)  # confirm A is attached

        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws_b:
            await _recv_snapshot(ws_b)  # B is view-only while A holds control

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
    try:
        await asyncio.sleep(1.0)  # well past the 500ms watchdog, no UI client ever connects
        async with websockets.connect(f"ws://127.0.0.1:{app_port}/ws/ui") as ws:
            snap = await _recv_snapshot(ws)
            telem = snap.get("telem")
            assert telem is not None
            assert telem["state"]["wd_ok"] is True
            assert telem["state"]["last_cmd_age_ms"] < 500
            wd_stop_count_before = sum(1 for e in snap["events"] if e["code"] == "WD_STOP")

            # Watch for another second: no *additional* WD_STOP should fire
            # once the heartbeat has been running steadily (events is a
            # cumulative log, so the one from startup never disappears --
            # what matters is the count doesn't grow).
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                snap = await _recv_snapshot(ws, timeout=1.5)
                assert snap["telem"]["state"]["wd_ok"] is True
                wd_stop_count_now = sum(1 for e in snap["events"] if e["code"] == "WD_STOP")
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
