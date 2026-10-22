"""Golden-bytes tests — docs/02 §4.

tests/golden/*.hex are generated from the REAL C structs by
tools/golden_gen.cpp, independent of wire.py. wire.py must decode every
.hex to the expected JSON (tests/golden/expected.json) and re-encode it
to the identical bytes. Never regenerate the golden files from Python.
"""
import json
import math
from pathlib import Path

import pytest

from ground_station.app import wire

GOLDEN_DIR = Path(__file__).parent / "golden"
EXPECTED = json.loads((GOLDEN_DIR / "expected.json").read_text())


def _hex(name: str) -> bytes:
    return bytes.fromhex((GOLDEN_DIR / f"{name}.hex").read_text().strip())


def _approx_equal(a, b, tol=1e-4):
    if a is None or b is None:
        return a == b
    if isinstance(a, float) or isinstance(b, float):
        return math.isclose(a, b, abs_tol=tol)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_approx_equal(x, y, tol) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_approx_equal(a[k], b[k], tol) for k in a)
    return a == b


def test_hello_roundtrip():
    raw = _hex("hello")
    msg = wire.decode_hello(raw)
    expected = EXPECTED["hello"]
    assert msg.fw == expected["fw"]
    assert msg.reset_reason == expected["reset_reason"]
    assert msg.hw.imu.present == expected["hw"]["imu"]["present"]
    assert msg.hw.env.present == expected["hw"]["env"]["present"]
    assert msg.hw.env.model == expected["hw"]["env"]["model"]
    assert msg.hw.sonar.servo == expected["hw"]["sonar"]["servo"]
    assert msg.hw.battery.cells == expected["hw"]["battery"]["cells"]
    assert msg.hw.encoders.cpr == expected["hw"]["encoders"]["cpr"]
    assert msg.hw.lidar.present == expected["hw"]["lidar"]["present"]
    assert msg.hw.lidar.model == expected["hw"]["lidar"]["model"]
    assert msg.hw.buzzer.present == expected["hw"]["buzzer"]["present"]

    re_encoded = wire.encode_hello(msg)
    assert re_encoded == raw


def test_telem_roundtrip():
    raw = _hex("telem")
    msg = wire.decode_telem(raw)
    expected = EXPECTED["telem"]
    assert _approx_equal(msg.env.model_dump(), expected["env"])
    assert _approx_equal(msg.light.model_dump(), expected["light"])
    assert _approx_equal(msg.pwr.model_dump(), expected["pwr"])
    assert _approx_equal(msg.mot.model_dump(), expected["mot"])
    assert _approx_equal(msg.odom.model_dump(), expected["odom"])
    assert _approx_equal(msg.imu.model_dump(), expected["imu"])
    assert _approx_equal(msg.sonar.model_dump(), expected["sonar"])
    assert msg.state.mode == expected["state"]["mode"]
    assert msg.state.estop == expected["state"]["estop"]
    assert msg.state.wd_ok == expected["state"]["wd_ok"]
    assert msg.state.last_cmd_age_ms == expected["state"]["last_cmd_age_ms"]
    assert _approx_equal(msg.sys.model_dump(), expected["sys"])

    re_encoded = wire.encode_telem(msg)
    assert re_encoded == raw


def test_scan_sonar_roundtrip():
    raw = _hex("scan_sonar")
    msg, part, parts = wire.decode_scan_fragment(raw)
    expected = EXPECTED["scan_sonar"]
    assert msg.src == expected["src"]
    assert msg.scan_id == expected["scan_id"]
    assert _approx_equal(msg.pose.model_dump(), expected["pose"])
    assert _approx_equal(msg.pts, expected["pts"])
    assert part == 0 and parts == 1

    re_encoded = wire.encode_scan_fragment(
        seq=msg.seq, t_ms=msg.t, src=msg.src, scan_id=msg.scan_id,
        part=part, parts=parts,
        yaw_deg=msg.pose.yaw_deg, x_m=msg.pose.x_m, y_m=msg.pose.y_m,
        start_cdeg=0, step_cdeg=1000,
        dist_cm=[p[1] for p in msg.pts],
    )
    assert re_encoded == raw


def test_event_roundtrip():
    raw = _hex("event")
    msg = wire.decode_event(raw)
    expected = EXPECTED["event"]
    assert msg.level == expected["level"]
    assert msg.code == expected["code"]
    assert msg.msg == expected["msg"]

    re_encoded = wire.encode_event(msg)
    assert re_encoded == raw


def test_ack_roundtrip():
    raw = _hex("ack")
    msg = wire.decode_ack(raw)
    expected = EXPECTED["ack"]
    assert msg.ack_seq == expected["ack_seq"]
    assert msg.ok == expected["ok"]

    re_encoded = wire.encode_ack(msg)
    assert re_encoded == raw


def test_cmd_roundtrip():
    raw = _hex("cmd")
    msg = wire.decode_cmd(raw)
    expected = EXPECTED["cmd"]
    assert _approx_equal(msg.drive.model_dump(), expected["drive"])
    assert msg.mode == expected["mode"]
    assert _approx_equal(msg.servo.model_dump(), expected["servo"])
    assert msg.estop == expected["estop"]
    assert msg.estop_reset == expected["estop_reset"]
    assert msg.buzzer == expected["buzzer"]
    assert msg.request_hello == expected["request_hello"]
    assert msg.goto is None and expected["goto"] is None

    re_encoded = wire.encode_cmd(msg)
    assert re_encoded == raw


def test_bridge_status_roundtrip():
    raw = _hex("bridge_status")
    status = wire.decode_bridge_status(raw)
    expected = EXPECTED["bridge_status"]
    assert status.uptime_ms == expected["uptime_ms"]
    assert status.rx_count == expected["rx_count"]
    assert status.tx_ok == expected["tx_ok"]
    assert status.tx_fail == expected["tx_fail"]
    assert status.channel == expected["channel"]
    assert status.last_rssi == expected["last_rssi"]
    assert status.rover_paired == expected["rover_paired"]

    re_encoded = wire.encode_bridge_status(status)
    assert re_encoded == raw


def test_joystick_roundtrip():
    raw = _hex("joystick")
    state = wire.decode_joystick(raw)
    expected = EXPECTED["joystick"]
    assert state.lx == expected["lx"]
    assert state.ly == expected["ly"]
    assert state.rx == expected["rx"]
    assert state.ry == expected["ry"]
    assert state.buttons == expected["buttons"]
    assert state.seq == expected["seq"]

    re_encoded = wire.encode_joystick(state)
    assert re_encoded == raw


def test_serial_frame_telem():
    raw = _hex("serial_frame_telem")
    expected = EXPECTED["serial_frame_telem"]
    assert raw[-1] == 0x00
    frame = wire.decode_serial_frame(raw[:-1])
    assert frame.kind == expected["kind"]
    assert frame.rssi == expected["rssi"]
    assert frame.payload == _hex(expected["payload_file"].removesuffix(".hex"))

    re_encoded = wire.encode_serial_frame(frame.kind, frame.rssi, frame.payload)
    assert re_encoded == raw


def test_serial_frame_joystick():
    raw = _hex("serial_frame_joystick")
    expected = EXPECTED["serial_frame_joystick"]
    assert raw[-1] == 0x00
    frame = wire.decode_serial_frame(raw[:-1])
    assert frame.kind == expected["kind"]
    assert frame.rssi == expected["rssi"]
    assert frame.payload == _hex(expected["payload_file"].removesuffix(".hex"))

    re_encoded = wire.encode_serial_frame(frame.kind, frame.rssi, frame.payload)
    assert re_encoded == raw


def test_crc16_check_vector():
    assert wire._crc16_ccitt_false(b"123456789") == 0x29B1


def test_bad_magic_rejected_without_exception():
    raw = _hex("telem")
    corrupted = bytes([0x00]) + raw[1:]
    with pytest.raises(wire.WireError):
        wire.decode_message(corrupted)


def test_bad_crc_rejected_without_exception():
    raw = _hex("serial_frame_telem")[:-1]
    body = bytearray(raw)
    body[-1] ^= 0xFF  # corrupt one byte inside the COBS-encoded frame
    with pytest.raises(wire.WireError):
        wire.decode_serial_frame(bytes(body))
