"""link.py integration tests against simulator/fake_rover.py.

Covers the docs/06 Phase 3 checklist: kill the simulator -> LOST/NO_BRIDGE;
restart it -> OK again without restarting the Link. Uses socket:// URLs
bound to OS-assigned ports, matching tests/test_simulator.py conventions.
"""
from __future__ import annotations

import asyncio

from ground_station.app import wire
from ground_station.app.link import Link
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
        await handle_client(reader, writer, state, registry)

    server = await asyncio.start_server(_handler, args.host, args.port)
    asyncio.create_task(_driver_loop(state, registry, args))
    actual_port = server.sockets[0].getsockname()[1]
    return server, actual_port, registry
