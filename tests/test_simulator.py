"""simulator/fake_rover.py tests — docs/06 Phase 2 checklist.

Covers: connect -> HELLO + TELEM; watchdog fires (WD_STOP) when no CmdMsg
arrives; rover state survives client disconnect/reconnect; only one client
is accepted at a time; malformed frames don't crash the server.

Every network wait is wrapped in asyncio.wait_for(..., timeout=...) so a
broken server fails the test instead of hanging pytest. The server always
binds to port 0 (OS-assigned free port), never the real default 8765, so
these tests never collide with a simulator the user has running locally.
"""
from __future__ import annotations

import asyncio

import pytest

from ground_station.app import wire
from simulator.fake_rover import parse_args, run_server

TIMEOUT = 2.0


async def _start(argv: list[str] | None = None):
    args = parse_args(argv or [])
    args.host = "127.0.0.1"
    args.port = 0
    server = await run_server(args)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _connect(port: int):
    return await asyncio.wait_for(
        asyncio.open_connection("127.0.0.1", port), timeout=TIMEOUT
    )


async def _read_message(reader: asyncio.StreamReader):
    """Read one COBS-framed serial message and decode it. Returns (kind, decoded|None)."""
    raw = await asyncio.wait_for(reader.readuntil(b"\x00"), timeout=TIMEOUT)
    frame = wire.decode_serial_frame(raw[:-1])
    if frame.kind == wire.SK_RX_FROM_ROVER:
        try:
            return frame.kind, wire.decode_message(frame.payload)
        except wire.UnknownMsgType:
            return frame.kind, None
    return frame.kind, None


async def test_connect_receives_hello_then_telem():
    server, port = await _start()
    try:
        reader, writer = await _connect(port)
        try:
            kinds_seen = set()
            msg_types = set()
            for _ in range(20):
                kind, decoded = await _read_message(reader)
                kinds_seen.add(kind)
                if decoded is not None:
                    msg_types.add(type(decoded).__name__)
                if "HelloMsg" in msg_types and "TelemMsg" in msg_types:
                    break
            assert "HelloMsg" in msg_types
            assert "TelemMsg" in msg_types
        finally:
            writer.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_watchdog_fires_without_cmd():
    server, port = await _start()
    try:
        reader, writer = await _connect(port)
        try:
            saw_wd_stop = False
            saw_wd_not_ok = False
            deadline_iters = 40  # ~ a few seconds of telem/event frames at worst case
            for _ in range(deadline_iters):
                kind, decoded = await _read_message(reader)
                if decoded is None:
                    continue
                if type(decoded).__name__ == "TelemMsg" and not decoded.state.wd_ok:
                    saw_wd_not_ok = True
                if type(decoded).__name__ == "EventMsg" and decoded.code == "WD_STOP":
                    saw_wd_stop = True
                if saw_wd_stop and saw_wd_not_ok:
                    break
            assert saw_wd_not_ok
            assert saw_wd_stop
        finally:
            writer.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_state_persists_across_reconnect():
    server, port = await _start()
    try:
        reader1, writer1 = await _connect(port)
        vbat_first = None
        for _ in range(20):
            _, decoded = await _read_message(reader1)
            if decoded is not None and type(decoded).__name__ == "TelemMsg":
                vbat_first = decoded.pwr.vbat_v
                break
        assert vbat_first is not None
        writer1.close()
        await asyncio.sleep(0.2)

        reader2, writer2 = await _connect(port)
        try:
            vbat_second = None
            for _ in range(20):
                _, decoded = await _read_message(reader2)
                if decoded is not None and type(decoded).__name__ == "TelemMsg":
                    vbat_second = decoded.pwr.vbat_v
                    break
            assert vbat_second is not None
            # battery only ever drains (monotonic non-increasing), never resets to 12.6
            assert vbat_second <= vbat_first + 1e-6
        finally:
            writer2.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_second_client_rejected():
    server, port = await _start()
    try:
        reader_a, writer_a = await _connect(port)
        try:
            # drain a frame to be sure A is fully attached
            await _read_message(reader_a)

            reader_b, writer_b = await _connect(port)
            # server should close B immediately without reading anything
            data = await asyncio.wait_for(reader_b.read(1), timeout=TIMEOUT)
            assert data == b""  # EOF: rejected
            writer_b.close()

            # A must still be receiving frames
            kind, decoded = await _read_message(reader_a)
            assert kind == wire.SK_RX_FROM_ROVER
        finally:
            writer_a.close()
    finally:
        server.close()
        await server.wait_closed()


async def test_malformed_frame_does_not_crash_server():
    server, port = await _start()
    try:
        reader, writer = await _connect(port)
        try:
            # garbage bytes followed by the frame delimiter
            writer.write(b"\xff\xfe\xfd\x00")
            await writer.drain()

            # server must still be alive and keep sending telemetry
            kind, decoded = await _read_message(reader)
            assert kind == wire.SK_RX_FROM_ROVER
        finally:
            writer.close()
    finally:
        server.close()
        await server.wait_closed()
