"""link.py integration tests against simulator/fake_rover.py.

Covers the docs/06 Phase 3 checklist: kill the simulator -> LOST/NO_BRIDGE;
restart it -> OK again without restarting the Link. Uses socket:// URLs
bound to OS-assigned ports, matching tests/test_simulator.py conventions.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from ground_station.app import wire
from ground_station.app.link import Link
from ground_station.app.state import GroundState, LinkTracker
from simulator.fake_rover import parse_args, run_server

TIMEOUT = 2.0
RECONNECT_RETRY_S = 0.2


async def _start_simulator():
    args = parse_args([])
    args.host = "127.0.0.1"
    args.port = 0
    server = await run_server(args)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _wait_until(predicate, timeout: float = TIMEOUT) -> None:
    async def _poll():
        while not predicate():
            await asyncio.sleep(0.02)

    await asyncio.wait_for(_poll(), timeout=timeout)


async def test_link_connects_and_receives_frames():
    server, port = await _start_simulator()
    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=RECONNECT_RETRY_S)
    try:
        await link.start()
        frame = await asyncio.wait_for(link.frames().__anext__(), timeout=TIMEOUT)
        assert frame.kind in (wire.SK_RX_FROM_ROVER, wire.SK_BRIDGE_STATUS)
        await _wait_until(link.is_connected)
    finally:
        await link.stop()
        server.close()
        await server.wait_closed()


async def test_link_reconnects_after_simulator_restart():
    server, port, registry = await _start_simulator_with_registry()
    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=RECONNECT_RETRY_S)
    await link.start()
    await _wait_until(link.is_connected)
    # is_connected() flips as soon as the client TCP connect() succeeds,
    # which can race ahead of the server's handle_client() coroutine
    # actually running and registering the writer.
    await _wait_until(lambda: registry.get() is not None)

    # server.close() alone only stops accepting new connections; the
    # already-accepted client socket stays open until something closes it.
    # Closing the simulator's own view of that connection is what actually
    # severs the link, the way killing the simulator process (restarting
    # it) would from the Link's point of view.
    writer = registry.get()
    assert writer is not None
    writer.close()
    server.close()
    await server.wait_closed()
    await _wait_until(lambda: not link.is_connected())

    server2, _, _ = await _start_simulator_with_registry(port=port)
    await _wait_until(link.is_connected, timeout=5.0)

    # Server.wait_closed() (3.12+) only resolves once every accepted
    # connection has dropped too, so stop the Link (closing its end of the
    # socket) before waiting on the server's own close.
    await link.stop()
    server2.close()
    await server2.wait_closed()


async def test_loss_pct_stays_low_against_real_simulator_traffic():
    """End-to-end regression for the loss_pct unwrap bug: a real simulator
    (no --lossy) feeding a real LinkTracker through decoded wire frames for
    5 s must not report significant loss -- it mixes TELEM/HELLO/EVENT/ACK/
    scan-fragment seqs from the same counter, which is exactly the kind of
    slight reordering between message types (D-003) that triggered it."""
    server, port = await _start_simulator()
    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=RECONNECT_RETRY_S)
    tracker = LinkTracker()
    try:
        await link.start()
        deadline = asyncio.get_event_loop().time() + 5.0
        frames = link.frames()
        while asyncio.get_event_loop().time() < deadline:
            frame = await asyncio.wait_for(frames.__anext__(), timeout=TIMEOUT)
            if frame.kind != wire.SK_RX_FROM_ROVER:
                continue
            try:
                decoded = wire.decode_message(frame.payload)
            except wire.WireError:
                continue
            if isinstance(decoded, tuple):
                scan, _part, _parts = decoded
                tracker.on_rover_seq(scan.seq)
            else:
                tracker.on_rover_seq(decoded.seq)
        block = tracker.to_block(
            now_wall_ms=time.time() * 1000.0, connected=True, serial_port="COM5",
        )
        assert block.loss_pct < 2.0
    finally:
        await link.stop()
        server.close()
        await server.wait_closed()


async def test_reboot_after_recovers_loss_pct_and_mission_clock():
    """End-to-end regression: a real simulator reboot (--reboot-after 5)
    must not leave a pre-reboot straggler poisoning _highest_rover_seq
    (the bug: a late seq-114 message after post-reboot seqs 2,3,4 looked
    110 ahead, driving loss_pct to ~96% and STALE for ~6s). With the fixed
    loss metric (unknown/null until LOSS_MIN_SAMPLES, in-flight messages
    excluded from the missing tally), loss_pct must read < 2% (or be null,
    i.e. not enough samples yet -- never a number above 2%) at every
    snapshot from 1s after the restart; exactly one ROVER_RESTART event
    must be logged; and the backend-owned mission clock must stay
    monotonic (not reset) across the reboot."""
    args = parse_args(["--reboot-after", "5"])
    args.host = "127.0.0.1"
    args.port = 0
    server = await run_server(args)
    port = server.sockets[0].getsockname()[1]

    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=RECONNECT_RETRY_S)
    state = GroundState()
    try:
        await link.start()
        deadline = asyncio.get_event_loop().time() + 8.0
        restart_wall_ms = asyncio.get_event_loop().time() * 1000.0 + 6000.0  # ~1s after reboot
        frames = link.frames()
        mission_clock_samples = []
        checked_after_restart = False
        while asyncio.get_event_loop().time() < deadline:
            frame = await asyncio.wait_for(frames.__anext__(), timeout=TIMEOUT)
            recv_wall_ms = time.time() * 1000.0
            if frame.kind != wire.SK_RX_FROM_ROVER:
                continue
            try:
                decoded = wire.decode_message(frame.payload)
            except wire.WireError:
                continue
            if isinstance(decoded, tuple):
                scan, part, parts = decoded
                state.ingest_scan_fragment(scan, part, parts, int(recv_wall_ms))
            else:
                state.ingest(decoded, rssi=None, recv_wall_ms=recv_wall_ms)

            if state.mission_start_wall_ms is not None:
                mission_clock_samples.append(state.mission_start_wall_ms)

            now_loop_ms = asyncio.get_event_loop().time() * 1000.0
            if now_loop_ms >= restart_wall_ms:
                checked_after_restart = True
                block = state.link.to_block(
                    now_wall_ms=recv_wall_ms, connected=True, serial_port="COM5",
                )
                # None (not enough samples yet) is fine -- "unknown" is not
                # a false reading. Any numeric value must be < 2%: the old
                # straggler bug produced ~96% and 6s of STALE.
                assert block.loss_pct is None or block.loss_pct < 2.0, (
                    f"loss_pct={block.loss_pct} at t_loop={now_loop_ms}"
                )
                assert block.state != "STALE"

        assert checked_after_restart
        restart_events = [e for e in state.events if e.code == "ROVER_RESTART"]
        assert len(restart_events) == 1
        # mission_start_wall_ms is set once and never changes once set.
        assert len(set(mission_clock_samples)) == 1

        final_block = state.link.to_block(
            now_wall_ms=time.time() * 1000.0, connected=True, serial_port="COM5",
        )
        assert final_block.loss_pct is not None and final_block.loss_pct < 2.0
    finally:
        await link.stop()
        server.close()
        await server.wait_closed()


async def test_rover_silent_then_resumes_without_restart():
    """End-to-end for docs/06's silent-rover check: --rover-silent-after N
    --rover-silent-for M must take the link OK -> LOST (~2s after the
    rover goes quiet) -> OK again once it resumes, with no ROVER_RESTART
    (t_ms keeps running, unlike --reboot-after) and loss_pct back under 2%
    within 10s of resuming."""
    silent_after = 1.0
    silent_for = 3.0
    args = parse_args(["--rover-silent-after", str(silent_after), "--rover-silent-for", str(silent_for)])
    args.host = "127.0.0.1"
    args.port = 0
    server = await run_server(args)
    port = server.sockets[0].getsockname()[1]

    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=RECONNECT_RETRY_S)
    state = GroundState()
    try:
        await link.start()
        start_loop = asyncio.get_event_loop().time()
        deadline = start_loop + silent_after + silent_for + 12.0
        frames = link.frames()

        saw_ok_before_silence = False
        saw_lost_during_silence = False
        saw_ok_after_resume = False
        resume_loop_t: Optional[float] = None
        recovered_at: Optional[float] = None

        while asyncio.get_event_loop().time() < deadline:
            frame = await asyncio.wait_for(frames.__anext__(), timeout=TIMEOUT)
            recv_wall_ms = time.time() * 1000.0
            if frame.kind == wire.SK_RX_FROM_ROVER:
                try:
                    decoded = wire.decode_message(frame.payload)
                except wire.WireError:
                    decoded = None
                if decoded is not None:
                    if isinstance(decoded, tuple):
                        scan, part, parts = decoded
                        state.ingest_scan_fragment(scan, part, parts, int(recv_wall_ms))
                    else:
                        state.ingest(decoded, rssi=None, recv_wall_ms=recv_wall_ms)
                    now_loop = asyncio.get_event_loop().time()
                    if now_loop >= start_loop + silent_after + silent_for and resume_loop_t is None:
                        resume_loop_t = now_loop

            now_loop = asyncio.get_event_loop().time()
            block = state.link.to_block(now_wall_ms=recv_wall_ms, connected=True, serial_port="COM5")

            if now_loop < start_loop + silent_after - 0.3 and block.state == "OK":
                saw_ok_before_silence = True
            if now_loop >= start_loop + silent_after + 2.0 and now_loop < start_loop + silent_after + silent_for:
                if block.state == "LOST":
                    saw_lost_during_silence = True
            if resume_loop_t is not None and now_loop >= resume_loop_t:
                if block.state == "OK":
                    saw_ok_after_resume = True
                    if recovered_at is None:
                        recovered_at = now_loop
                # the docs/06 check is "loss back under 2% within 10s of
                # resuming" -- not instantly: a fresh straggler from right
                # before the silence can transiently inflate loss_pct until
                # enough post-resume samples replace it (see
                # test_reboot_after_recovers_loss_pct_and_mission_clock).
                if recovered_at is not None and now_loop - recovered_at >= 10.0:
                    assert block.loss_pct is None or block.loss_pct < 2.0, (
                        f"loss_pct={block.loss_pct} at t={now_loop - recovered_at:.1f}s after resume"
                    )

        assert saw_ok_before_silence
        assert saw_lost_during_silence
        assert saw_ok_after_resume
        assert not [e for e in state.events if e.code == "ROVER_RESTART"]

        final_block = state.link.to_block(now_wall_ms=time.time() * 1000.0, connected=True, serial_port="COM5")
        assert final_block.loss_pct is not None and final_block.loss_pct < 2.0
    finally:
        await link.stop()
        server.close()
        await server.wait_closed()


async def _start_simulator_with_registry(port: int = 0):
    """Like fake_rover.run_server(), but also hands back the _ClientRegistry
    so the test can sever the accepted connection the way a killed/restarted
    simulator process would (server.close() alone only stops new accepts)."""
    from simulator.fake_rover import _ClientRegistry, _driver_loop, build_state, handle_client

    args = parse_args([])
    args.host = "127.0.0.1"
    args.port = port
    state = build_state(args)
    registry = _ClientRegistry()

    async def _handler(reader, writer):
        await handle_client(reader, writer, state, registry, args)

    server = await asyncio.start_server(_handler, args.host, args.port)
    asyncio.create_task(_driver_loop(state, registry, args))
    actual_port = server.sockets[0].getsockname()[1]
    return server, actual_port, registry
