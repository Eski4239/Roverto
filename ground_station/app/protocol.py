"""Logical (JSON) protocol models — docs/02_TELEMETRY_PROTOCOL.md §2-3.

These are what everything above the link layer sees: state, logger, web UI,
simulator, tests. wire.py converts binary frames to/from these models.
Unknown JSON fields are ignored (pydantic default); hardware-dependent
fields are Optional and default to None ("NOT INSTALLED" / "no data").
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

Mode = Literal["idle", "manual", "assisted", "auto"]
EventLevel = Literal["info", "warn", "error"]
EventCode = Literal[
    "BOOT", "BATT_LOW", "BATT_CRIT", "TILT", "WD_STOP",
    "ESTOP", "SENSOR_LOST", "OBSTACLE", "CMD_REJECTED",
    "ROVER_RESTART",  # GS-synthesized only (state.py) — never on the wire
]
ScanSrc = Literal["sonar", "lidar"]
ServoMode = Literal["sweep", "fixed"]


class Model(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- hello ----

class HwImu(Model):
    present: bool
    model: Optional[str] = None


class HwEnv(Model):
    present: bool
    model: Optional[str] = None  # "bme280" | "bmp280" | "dht11" | None


class HwLight(Model):
    present: bool
    model: Optional[str] = None


class HwSonar(Model):
    present: bool
    model: Optional[str] = None
    servo: bool = False  # docs/02 §6.1: wire HW_SERVO bit, nested here


class HwBattery(Model):
    present: bool
    cells: int = 0


class HwCurrent(Model):
    present: bool
    model: Optional[str] = None


class HwEncoders(Model):
    present: bool
    cpr: int = 0


class HwLidar(Model):
    present: bool
    model: Optional[str] = None


class HwBuzzer(Model):
    present: bool


class HwCamera(Model):
    """Owned entirely by the ground station (HTTP probe) — docs/02 §6.2.

    wire.py never populates this; state.py adds it after probing camera_url.
    """
    present: bool
    url: Optional[str] = None


class Hw(Model):
    imu: HwImu
    env: HwEnv
    light: HwLight
    sonar: HwSonar
    battery: HwBattery
    current: HwCurrent
    encoders: HwEncoders
    lidar: HwLidar
    buzzer: HwBuzzer
    camera: Optional[HwCamera] = None


class HelloMsg(Model):
    v: int = 1
    type: Literal["hello"] = "hello"
    t: int
    seq: int
    fw: str
    reset_reason: str
    hw: Hw


# ---------------------------------------------------------------- telem ----

class TelemEnv(Model):
    temp_c: Optional[float] = None
    hum_pct: Optional[float] = None
    press_hpa: Optional[float] = None
    alt_m: Optional[float] = None


class TelemLight(Model):
    lux: Optional[float] = None


class TelemPwr(Model):
    vbat_v: Optional[float] = None
    soc_pct: Optional[float] = None
    ibat_a: Optional[float] = None
    p_w: Optional[float] = None


class TelemMot(Model):
    pwm_l: int
    pwm_r: int
    rpm_l: Optional[float] = None
    rpm_r: Optional[float] = None


class TelemOdom(Model):
    x_m: Optional[float] = None
    y_m: Optional[float] = None
    dist_m: Optional[float] = None


class TelemImu(Model):
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    yaw_deg: Optional[float] = None
    ax_g: Optional[float] = None
    ay_g: Optional[float] = None
    az_g: Optional[float] = None
    gz_dps: Optional[float] = None
    temp_c: Optional[float] = None


class TelemSonar(Model):
    angle_deg: Optional[float] = None
    dist_cm: Optional[float] = None


class TelemState(Model):
    mode: Mode
    estop: bool
    wd_ok: bool
    last_cmd_age_ms: int


class TelemSys(Model):
    rssi_dbm: int
    heap_b: int
    uptime_s: int
    loop_hz: int
    chip_temp_c: Optional[float] = None


class TelemMsg(Model):
    v: int = 1
    type: Literal["telem"] = "telem"
    t: int
    seq: int
    env: TelemEnv
    light: TelemLight
    pwr: TelemPwr
    mot: TelemMot
    odom: TelemOdom
    imu: TelemImu
    sonar: TelemSonar
    state: TelemState
    sys: TelemSys


# ----------------------------------------------------------------- scan ----

class ScanPose(Model):
    x_m: Optional[float] = None
    y_m: Optional[float] = None
    yaw_deg: Optional[float] = None


class ScanMsg(Model):
    v: int = 1
    type: Literal["scan"] = "scan"
    t: int
    seq: int
    src: ScanSrc
    scan_id: int
    pose: ScanPose
    pts: list[list[Optional[float]]]  # [[angle_deg, dist_cm], ...]


# ---------------------------------------------------------------- event ----

class EventMsg(Model):
    v: int = 1
    type: Literal["event"] = "event"
    t: int
    seq: int
    level: EventLevel
    code: EventCode
    msg: str


# ------------------------------------------------------------------ ack ----

class AckMsg(Model):
    v: int = 1
    type: Literal["ack"] = "ack"
    t: int
    seq: int
    ack_seq: int
    ok: bool


# ------------------------------------------------------------------ cmd ----

class CmdDrive(Model):
    l: float = 0.0
    r: float = 0.0


class CmdServo(Model):
    mode: ServoMode = "sweep"
    angle_deg: int = 90


class CmdGoto(Model):
    x_m: float
    y_m: float


class CmdMsg(Model):
    v: int = 1
    type: Literal["cmd"] = "cmd"
    t: int
    seq: int
    drive: CmdDrive
    mode: Mode
    servo: CmdServo
    estop: bool = False
    estop_reset: bool = False
    buzzer: bool = False
    request_hello: bool = False
    goto: Optional[CmdGoto] = None


# --------------------------------------------------- ground-station-only ----

LinkState = Literal["OK", "STALE", "LOST", "NO_BRIDGE"]


class LinkBlock(Model):
    """Never on the radio — docs/02 §3.2. Added by state.py for the UI."""
    state: LinkState
    rx_hz: float
    loss_pct: Optional[float] = None  # null/"--" in the UI until enough samples (LOSS_MIN_SAMPLES)
    rtt_ms: Optional[float] = None
    rssi_bridge_dbm: Optional[int] = None
    rssi_rover_dbm: Optional[int] = None
    bridge_tx_fail: int = 0
    serial_port: Optional[str] = None
