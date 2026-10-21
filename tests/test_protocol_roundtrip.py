"""Protocol round-trip tests — docs/02 §2-3 JSON examples must survive
model -> bytes -> model, and lidar scan fragment reassembly (4 fragments,
300 ms timeout -> missing angles become null).
"""
import math

from ground_station.app import wire
from ground_station.app.protocol import (
    AckMsg,
    CmdDrive,
    CmdMsg,
    CmdServo,
    EventMsg,
    Hw,
    HwBattery,
    HwBuzzer,
    HwCurrent,
    HwEncoders,
    HwEnv,
    HwImu,
    HwLidar,
    HwLight,
    HwSonar,
    HelloMsg,
    ScanMsg,
    ScanPose,
    TelemEnv,
    TelemImu,
    TelemLight,
    TelemMot,
    TelemMsg,
    TelemOdom,
    TelemPwr,
    TelemSonar,
    TelemState,
    TelemSys,
)
from ground_station.app.scan_reassembly import ScanReassembler


def test_hello_json_roundtrip():
    hw = Hw(
        imu=HwImu(present=True), env=HwEnv(present=True, model="bme280"),
        light=HwLight(present=True), sonar=HwSonar(present=True, servo=True),
        battery=HwBattery(present=True, cells=3), current=HwCurrent(present=False),
        encoders=HwEncoders(present=False, cpr=0), lidar=HwLidar(present=False, model=None),
        buzzer=HwBuzzer(present=True),
    )
    msg = HelloMsg(t=120, seq=0, fw="rover_main 0.1.0", reset_reason="POWERON", hw=hw)
    raw = wire.encode_hello(msg)
    back = wire.decode_hello(raw)
    assert back.fw == msg.fw
    assert back.reset_reason == msg.reset_reason
    assert back.hw.sonar.servo is True


def test_telem_json_roundtrip():
    msg = TelemMsg(
        t=12345, seq=88,
        env=TelemEnv(temp_c=22.4, hum_pct=41.0, press_hpa=1012.3, alt_m=0.4),
        light=TelemLight(lux=340),
        pwr=TelemPwr(vbat_v=11.42, soc_pct=71, ibat_a=None, p_w=None),
        mot=TelemMot(pwm_l=180, pwm_r=175, rpm_l=None, rpm_r=None),
        odom=TelemOdom(x_m=None, y_m=None, dist_m=None),
        imu=TelemImu(roll_deg=1.2, pitch_deg=-0.4, yaw_deg=87.5, ax_g=0.01, ay_g=-0.02,
                     az_g=1.00, gz_dps=0.3, temp_c=31.2),
        sonar=TelemSonar(angle_deg=45, dist_cm=63),
        state=TelemState(mode="manual", estop=False, wd_ok=True, last_cmd_age_ms=40),
        sys=TelemSys(rssi_dbm=-61, heap_b=182000, uptime_s=340, loop_hz=98, chip_temp_c=48),
    )
    raw = wire.encode_telem(msg)
    back = wire.decode_telem(raw)
    assert back.pwr.ibat_a is None
    assert back.mot.pwm_l == 180
    assert math.isclose(back.env.temp_c, 22.4, abs_tol=1e-4)


def test_event_json_roundtrip():
    msg = EventMsg(t=14000, seq=101, level="warn", code="BATT_LOW", msg="vbat 10.4 V")
    raw = wire.encode_event(msg)
    back = wire.decode_event(raw)
    assert back == msg


def test_ack_json_roundtrip():
    msg = AckMsg(t=5010, seq=90, ack_seq=42, ok=True)
    raw = wire.encode_ack(msg)
    back = wire.decode_ack(raw)
    assert back == msg


def test_cmd_json_roundtrip():
    msg = CmdMsg(
        t=5000, seq=42, drive=CmdDrive(l=0.6, r=0.6), mode="manual",
        servo=CmdServo(mode="sweep", angle_deg=90), estop=False, estop_reset=False,
        buzzer=False, request_hello=False, goto=None,
    )
    raw = wire.encode_cmd(msg)
    back = wire.decode_cmd(raw)
    assert math.isclose(back.drive.l, msg.drive.l, abs_tol=1e-4)
    assert back.goto is None


def test_scan_sonar_single_fragment_roundtrip():
    msg = ScanMsg(
        t=13000, seq=95, src="sonar", scan_id=12,
        pose=ScanPose(x_m=None, y_m=None, yaw_deg=87.5),
        pts=[[0, 120], [10, 118], [20, None]],
    )
    raw = wire.encode_scan_fragment(
        seq=msg.seq, t_ms=msg.t, src=msg.src, scan_id=msg.scan_id, part=0, parts=1,
        yaw_deg=msg.pose.yaw_deg, x_m=msg.pose.x_m, y_m=msg.pose.y_m,
        start_cdeg=0, step_cdeg=1000, dist_cm=[p[1] for p in msg.pts],
    )
    back, part, parts = wire.decode_scan_fragment(raw)
    assert part == 0 and parts == 1
    assert back.pts == [[0.0, 120], [10.0, 118], [20.0, None]]


def _lidar_fragment(part: int, parts: int, n: int, scan_id: int = 7):
    start_cdeg = part * n * 100
    dists = [1000 + part * 100 + i for i in range(n)]
    raw = wire.encode_scan_fragment(
        seq=part, t_ms=1000, src="lidar", scan_id=scan_id, part=part, parts=parts,
        yaw_deg=10.0, x_m=None, y_m=None,
        start_cdeg=start_cdeg, step_cdeg=100, dist_cm=dists,
    )
    return wire.decode_scan_fragment(raw)


def test_lidar_scan_reassembles_from_four_fragments():
    reassembler = ScanReassembler()
    result = None
    for part in range(4):
        scan, p, parts = _lidar_fragment(part, 4, n=90)
        result = reassembler.add_fragment(scan, p, parts, now_ms=1000 + part)
    assert result is not None
    assert len(result.pts) == 360
    assert all(pt[1] is not None for pt in result.pts)


def test_lidar_scan_missing_fragment_yields_nulls_after_timeout():
    reassembler = ScanReassembler(timeout_ms=300)
    for part in (0, 1, 3):  # fragment 2 never arrives
        scan, p, parts = _lidar_fragment(part, 4, n=90)
        result = reassembler.add_fragment(scan, p, parts, now_ms=1000)
    assert result is None  # not complete yet

    result = reassembler.poll_timeouts(now_ms=1000 + 301)
    assert result is not None
    assert len(result.pts) == 360
    missing = result.pts[180:270]
    assert all(pt[1] is None for pt in missing)
    present = result.pts[0:180] + result.pts[270:360]
    assert all(pt[1] is not None for pt in present)


def test_f23_crc_bad_telem_frame_is_rejected_cleanly():
    """F23: GS receiving a CRC-bad (or otherwise corrupted) TELEM frame --
    decode_serial_frame must raise wire.WireError (dropped, counted by
    main.py's _ingest_loop debug log, F3's try/except), never crash and
    never silently decode garbage as if it were valid telem."""
    msg = TelemMsg(
        t=500, seq=7,
        env=TelemEnv(), light=TelemLight(), pwr=TelemPwr(),
        mot=TelemMot(pwm_l=0, pwm_r=0), odom=TelemOdom(),
        imu=TelemImu(), sonar=TelemSonar(),
        state=TelemState(mode="idle", estop=False, wd_ok=True, last_cmd_age_ms=0),
        sys=TelemSys(rssi_dbm=-60, heap_b=1000, uptime_s=1, loop_hz=100),
    )
    payload = wire.encode_telem(msg)
    good_frame = wire.encode_serial_frame(wire.SK_RX_FROM_ROVER, rssi=-55, payload=payload)

    # the valid frame decodes and round-trips correctly (sanity baseline).
    good_sf = wire.decode_serial_frame(good_frame[:-1])  # strip the \x00 delimiter
    good_msg = wire.decode_message(good_sf.payload)
    assert good_msg.seq == 7

    # corrupt one payload byte (after COBS decoding + CRC check, this must
    # fail CRC validation -- it's deep enough into the frame that COBS
    # framing itself still parses, isolating the CRC check specifically).
    corrupted = bytearray(good_frame[:-1])
    corrupted[len(corrupted) // 2] ^= 0xFF
    try:
        wire.decode_serial_frame(bytes(corrupted))
        assert False, "corrupted frame should have failed CRC validation"
    except wire.WireError:
        pass  # expected -- this is what main.py's _ingest_loop/Link._handle_frame catch


async def test_f23_link_survives_crc_bad_frame_and_keeps_delivering_good_ones():
    """F23 (integration): a CRC-bad frame arriving on the wire must not
    wedge Link -- the next good frame after it must still be delivered."""
    import asyncio
    import socket

    from ground_station.app.link import Link

    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    port = _free_port()

    msg = TelemMsg(
        t=500, seq=7,
        env=TelemEnv(), light=TelemLight(), pwr=TelemPwr(),
        mot=TelemMot(pwm_l=0, pwm_r=0), odom=TelemOdom(),
        imu=TelemImu(), sonar=TelemSonar(),
        state=TelemState(mode="idle", estop=False, wd_ok=True, last_cmd_age_ms=0),
        sys=TelemSys(rssi_dbm=-60, heap_b=1000, uptime_s=1, loop_hz=100),
    )
    good_frame = wire.encode_serial_frame(
        wire.SK_RX_FROM_ROVER, rssi=-55, payload=wire.encode_telem(msg),
    )
    corrupted = bytearray(good_frame)
    corrupted[len(corrupted) // 2] ^= 0xFF

    async def _handler(reader, writer):
        writer.write(bytes(corrupted))  # CRC-bad frame first
        await writer.drain()
        await asyncio.sleep(0.05)
        writer.write(good_frame)  # then a good one
        await writer.drain()
        await asyncio.sleep(1.0)  # keep the connection open while Link reads
        writer.close()

    server = await asyncio.start_server(_handler, "127.0.0.1", port)
    link = Link(f"socket://127.0.0.1:{port}", reconnect_retry_s=0.2)
    try:
        await link.start()
        frame = await asyncio.wait_for(link.frames().__anext__(), timeout=2.0)
        assert frame.kind == wire.SK_RX_FROM_ROVER
        decoded = wire.decode_message(frame.payload)
        assert decoded.seq == 7, "the good frame after the corrupted one was not delivered"
    finally:
        await link.stop()
        server.close()
        await server.wait_closed()
