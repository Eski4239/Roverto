"""Binary wire codec — docs/02_TELEMETRY_PROTOCOL.md §4, firmware/common/rover_protocol.h.

Converts between the C structs on the radio/serial link and the pydantic
logical models in protocol.py. NaN <-> None, 0xFFFF <-> None, hw_present
bitmask <-> hello.hw, numeric enums <-> strings.

Struct formats here are the single Python mirror of rover_protocol.h and
must match it exactly (verified against tests/golden/*.hex, generated
independently from the real C structs by tools/golden_gen.cpp).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Optional

from cobs import cobs

from ground_station.app.protocol import (
    AckMsg,
    CmdDrive,
    CmdGoto,
    CmdMsg,
    CmdServo,
    EventMsg,
    Hw,
    HwBattery,
    HwBuzzer,
    HwCamera,
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

# ----------------------------------------------------------- constants ----

PROTO_MAGIC = 0xA7
PROTO_VER = 1

MSG_HELLO = 0x01
MSG_TELEM = 0x02
MSG_SCAN = 0x03
MSG_EVENT = 0x04
MSG_ACK = 0x05
MSG_CMD = 0x10

HW_IMU, HW_ENV, HW_LIGHT, HW_SONAR, HW_BATTERY = 0, 1, 2, 3, 4
HW_CURRENT, HW_ENCODERS, HW_CAMERA, HW_LIDAR, HW_BUZZER, HW_SERVO = 5, 6, 7, 8, 9, 10

ENV_MODEL = {0: None, 1: "bme280", 2: "bmp280", 3: "dht11"}
ENV_MODEL_INV = {v: k for k, v in ENV_MODEL.items() if v is not None}

LIDAR_MODEL = {0: None, 1: "ld06", 2: "ld19", 3: "rplidar_c1"}
LIDAR_MODEL_INV = {v: k for k, v in LIDAR_MODEL.items() if v is not None}

MODE = {0: "idle", 1: "manual", 2: "assisted", 3: "auto"}
MODE_INV = {v: k for k, v in MODE.items()}

SCAN_SRC = {1: "sonar", 2: "lidar"}
SCAN_SRC_INV = {v: k for k, v in SCAN_SRC.items()}

EV_LEVEL = {0: "info", 1: "warn", 2: "error"}
EV_LEVEL_INV = {v: k for k, v in EV_LEVEL.items()}

EV_CODE = {
    1: "BOOT", 2: "BATT_LOW", 3: "BATT_CRIT", 4: "TILT", 5: "WD_STOP",
    6: "ESTOP", 7: "SENSOR_LOST", 8: "OBSTACLE", 9: "CMD_REJECTED",
}
EV_CODE_INV = {v: k for k, v in EV_CODE.items()}

# docs/02 §6.5
RESET_REASON = {
    0: "UNKNOWN", 1: "POWERON", 2: "EXT", 3: "SW", 4: "PANIC",
    5: "INT_WDT", 6: "TASK_WDT", 7: "WDT", 8: "DEEPSLEEP", 9: "BROWNOUT",
    10: "SDIO", 11: "USB", 12: "JTAG", 13: "EFUSE", 14: "PWR_GLITCH",
    15: "CPU_LOCKUP",
}
RESET_REASON_INV = {v: k for k, v in RESET_REASON.items()}


def _reset_reason_str(code: int) -> str:
    return RESET_REASON.get(code, f"UNKNOWN_{code}")


def _reset_reason_code(name: str) -> int:
    if name in RESET_REASON_INV:
        return RESET_REASON_INV[name]
    if name.startswith("UNKNOWN_"):
        return int(name.removeprefix("UNKNOWN_"))
    return 0

# -------------------------------------------------------- struct formats ----

HEADER_FMT = "<BBBBHI"
HEADER_SIZE = struct.calcsize(HEADER_FMT)  # 10

HELLO_FMT = "<BBBBHI20sHBBBBBB"
HELLO_SIZE = struct.calcsize(HELLO_FMT)  # 38

TELEM_FMT = "<BBBBHIfffffffffhhfffffffffffffffBBHbIIHf"
TELEM_SIZE = struct.calcsize(TELEM_FMT)  # 129

SCAN_HEADER_FMT = "<BBBBHIBBBBfffHHB"
SCAN_HEADER_SIZE = struct.calcsize(SCAN_HEADER_FMT)  # 31

EVENT_FMT = "<BBBBHIBB60s"
EVENT_SIZE = struct.calcsize(EVENT_FMT)  # 72

ACK_FMT = "<BBBBHIHB"
ACK_SIZE = struct.calcsize(ACK_FMT)  # 13

CMD_FMT = "<BBBBHIffBBBBff"
CMD_SIZE = struct.calcsize(CMD_FMT)  # 30

BRIDGE_STATUS_FMT = "<IIIIBbB"
BRIDGE_STATUS_SIZE = struct.calcsize(BRIDGE_STATUS_FMT)  # 19

JOYSTICK_FMT = "<HHHHBB"
JOYSTICK_SIZE = struct.calcsize(JOYSTICK_FMT)  # 10

assert HEADER_SIZE == 10
assert HELLO_SIZE == 38
assert TELEM_SIZE == 129
assert SCAN_HEADER_SIZE == 31
assert EVENT_SIZE == 72
assert ACK_SIZE == 13
assert CMD_SIZE == 30
assert BRIDGE_STATUS_SIZE == 19

# ----------------------------------------------------------------- misc ----


def _nan_to_none(x: float) -> Optional[float]:
    return None if math.isnan(x) else x


def _none_to_nan(x: Optional[float]) -> float:
    return math.nan if x is None else x


def _dist_to_json(x: int) -> Optional[int]:
    return None if x == 0xFFFF else x


def _dist_to_wire(x: Optional[float]) -> int:
    return 0xFFFF if x is None else int(round(x))


class WireError(Exception):
    """Raised on malformed input; never escapes as a crash to the caller."""


class UnknownMsgType(WireError):
    pass


@dataclass
class Header:
    magic: int
    ver: int
    type: int
    flags: int
    seq: int
    t_ms: int


def decode_header(b: bytes) -> Header:
    magic, ver, type_, flags, seq, t_ms = struct.unpack_from(HEADER_FMT, b, 0)
    return Header(magic, ver, type_, flags, seq, t_ms)


def _encode_header(type_: int, seq: int, t_ms: int) -> bytes:
    return struct.pack(HEADER_FMT, PROTO_MAGIC, PROTO_VER, type_, 0, seq, t_ms)


# ---------------------------------------------------------------- HELLO ----


def decode_hello(b: bytes) -> HelloMsg:
    (magic, ver, type_, flags, seq, t_ms, fw_raw, hw_present,
     env_model, lidar_model, cells, reset_reason, encoder_cpr, _reserved) = \
        struct.unpack_from(HELLO_FMT, b, 0)
    fw = fw_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")

    def bit(n: int) -> bool:
        return bool(hw_present & (1 << n))

    hw = Hw(
        imu=HwImu(present=bit(HW_IMU)),
        env=HwEnv(present=bit(HW_ENV), model=ENV_MODEL.get(env_model) if bit(HW_ENV) else None),
        light=HwLight(present=bit(HW_LIGHT)),
        sonar=HwSonar(present=bit(HW_SONAR), servo=bit(HW_SERVO)),
        battery=HwBattery(present=bit(HW_BATTERY), cells=cells if bit(HW_BATTERY) else 0),
        current=HwCurrent(present=bit(HW_CURRENT)),
        encoders=HwEncoders(present=bit(HW_ENCODERS), cpr=encoder_cpr if bit(HW_ENCODERS) else 0),
        lidar=HwLidar(present=bit(HW_LIDAR), model=LIDAR_MODEL.get(lidar_model) if bit(HW_LIDAR) else None),
        buzzer=HwBuzzer(present=bit(HW_BUZZER)),
        # camera intentionally omitted here — docs/02 §6.2, state.py adds it
    )
    return HelloMsg(t=t_ms, seq=seq, fw=fw, reset_reason=_reset_reason_str(reset_reason), hw=hw)


def encode_hello(m: HelloMsg) -> bytes:
    hw = m.hw
    hw_present = 0
    if hw.imu.present:
        hw_present |= 1 << HW_IMU
    if hw.env.present:
        hw_present |= 1 << HW_ENV
    if hw.light.present:
        hw_present |= 1 << HW_LIGHT
    if hw.sonar.present:
        hw_present |= 1 << HW_SONAR
    if hw.battery.present:
        hw_present |= 1 << HW_BATTERY
    if hw.current.present:
        hw_present |= 1 << HW_CURRENT
    if hw.encoders.present:
        hw_present |= 1 << HW_ENCODERS
    if hw.lidar.present:
        hw_present |= 1 << HW_LIDAR
    if hw.buzzer.present:
        hw_present |= 1 << HW_BUZZER
    if hw.sonar.servo:
        hw_present |= 1 << HW_SERVO

    env_model = ENV_MODEL_INV.get(hw.env.model, 0) if hw.env.present else 0
    lidar_model = LIDAR_MODEL_INV.get(hw.lidar.model, 0) if hw.lidar.present else 0

    fw_bytes = m.fw.encode("ascii")[:20].ljust(20, b"\x00")
    header = _encode_header(MSG_HELLO, m.seq, m.t)
    return header + struct.pack(
        "<20sHBBBBBB",
        fw_bytes,
        hw_present,
        env_model,
        lidar_model,
        hw.battery.cells,
        _reset_reason_code(m.reset_reason),
        hw.encoders.cpr,
        0,
    )


# ---------------------------------------------------------------- TELEM ----


def decode_telem(b: bytes) -> TelemMsg:
    (magic, ver, type_, flags, seq, t_ms,
     temp_c, hum_pct, press_hpa, alt_m, lux,
     vbat_v, soc_pct, ibat_a, p_w,
     pwm_l, pwm_r, rpm_l, rpm_r,
     x_m, y_m, dist_m,
     roll_deg, pitch_deg, yaw_deg, ax_g, ay_g, az_g, gz_dps, imu_temp_c,
     sonar_angle_deg, sonar_dist_cm,
     mode, state_flags, last_cmd_age_ms, rssi_dbm,
     heap_b, uptime_s, loop_hz, chip_temp_c) = struct.unpack_from(TELEM_FMT, b, 0)

    n2n = _nan_to_none
    return TelemMsg(
        t=t_ms, seq=seq,
        env=TelemEnv(temp_c=n2n(temp_c), hum_pct=n2n(hum_pct), press_hpa=n2n(press_hpa), alt_m=n2n(alt_m)),
        light=TelemLight(lux=n2n(lux)),
        pwr=TelemPwr(vbat_v=n2n(vbat_v), soc_pct=n2n(soc_pct), ibat_a=n2n(ibat_a), p_w=n2n(p_w)),
        mot=TelemMot(pwm_l=pwm_l, pwm_r=pwm_r, rpm_l=n2n(rpm_l), rpm_r=n2n(rpm_r)),
        odom=TelemOdom(x_m=n2n(x_m), y_m=n2n(y_m), dist_m=n2n(dist_m)),
        imu=TelemImu(
            roll_deg=n2n(roll_deg), pitch_deg=n2n(pitch_deg), yaw_deg=n2n(yaw_deg),
            ax_g=n2n(ax_g), ay_g=n2n(ay_g), az_g=n2n(az_g), gz_dps=n2n(gz_dps),
            temp_c=n2n(imu_temp_c),
        ),
        sonar=TelemSonar(angle_deg=n2n(sonar_angle_deg), dist_cm=n2n(sonar_dist_cm)),
        state=TelemState(
            mode=MODE.get(mode, "idle"),
            estop=bool(state_flags & 0x01),
            wd_ok=bool(state_flags & 0x02),
            last_cmd_age_ms=last_cmd_age_ms,
        ),
        sys=TelemSys(
            rssi_dbm=rssi_dbm, heap_b=heap_b, uptime_s=uptime_s, loop_hz=loop_hz,
            chip_temp_c=n2n(chip_temp_c),
        ),
    )


def encode_telem(m: TelemMsg) -> bytes:
    n2n = _none_to_nan
    state_flags = (0x01 if m.state.estop else 0) | (0x02 if m.state.wd_ok else 0)
    header = _encode_header(MSG_TELEM, m.seq, m.t)
    return header + struct.pack(
        "<fffffffffhhfffffffffffffffBBHbIIHf",
        n2n(m.env.temp_c), n2n(m.env.hum_pct), n2n(m.env.press_hpa), n2n(m.env.alt_m),
        n2n(m.light.lux),
        n2n(m.pwr.vbat_v), n2n(m.pwr.soc_pct), n2n(m.pwr.ibat_a), n2n(m.pwr.p_w),
        m.mot.pwm_l, m.mot.pwm_r, n2n(m.mot.rpm_l), n2n(m.mot.rpm_r),
        n2n(m.odom.x_m), n2n(m.odom.y_m), n2n(m.odom.dist_m),
        n2n(m.imu.roll_deg), n2n(m.imu.pitch_deg), n2n(m.imu.yaw_deg),
        n2n(m.imu.ax_g), n2n(m.imu.ay_g), n2n(m.imu.az_g), n2n(m.imu.gz_dps), n2n(m.imu.temp_c),
        n2n(m.sonar.angle_deg), n2n(m.sonar.dist_cm),
        MODE_INV.get(m.state.mode, 0), state_flags, m.state.last_cmd_age_ms, m.sys.rssi_dbm,
        m.sys.heap_b, m.sys.uptime_s, m.sys.loop_hz, n2n(m.sys.chip_temp_c),
    )


# ----------------------------------------------------------------- SCAN ----

SCAN_MAX_PTS = 100


def decode_scan_fragment(b: bytes) -> tuple[ScanMsg, int, int]:
    """Decode a single ScanMsg fragment. Returns (partial ScanMsg, part, parts).

    pts on the returned ScanMsg cover only this fragment's points; the
    caller (scan reassembly, e.g. state.py) merges fragments by scan_id.
    """
    (magic, ver, type_, flags, seq, t_ms,
     src, scan_id, part, parts, yaw_deg, x_m, y_m,
     start_cdeg, step_cdeg, n) = struct.unpack_from(SCAN_HEADER_FMT, b, 0)
    dists = struct.unpack_from(f"<{n}H", b, SCAN_HEADER_SIZE)

    pts: list[list[Optional[float]]] = []
    for i, d in enumerate(dists):
        angle = (start_cdeg + i * step_cdeg) / 100.0
        pts.append([angle, _dist_to_json(d)])

    scan = ScanMsg(
        t=t_ms, seq=seq, src=SCAN_SRC.get(src, "sonar"), scan_id=scan_id,
        pose=ScanPose(x_m=_nan_to_none(x_m), y_m=_nan_to_none(y_m), yaw_deg=_nan_to_none(yaw_deg)),
        pts=pts,
    )
    return scan, part, parts


def encode_scan_fragment(
    *, seq: int, t_ms: int, src: str, scan_id: int, part: int, parts: int,
    yaw_deg: Optional[float], x_m: Optional[float], y_m: Optional[float],
    start_cdeg: int, step_cdeg: int, dist_cm: list[Optional[float]],
) -> bytes:
    n = len(dist_cm)
    if n > SCAN_MAX_PTS:
        raise WireError(f"scan fragment has {n} points, max {SCAN_MAX_PTS}")
    header = _encode_header(MSG_SCAN, seq, t_ms)
    body = struct.pack(
        "<BBBBfffHHB",
        SCAN_SRC_INV.get(src, 1), scan_id, part, parts,
        _none_to_nan(yaw_deg), _none_to_nan(x_m), _none_to_nan(y_m),
        start_cdeg, step_cdeg, n,
    )
    pts = struct.pack(f"<{n}H", *[_dist_to_wire(d) for d in dist_cm])
    return header + body + pts


# ---------------------------------------------------------------- EVENT ----


def decode_event(b: bytes) -> EventMsg:
    magic, ver, type_, flags, seq, t_ms, level, code, msg_raw = \
        struct.unpack_from(EVENT_FMT, b, 0)
    msg = msg_raw.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    return EventMsg(
        t=t_ms, seq=seq,
        level=EV_LEVEL.get(level, "info"),
        code=EV_CODE.get(code, "CMD_REJECTED"),
        msg=msg,
    )


def encode_event(m: EventMsg) -> bytes:
    header = _encode_header(MSG_EVENT, m.seq, m.t)
    msg_bytes = m.msg.encode("ascii", errors="replace")[:59].ljust(60, b"\x00")
    return header + struct.pack("<BB60s", EV_LEVEL_INV.get(m.level, 0), EV_CODE_INV.get(m.code, 9), msg_bytes)


# ------------------------------------------------------------------ ACK ----


def decode_ack(b: bytes) -> AckMsg:
    magic, ver, type_, flags, seq, t_ms, ack_seq, ok = struct.unpack_from(ACK_FMT, b, 0)
    return AckMsg(t=t_ms, seq=seq, ack_seq=ack_seq, ok=bool(ok))


def encode_ack(m: AckMsg) -> bytes:
    header = _encode_header(MSG_ACK, m.seq, m.t)
    return header + struct.pack("<HB", m.ack_seq, 1 if m.ok else 0)


# ------------------------------------------------------------------ CMD ----


def decode_cmd(b: bytes) -> CmdMsg:
    (magic, ver, type_, flags, seq, t_ms,
     drive_l, drive_r, mode, servo_mode, servo_angle_deg, cmd_flags,
     goto_x_m, goto_y_m) = struct.unpack_from(CMD_FMT, b, 0)

    goto_x = _nan_to_none(goto_x_m)
    goto_y = _nan_to_none(goto_y_m)
    goto = CmdGoto(x_m=goto_x, y_m=goto_y) if goto_x is not None and goto_y is not None else None

    return CmdMsg(
        t=t_ms, seq=seq,
        drive=CmdDrive(l=drive_l, r=drive_r),
        mode=MODE.get(mode, "idle"),
        servo=CmdServo(mode="fixed" if servo_mode == 1 else "sweep", angle_deg=servo_angle_deg),
        estop=bool(cmd_flags & 0x01),
        estop_reset=bool(cmd_flags & 0x02),
        buzzer=bool(cmd_flags & 0x04),
        request_hello=bool(cmd_flags & 0x08),
        goto=goto,
    )


def encode_cmd(m: CmdMsg) -> bytes:
    cmd_flags = (
        (0x01 if m.estop else 0)
        | (0x02 if m.estop_reset else 0)
        | (0x04 if m.buzzer else 0)
        | (0x08 if m.request_hello else 0)
    )
    goto_x = m.goto.x_m if m.goto else None
    goto_y = m.goto.y_m if m.goto else None
    header = _encode_header(MSG_CMD, m.seq, m.t)
    return header + struct.pack(
        "<ffBBBBff",
        m.drive.l, m.drive.r,
        MODE_INV.get(m.mode, 0),
        1 if m.servo.mode == "fixed" else 0,
        m.servo.angle_deg,
        cmd_flags,
        _none_to_nan(goto_x), _none_to_nan(goto_y),
    )


# ---------------------------------------------------- generic dispatch ----


def decode_message(b: bytes):
    """Decode any rover->GS wire message by its header type. Raises WireError."""
    if len(b) < HEADER_SIZE:
        raise WireError("message shorter than header")
    h = decode_header(b)
    if h.magic != PROTO_MAGIC:
        raise WireError(f"bad magic 0x{h.magic:02x}")
    if h.type == MSG_HELLO:
        return decode_hello(b)
    if h.type == MSG_TELEM:
        return decode_telem(b)
    if h.type == MSG_SCAN:
        return decode_scan_fragment(b)
    if h.type == MSG_EVENT:
        return decode_event(b)
    if h.type == MSG_ACK:
        return decode_ack(b)
    raise UnknownMsgType(f"unknown wire type 0x{h.type:02x}")


# ------------------------------------------------- BridgeStatus (GS-only) ----


@dataclass
class BridgeStatus:
    uptime_ms: int
    rx_count: int
    tx_ok: int
    tx_fail: int
    channel: int
    last_rssi: int
    rover_paired: bool


def decode_bridge_status(b: bytes) -> BridgeStatus:
    uptime_ms, rx_count, tx_ok, tx_fail, channel, last_rssi, rover_paired = \
        struct.unpack_from(BRIDGE_STATUS_FMT, b, 0)
    return BridgeStatus(uptime_ms, rx_count, tx_ok, tx_fail, channel, last_rssi, bool(rover_paired))


def encode_bridge_status(s: BridgeStatus) -> bytes:
    return struct.pack(
        BRIDGE_STATUS_FMT, s.uptime_ms, s.rx_count, s.tx_ok, s.tx_fail,
        s.channel, s.last_rssi, 1 if s.rover_paired else 0,
    )


# ------------------------------------------ JoystickState (GS-only) ----


@dataclass
class JoystickState:
    lx: int
    ly: int
    rx: int
    ry: int
    buttons: int
    seq: int


def decode_joystick(b: bytes) -> JoystickState:
    lx, ly, rx, ry, buttons, seq = struct.unpack_from(JOYSTICK_FMT, b, 0)
    return JoystickState(lx, ly, rx, ry, buttons, seq)


def encode_joystick(j: JoystickState) -> bytes:
    return struct.pack(JOYSTICK_FMT, j.lx, j.ly, j.rx, j.ry, j.buttons, j.seq)


# ---------------------------------------- Serial framing — docs/02 §4 ----

SK_RX_FROM_ROVER = 0x01
SK_TX_TO_ROVER = 0x02
SK_BRIDGE_STATUS = 0x03
SK_BRIDGE_LOG = 0x04
SK_JOYSTICK = 0x05


def _crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


@dataclass
class SerialFrame:
    kind: int
    rssi: int
    payload: bytes


def encode_serial_frame(kind: int, rssi: int, payload: bytes) -> bytes:
    body = bytes([kind, rssi & 0xFF]) + payload
    crc = _crc16_ccitt_false(body)
    body += struct.pack("<H", crc)
    return cobs.encode(body) + b"\x00"


def decode_serial_frame(frame: bytes) -> SerialFrame:
    """Decode one COBS frame (without the trailing 0x00). Raises WireError."""
    try:
        body = cobs.decode(frame)
    except cobs.DecodeError as exc:
        raise WireError(f"COBS decode failed: {exc}") from exc
    if len(body) < 4:
        raise WireError("frame too short")
    kind = body[0]
    rssi_byte = body[1]
    rssi = rssi_byte - 256 if rssi_byte >= 128 else rssi_byte
    payload, crc_bytes = body[2:-2], body[-2:]
    expected_crc = struct.unpack("<H", crc_bytes)[0]
    actual_crc = _crc16_ccitt_false(body[:-2])
    if actual_crc != expected_crc:
        raise WireError(f"CRC mismatch: got 0x{actual_crc:04x}, expected 0x{expected_crc:04x}")
    return SerialFrame(kind=kind, rssi=rssi, payload=payload)
