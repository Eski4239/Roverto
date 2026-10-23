"""TCP server on 127.0.0.1:8765 emitting the exact serial byte stream the
ground_bridge would (docs/02 §4): SK_RX_FROM_ROVER frames with a fake RSSI,
plus SK_BRIDGE_STATUS at 1 Hz; accepts SK_TX_TO_ROVER frames carrying
CmdMsg. Implemented in Phase 2 (docs/06).

Rover state lives in one RoverState object created once in main() and kept
alive across client disconnect/reconnect (a laptop replugging the USB
bridge does not reset the rover). Only one client is accepted at a time,
like a real serial port; a second connection is rejected. The background
driver loop runs independently of any connection, so the 500 ms watchdog
and battery/IMU drift keep advancing with nobody attached.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

if __name__ == "__main__" and __package__ is None:
    # allow `python simulator/fake_rover.py` (CLAUDE.md run instructions) in
    # addition to `python -m simulator.fake_rover`, by putting the repo root
    # on sys.path so `ground_station` resolves as a package either way.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ground_station.app import wire
from ground_station.app.state import load_config as _load_gs_config
from ground_station.app.protocol import (
    CmdMsg,
    EventMsg,
    HelloMsg,
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

log = logging.getLogger("fake_rover")

WATCHDOG_MS = 500
HELLO_PERIOD_S = 5.0
SONAR_SCAN_PERIOD_S = 2.0
LIDAR_SCAN_PERIOD_S = 0.1
BRIDGE_STATUS_PERIOD_S = 1.0
TELEM_PERIOD_S = 0.1
BATT_CRIT_V = 9.9
BATT_LOW_V = 10.5
BATT_HYSTERESIS_V = 0.2
BATT_PERSIST_S = 3.0
TILT_LIMIT_DEG = 35.0
TILT_RESUME_DEG = 30.0
OBSTACLE_DIST_CM = 20.0
RATE_LIMITED_EVENT_PERIOD_S = 1.0

# P3: a simple 1D world so assisted mode (forward blocked < 20cm) is
# actually testable -- the rover's position integrates applied PWM, and the
# front sonar reports distance to a wall FRONT_WALL_START_CM ahead at boot.
# Reversing (negative applied PWM) increases the distance again. Only the
# front (angle=0) distance is dynamic; the other FAKE_ROOM_CM angles stay a
# static room shape, since nothing asked for a full 2D map.
FRONT_WALL_START_CM = 150.0
ROVER_MAX_SPEED_CM_S = 40.0  # at full PWM (±pwm_max)


def _default_pwm_max() -> int:
    try:
        cfg = _load_gs_config(Path(__file__).resolve().parent.parent / "ground_station" / "app" / "config.toml")
        return int(cfg.get("motors", {}).get("pwm_max", 120))
    except (OSError, KeyError, ValueError):
        return 120

# Fake rectangular room, sonar frame: 0 deg = front, CCW+. angle_deg -> wall dist_cm.
FAKE_ROOM_CM = {0: 180, 30: 160, 60: 120, 90: 90, 120: 120, 150: 160, 180: 180}


@dataclass
class RoverState:
    """All mutable rover state. Pure logic, no I/O — survives client churn."""

    bme280: bool = True
    bmp280: bool = False
    dht11: bool = False
    encoders: bool = False
    ina219: bool = False
    lidar: bool = False

    start_mono: float = field(default_factory=time.monotonic)
    seq: int = 0
    scan_id: int = 0

    vbat_v: float = 12.6
    chip_temp_c: float = 35.0
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    # P3: front-wall distance, integrated from applied PWM each tick.
    front_wall_cm: float = FRONT_WALL_START_CM

    mode: str = "idle"
    drive_l: float = 0.0
    drive_r: float = 0.0
    servo_mode: str = "sweep"
    servo_angle_deg: int = 90
    sweep_angle_deg: float = 0.0
    sweep_dir: int = 1

    estop_latched: bool = False
    wd_ok: bool = False  # becomes True only once a CmdMsg is actually accepted
    last_cmd_mono: Optional[float] = None
    last_accepted_mode: Optional[str] = None
    last_accepted_flags: Optional[int] = None
    last_accepted_drive_zero: bool = True

    hello_requested: bool = True  # send HELLO immediately on boot
    wd_stop_sent: bool = False
    pending_events: list[EventMsg] = field(default_factory=list)

    # GS-1: edge-triggered events, emitted once per state change, not per tick.
    tilt_active: bool = False
    batt_low_active: bool = False
    batt_crit_active: bool = False
    batt_low_since: Optional[float] = None
    batt_crit_since: Optional[float] = None
    last_cmd_rejected_event_mono: Optional[float] = None
    last_obstacle_event_mono: Optional[float] = None
    obstacle_blocking: bool = False

    pwm_max: int = 120
    reboot_after_s: Optional[float] = None
    rebooted: bool = False

    silent_after_s: Optional[float] = None
    silent_for_s: Optional[float] = None
    silent_started_mono: Optional[float] = None
    silent_done: bool = False

    # Phase 6: --joystick-demo scripts a pure driving pattern (centre ->
    # forward -> turn -> reverse -> centre, looping, never touching the
    # button) so the backend's calibration/deadband/fault logic is
    # testable without real hardware. --joystick-demo-estop is a separate,
    # deliberate one-shot button press (10s after start, never again) for
    # testing E-STOP in isolation -- confirmed live that combining both in
    # one looping pattern made a correctly-working E-STOP look broken,
    # since the button fired every loop. --joystick-fault reuses the same
    # clock but injects a jump every frame once armed, to exercise
    # joystick.py's fault detection.
    joystick_demo: bool = False
    joystick_demo_estop: bool = False
    joystick_demo_estop_fired: bool = False
    joystick_fault: bool = False
    joystick_start_mono: Optional[float] = None
    joystick_seq: int = 0
    joystick_silent_after_s: Optional[float] = None
    joystick_silent_for_s: Optional[float] = None
    joystick_silent_started_mono: Optional[float] = None
    joystick_silent_done: bool = False

    # tests only: counts frames the serial parser had to drop (bad CRC,
    # truncated, or otherwise undecodable) vs. CmdMsgs actually applied --
    # used to detect two writers' frames interleaving on the wire (F13/F20).
    malformed_frame_count: int = 0
    accepted_cmd_count: int = 0
    last_cmd_buzzer: Optional[bool] = None

    # watchdog (docs/02 §5.1): an event-loop timer armed/re-armed on every
    # accepted CmdMsg, not a poll inside tick() -- rover_main's own watchdog
    # checks at a much higher rate than the 10Hz TELEM tick this simulator
    # otherwise runs at, so polling it from tick() could let WD_STOP fire
    # up to one whole tick (100ms) later than a real rover would.
    _watchdog_handle: Optional[object] = field(default=None, repr=False)

    def _trip_watchdog(self) -> None:
        self.wd_ok = False
        self.drive_l = 0.0
        self.drive_r = 0.0
        if not self.wd_stop_sent:
            self.wd_stop_sent = True
            self._emit_event("warn", "WD_STOP", "no cmd for 500 ms")

    def _arm_watchdog(self, loop: "asyncio.AbstractEventLoop", *, cmd_received: bool) -> None:
        """Called both when a CmdMsg is actually accepted (cmd_received=True
        -- the watchdog is satisfied, wd_ok goes true) and at boot/reboot
        before any CmdMsg has arrived yet (cmd_received=False -- just starts
        the same WATCHDOG_MS countdown a real power-on would, without
        prematurely claiming the link is healthy)."""
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
        if cmd_received:
            self.wd_ok = True
            self.wd_stop_sent = False
        self._watchdog_handle = loop.call_later(WATCHDOG_MS / 1000.0, self._trip_watchdog)

    def now_ms(self) -> int:
        return int((time.monotonic() - self.start_mono) * 1000)

    def next_seq(self) -> int:
        self.seq = (self.seq + 1) % 65536
        return self.seq

    # ---------------------------------------------------------- lifecycle ----

    def _env_model(self) -> Optional[str]:
        if self.bme280:
            return "bme280"
        if self.bmp280:
            return "bmp280"
        if self.dht11:
            return "dht11"
        return None

    def _maybe_reboot(self, elapsed: float) -> None:
        """--reboot-after N: simulate a one-shot rover reboot at uptime N s
        (GS-2 testing aid) -- seq/t_ms restart from 0, a fresh HELLO is sent,
        watchdog/estop/tilt/battery latches clear as a real power-cycle would."""
        if self.reboot_after_s is None or self.rebooted or elapsed < self.reboot_after_s:
            return
        self.rebooted = True
        self.start_mono = time.monotonic()
        self.seq = 0
        self.hello_requested = True
        self.estop_latched = False
        self.last_cmd_mono = None
        self._arm_watchdog(asyncio.get_running_loop(), cmd_received=False)
        self.last_accepted_mode = None
        self.last_accepted_flags = None
        self.last_accepted_drive_zero = True
        self.tilt_active = False
        self.batt_low_active = False
        self.batt_crit_active = False
        self.batt_low_since = None
        self.batt_crit_since = None
        self.roll_deg = 0.0
        self.pitch_deg = 0.0
        self.drive_l = 0.0
        self.drive_r = 0.0
        # A real power-cycle can't have anything queued with a pre-reboot
        # seq: drop pending events built before the reboot, and any scan
        # sweep in progress (its fragments share the old scan's seq).
        self.pending_events.clear()
        self.scan_id = 0

    def is_silent(self) -> bool:
        """--rover-silent-after N --rover-silent-for M: the rover stops
        sending HELLO/TELEM/SCAN/EVENT/ACK for M s starting at uptime N s,
        then resumes with t_ms/seq untouched (no reboot). BRIDGE_STATUS is
        not gated by this -- it's emitted by the driver loop unconditionally,
        matching a real bridge that keeps reporting link status even when
        the rover itself has gone quiet."""
        if self.silent_after_s is None or self.silent_for_s is None or self.silent_done:
            return False
        elapsed = time.monotonic() - self.start_mono
        if self.silent_started_mono is None:
            if elapsed < self.silent_after_s:
                return False
            self.silent_started_mono = time.monotonic()
        if time.monotonic() - self.silent_started_mono >= self.silent_for_s:
            self.silent_done = True
            return False
        return True

    def _joystick_is_silent(self) -> bool:
        """--joystick-silent-after N --joystick-silent-for M: SK_JOYSTICK
        stops for M s starting at uptime N s (mirrors is_silent()'s idiom),
        for testing the GS's 200 ms joystick-lost timeout without affecting
        HELLO/TELEM/SCAN/EVENT/ACK."""
        if (
            self.joystick_silent_after_s is None
            or self.joystick_silent_for_s is None
            or self.joystick_silent_done
        ):
            return False
        elapsed = time.monotonic() - self.start_mono
        if self.joystick_silent_started_mono is None:
            if elapsed < self.joystick_silent_after_s:
                return False
            self.joystick_silent_started_mono = time.monotonic()
        if time.monotonic() - self.joystick_silent_started_mono >= self.joystick_silent_for_s:
            self.joystick_silent_done = True
            return False
        return True

    def build_joystick_frame(self) -> Optional[bytes]:
        """--joystick-demo: centre -> forward -> turn -> reverse -> centre,
        looping forever, NEVER touching the button. Confirmed live
        (2026-10-22): the previous combined pattern pressed the stick
        button every loop, which E-STOPs the rover on a timer that looks
        like a bug but is actually the (correct) button logic reacting to
        a demo script that presses it repeatedly -- not an E-STOP defect.
        Splitting the button out of the driving demo removes that
        confusion; --joystick-demo-estop (self.joystick_demo_estop) is the
        separate, deliberate "press the button exactly once" scenario for
        testing E-STOP itself. Raw ADC values around 2048 (docs/02 §4
        JoystickState). --joystick-fault adds a wild jump on top, on every
        frame, independent of either demo pattern being enabled.

        The centred window (cycle < 1.0) recurs every loop so the
        backend's 0.5s centre-calibration gate always has a fresh
        opportunity to open, however far into a cycle the backend happened
        to connect/switch-to-Joystick."""
        if not self.joystick_demo and not self.joystick_demo_estop and not self.joystick_fault:
            return None
        if self._joystick_is_silent():
            return None
        if self.joystick_start_mono is None:
            self.joystick_start_mono = time.monotonic()
        elapsed = time.monotonic() - self.joystick_start_mono

        CENTRE = 2048
        FULL = 2048  # deflection to reach the raw extremes (0 / 4095)
        lx = ly = rx = ry = CENTRE
        buttons = 0

        if self.joystick_demo:
            cycle = elapsed % 6.0  # loops forever: centre/fwd/turn/reverse/centre
            if cycle < 1.0:
                pass  # centre 1s
            elif cycle < 2.5:
                ly = ry = CENTRE - FULL  # both sticks forward (y: push = decrease)
            elif cycle < 4.0:
                ly = CENTRE - FULL
                ry = CENTRE + FULL  # turn: left forward, right back
            elif cycle < 5.0:
                ly = ry = CENTRE + FULL  # reverse: both sticks back
            else:
                pass  # centre 1s before looping

        if self.joystick_demo_estop and not self.joystick_demo_estop_fired:
            # Held for a short window (not a single-frame pulse) so a
            # dropped frame can't make the press invisible to the backend's
            # edge detector; fired=True latches it off for good afterwards
            # -- "once, 10s after start, never again," confirmed live.
            if 10.0 <= elapsed < 10.3:
                buttons = 0b01
            elif elapsed >= 10.3:
                self.joystick_demo_estop_fired = True

        if self.joystick_fault:
            jump = FULL if self.joystick_seq % 2 == 0 else -FULL
            lx = max(0, min(4095, lx + jump))
            ry = max(0, min(4095, ry - jump))

        self.joystick_seq = (self.joystick_seq + 1) % 256
        return wire.encode_joystick(wire.JoystickState(
            lx=max(0, min(4095, lx)), ly=max(0, min(4095, ly)),
            rx=max(0, min(4095, rx)), ry=max(0, min(4095, ry)),
            buttons=buttons, seq=self.joystick_seq,
        ))

    def tick(self) -> None:
        """Advance drift/decay and enforce safety rules. Call at ~10 Hz."""
        if self._watchdog_handle is None:
            # boot: no CmdMsg accepted yet, arm the same WATCHDOG_MS deadline
            # a real power-on would -- fires once as the expected startup
            # transient (test_no_wd_stop_with_zero_ui_clients) unless a
            # CmdMsg arrives first and re-arms it via apply_cmd().
            self._arm_watchdog(asyncio.get_running_loop(), cmd_received=False)
        now = time.monotonic()
        elapsed = now - self.start_mono
        self._maybe_reboot(elapsed)
        now = time.monotonic()
        elapsed = now - self.start_mono
        # battery: 12.6 -> 9.8 V over a ~10 minute demo run, then holds
        drain_frac = min(elapsed / 600.0, 1.0)
        self.vbat_v = 12.6 - drain_frac * (12.6 - 9.8)
        self.chip_temp_c = 35.0 + 10.0 * drain_frac + random.uniform(-0.3, 0.3)
        self.roll_deg += random.uniform(-0.3, 0.3)
        self.pitch_deg += random.uniform(-0.3, 0.3)
        self.roll_deg = max(-45.0, min(45.0, self.roll_deg * 0.98))
        self.pitch_deg = max(-45.0, min(45.0, self.pitch_deg * 0.98))
        self.yaw_deg = (self.yaw_deg + random.uniform(-0.5, 0.5)) % 360.0

        # P3: integrate the rover's forward position from applied drive --
        # tank-drive average of both wheels, scaled to ROVER_MAX_SPEED_CM_S
        # at full deflection. Driving forward shrinks the front wall
        # distance; reversing (negative average) grows it back. Clamped at
        # 0 (can't drive through the wall) with no upper bound (there's
        # nothing behind the rover in this simple 1D model).
        forward_frac = (self.drive_l + self.drive_r) / 2.0
        self.front_wall_cm = max(
            0.0, self.front_wall_cm - forward_frac * ROVER_MAX_SPEED_CM_S * TELEM_PERIOD_S,
        )

        # watchdog is now an event-loop timer (_arm_watchdog/_trip_watchdog),
        # armed on every accepted CmdMsg -- see apply_cmd() -- not polled
        # here, so WD_STOP fires at exactly WATCHDOG_MS, not up to one
        # TELEM_PERIOD_S tick late.

        # estop latch: motors forced 0 regardless of drive
        if self.estop_latched:
            self.drive_l = 0.0
            self.drive_r = 0.0

        # tilt: docs/02 §5.3, Q-3 -- latch until both axes are back under the
        # resume threshold AND a zero-drive cmd has been accepted (GS-1: emit
        # only once per transition, not every tick while tilted).
        is_tilted = abs(self.roll_deg) > TILT_LIMIT_DEG or abs(self.pitch_deg) > TILT_LIMIT_DEG
        if is_tilted:
            self.drive_l = 0.0
            self.drive_r = 0.0
            if not self.tilt_active:
                self.tilt_active = True
                self._emit_event("warn", "TILT", f"roll={self.roll_deg:.1f} pitch={self.pitch_deg:.1f}")
        elif self.tilt_active:
            self.drive_l = 0.0
            self.drive_r = 0.0
            resumed = (
                abs(self.roll_deg) < TILT_RESUME_DEG
                and abs(self.pitch_deg) < TILT_RESUME_DEG
                and self.last_accepted_drive_zero
            )
            if resumed:
                self.tilt_active = False

        # battery: docs/02 §5.4, Q-4 -- 3 s persistence before the event/limit
        # fires, 0.2 V hysteresis before it clears; emit once per transition.
        if self.vbat_v < BATT_CRIT_V:
            if self.batt_crit_since is None:
                self.batt_crit_since = now
            if not self.batt_crit_active and now - self.batt_crit_since >= BATT_PERSIST_S:
                self.batt_crit_active = True
                self._emit_event("error", "BATT_CRIT", f"vbat {self.vbat_v:.1f} V")
        elif self.vbat_v >= BATT_CRIT_V + BATT_HYSTERESIS_V:
            self.batt_crit_since = None
            self.batt_crit_active = False

        if self.batt_crit_active:
            self.drive_l = max(-0.3, min(0.3, self.drive_l))
            self.drive_r = max(-0.3, min(0.3, self.drive_r))

        if self.vbat_v < BATT_LOW_V:
            if self.batt_low_since is None:
                self.batt_low_since = now
            if not self.batt_low_active and now - self.batt_low_since >= BATT_PERSIST_S:
                self.batt_low_active = True
                self._emit_event("warn", "BATT_LOW", f"vbat {self.vbat_v:.1f} V")
        elif self.vbat_v >= BATT_LOW_V + BATT_HYSTERESIS_V:
            self.batt_low_since = None
            self.batt_low_active = False

        # sonar servo sweep (ignored while in fixed mode)
        if self.servo_mode == "sweep":
            self.sweep_angle_deg += self.sweep_dir * 6.0
            if self.sweep_angle_deg >= 180.0:
                self.sweep_angle_deg = 180.0
                self.sweep_dir = -1
            elif self.sweep_angle_deg <= 0.0:
                self.sweep_angle_deg = 0.0
                self.sweep_dir = 1

    def _emit_event(self, level: str, code: str, msg: str) -> None:
        self.pending_events.append(
            EventMsg(t=self.now_ms(), seq=self.next_seq(), level=level, code=code, msg=msg)
        )

    def drain_pending_events(self) -> list[EventMsg]:
        events, self.pending_events = self.pending_events, []
        return events

    # -------------------------------------------------------------- cmd ----

    def apply_cmd(self, cmd: CmdMsg) -> Optional[wire.AckMsg]:
        """docs/02 §6.8 ack rules; §5.2 estop latch; §5 4b modes (Q-5)."""
        self.last_cmd_mono = time.monotonic()
        self.accepted_cmd_count += 1
        # P6: print on change (not every accepted CmdMsg, which would spam
        # the console at 10Hz) so the operator gets visible feedback that
        # the buzzer flag actually reached the simulator -- there was
        # previously no sign at all that a BUZZER press had any effect.
        if cmd.buzzer != self.last_cmd_buzzer:
            log.info("BUZZER %s", "ON" if cmd.buzzer else "OFF")
        self.last_cmd_buzzer = cmd.buzzer  # tests only (F1)
        self._arm_watchdog(asyncio.get_running_loop(), cmd_received=True)

        cmd_flags = (
            (0x01 if cmd.estop else 0)
            | (0x02 if cmd.estop_reset else 0)
            | (0x04 if cmd.buzzer else 0)
            | (0x08 if cmd.request_hello else 0)
        )

        if cmd.estop:
            self.estop_latched = True
        if cmd.estop_reset:
            self.estop_latched = False

        if cmd.request_hello:
            self.hello_requested = True

        # Q-5: auto is rejected outright until navigation exists -- the mode,
        # drive and servo changes in this cmd are all ignored.
        if cmd.mode == "auto":
            self.last_cmd_mono = time.monotonic()  # watchdog still sees a live link
            now = time.monotonic()
            if (
                self.last_cmd_rejected_event_mono is None
                or now - self.last_cmd_rejected_event_mono >= RATE_LIMITED_EVENT_PERIOD_S
            ):
                self.last_cmd_rejected_event_mono = now
                self._emit_event("warn", "CMD_REJECTED", "auto mode not implemented")
            ack = wire.AckMsg(t=self.now_ms(), seq=self.next_seq(), ack_seq=cmd.seq, ok=False)
            return ack

        drive_l = max(-1.0, min(1.0, cmd.drive.l))
        drive_r = max(-1.0, min(1.0, cmd.drive.r))

        if cmd.mode == "assisted":
            front_dist = self._sonar_dist_cm(0.0)
            blocking = front_dist < OBSTACLE_DIST_CM and drive_l > 0 and drive_r > 0
            if blocking:
                drive_l = min(0.0, drive_l)
                drive_r = min(0.0, drive_r)
                now = time.monotonic()
                if (
                    self.last_obstacle_event_mono is None
                    or now - self.last_obstacle_event_mono >= RATE_LIMITED_EVENT_PERIOD_S
                ):
                    self.last_obstacle_event_mono = now
                    self._emit_event("warn", "OBSTACLE", f"front {front_dist:.0f} cm, forward blocked")
                self.obstacle_blocking = True
            else:
                self.obstacle_blocking = False

        if not self.estop_latched:
            self.drive_l = drive_l
            self.drive_r = drive_r

        self.mode = cmd.mode
        self.servo_mode = cmd.servo.mode
        self.servo_angle_deg = cmd.servo.angle_deg
        self.last_accepted_drive_zero = drive_l == 0.0 and drive_r == 0.0

        ack_rule_a = (
            self.last_accepted_mode is not None
            and (cmd.mode != self.last_accepted_mode or cmd_flags != self.last_accepted_flags)
        )
        ack_rule_b = cmd.seq % 10 == 0
        self.last_accepted_mode = cmd.mode
        self.last_accepted_flags = cmd_flags

        if ack_rule_a or ack_rule_b:
            ack = wire.AckMsg(t=self.now_ms(), seq=self.next_seq(), ack_seq=cmd.seq, ok=True)
            return ack
        return None

    # ------------------------------------------------------------ build ----

    def build_hello(self) -> HelloMsg:
        env_model = self._env_model()
        hw = Hw(
            imu=HwImu(present=True),
            env=HwEnv(present=env_model is not None, model=env_model),
            light=HwLight(present=True),
            sonar=HwSonar(present=True, servo=True),
            battery=HwBattery(present=True, cells=3),
            current=HwCurrent(present=self.ina219),
            encoders=HwEncoders(present=self.encoders, cpr=20 if self.encoders else 0),
            lidar=HwLidar(present=self.lidar, model="ld06" if self.lidar else None),
            buzzer=HwBuzzer(present=True),
        )
        return HelloMsg(
            t=self.now_ms(), seq=self.next_seq(),
            fw="fake_rover 0.1.0", reset_reason="POWERON", hw=hw,
        )

    def _sonar_dist_cm(self, angle_deg: float) -> float:
        # P3: only the front reading tracks the rover's integrated position
        # (self.front_wall_cm, updated in tick()) -- the rest of the sweep
        # still comes from the static FAKE_ROOM_CM shape, since nothing
        # asked for a full 2D map, just a testable front obstacle.
        if angle_deg == 0.0:
            return max(2.0, self.front_wall_cm + random.uniform(-3.0, 3.0))
        angles = sorted(FAKE_ROOM_CM)
        lo = max(a for a in angles if a <= angle_deg)
        hi = min((a for a in angles if a >= angle_deg), default=lo)
        if hi == lo:
            base = FAKE_ROOM_CM[lo]
        else:
            frac = (angle_deg - lo) / (hi - lo)
            base = FAKE_ROOM_CM[lo] + frac * (FAKE_ROOM_CM[hi] - FAKE_ROOM_CM[lo])
        return max(2.0, base + random.uniform(-3.0, 3.0))

    def build_telem(self) -> TelemMsg:
        env_model = self._env_model()
        has_hum = env_model == "bme280"
        has_press = env_model in ("bme280", "bmp280")
        # P4 fix: while in fixed mode the servo isn't sweeping (tick()
        # already stops advancing sweep_angle_deg -- see the comment there),
        # but TELEM must report the commanded servo_angle_deg, not whatever
        # arbitrary angle the sweep happened to freeze at when the mode
        # switched. Reporting the frozen sweep angle (e.g. 78 deg instead of
        # the requested 90) is what pushed the radar widget's drawn beam
        # outside its panel -- see sonarwidget.js's angle-to-xy fix too.
        reported_angle_deg = (
            float(self.servo_angle_deg) if self.servo_mode == "fixed" else self.sweep_angle_deg
        )
        sonar_dist = self._sonar_dist_cm(reported_angle_deg)
        pwm_l = int(self.drive_l * self.pwm_max)
        pwm_r = int(self.drive_r * self.pwm_max)
        return TelemMsg(
            t=self.now_ms(), seq=self.next_seq(),
            env=TelemEnv(
                temp_c=22.0 + random.uniform(-0.3, 0.3) if env_model else None,
                hum_pct=41.0 + random.uniform(-1.0, 1.0) if has_hum else None,
                press_hpa=1012.0 + random.uniform(-0.5, 0.5) if has_press else None,
                alt_m=0.4 if has_press else None,
            ),
            light=TelemLight(lux=340.0 + random.uniform(-10.0, 10.0)),
            pwr=TelemPwr(
                vbat_v=self.vbat_v,
                soc_pct=max(0.0, min(100.0, (self.vbat_v - 9.0) / (12.6 - 9.0) * 100.0)),
                ibat_a=1.2 + random.uniform(-0.1, 0.1) if self.ina219 else None,
                p_w=self.vbat_v * 1.2 if self.ina219 else None,
            ),
            mot=TelemMot(
                pwm_l=pwm_l, pwm_r=pwm_r,
                rpm_l=abs(pwm_l) * 0.5 if self.encoders else None,
                rpm_r=abs(pwm_r) * 0.5 if self.encoders else None,
            ),
            odom=TelemOdom(
                x_m=0.0 if self.encoders else None,
                y_m=0.0 if self.encoders else None,
                dist_m=0.0 if self.encoders else None,
            ),
            imu=TelemImu(
                roll_deg=self.roll_deg, pitch_deg=self.pitch_deg, yaw_deg=self.yaw_deg,
                ax_g=random.uniform(-0.02, 0.02), ay_g=random.uniform(-0.02, 0.02), az_g=1.0,
                gz_dps=random.uniform(-0.5, 0.5), temp_c=self.chip_temp_c - 3.0,
            ),
            sonar=TelemSonar(angle_deg=reported_angle_deg, dist_cm=sonar_dist),
            state=TelemState(
                mode=self.mode, estop=self.estop_latched, wd_ok=self.wd_ok,
                last_cmd_age_ms=(
                    0 if self.last_cmd_mono is None
                    else min(65535, int((time.monotonic() - self.last_cmd_mono) * 1000))
                ),
            ),
            sys=TelemSys(
                rssi_dbm=-60, heap_b=180000, uptime_s=int(time.monotonic() - self.start_mono),
                loop_hz=98, chip_temp_c=self.chip_temp_c,
            ),
        )

    def build_scan_fragments(self) -> list[bytes]:
        """Pre-encoded ScanMsg wire fragments for one complete sweep."""
        self.scan_id = (self.scan_id + 1) % 256
        t_ms = self.now_ms()
        if self.lidar:
            n_pts = 360
            step_cdeg = 100  # 1 degree steps
            dists = [self._sonar_dist_cm(i % 180) for i in range(n_pts)]
            frags = []
            per_frag = 100
            parts = math.ceil(n_pts / per_frag)
            for part in range(parts):
                chunk = dists[part * per_frag:(part + 1) * per_frag]
                frags.append(wire.encode_scan_fragment(
                    seq=self.next_seq(), t_ms=t_ms, src="lidar", scan_id=self.scan_id,
                    part=part, parts=parts, yaw_deg=self.yaw_deg, x_m=None, y_m=None,
                    start_cdeg=part * per_frag * step_cdeg, step_cdeg=step_cdeg,
                    dist_cm=chunk,
                ))
            return frags
        angles = list(range(0, 181, 10))
        dists = [self._sonar_dist_cm(a) for a in angles]
        frag = wire.encode_scan_fragment(
            seq=self.next_seq(), t_ms=t_ms, src="sonar", scan_id=self.scan_id,
            part=0, parts=1, yaw_deg=self.yaw_deg, x_m=None, y_m=None,
            start_cdeg=0, step_cdeg=1000, dist_cm=dists,
        )
        return [frag]


class _ClientRegistry:
    """Tracks the single allowed client writer. Not thread-safe by design —
    asyncio is single-threaded, so a plain attribute is sufficient."""

    def __init__(self) -> None:
        self.writer: Optional[asyncio.StreamWriter] = None

    def get(self) -> Optional[asyncio.StreamWriter]:
        return self.writer


def _send_frame(registry: _ClientRegistry, kind: int, rssi: int, payload: bytes, lossy: int) -> None:
    writer = registry.get()
    if writer is None:
        return
    if lossy and random.randint(1, 100) <= lossy:
        return
    try:
        writer.write(wire.encode_serial_frame(kind, rssi, payload))
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.debug("send failed, client likely gone: %s", exc)


async def _rx_loop(
    reader: asyncio.StreamReader, state: RoverState,
    registry: _ClientRegistry, args: argparse.Namespace,
) -> None:
    """Applies each incoming CmdMsg and, if it earns an ack (docs/02 §6.8),
    writes it to the socket immediately -- real rover_main replies within
    one ~10ms loop iteration, not on this simulator's own 100ms telemetry
    tick, so RTT measurement shouldn't be stretched by that unrelated tick."""
    while True:
        try:
            raw = await reader.readuntil(b"\x00")
        except asyncio.IncompleteReadError:
            return
        frame = raw[:-1]
        if not frame:
            continue
        try:
            sf = wire.decode_serial_frame(frame)
            if sf.kind != wire.SK_TX_TO_ROVER:
                continue
            cmd = wire.decode_cmd(sf.payload)
        except Exception as exc:  # noqa: BLE001 — never crash on malformed input
            log.debug("dropping malformed frame: %s", exc)
            state.malformed_frame_count += 1
            continue
        ack = state.apply_cmd(cmd)
        if ack is not None and not state.is_silent():
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, wire.encode_ack(ack), args.lossy)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: RoverState,
    registry: _ClientRegistry,
    args: argparse.Namespace,
) -> None:
    peer = writer.get_extra_info("peername")
    if registry.writer is not None:
        log.warning("rejecting second client %s: one connection at a time", peer)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return

    registry.writer = writer
    state.hello_requested = True  # re-send HELLO so a freshly (re)connected client sees it
    if state.last_cmd_mono is None:
        # no cmd ever received: let a freshly connected client observe the
        # watchdog firing instead of silently swallowing it pre-connect.
        state.wd_stop_sent = False
    log.info("client connected: %s", peer)
    try:
        await _rx_loop(reader, state, registry, args)
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.info("client %s disconnected: %s", peer, exc)
    finally:
        registry.writer = None
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("client disconnected: %s", peer)


def _advance_deadline(next_t: float, period: float, now: float) -> float:
    """Advance a monotonic deadline by one period. If we've fallen more than
    one period behind (e.g. a slow tick), resync to `now + period` instead
    of bursting through all the missed ticks back-to-back."""
    next_t += period
    if next_t < now - period:
        next_t = now + period
    return next_t


JOYSTICK_PERIOD_S = 1.0 / 50.0  # docs/02 §4: SK_JOYSTICK at 50 Hz


async def _joystick_loop(state: RoverState, registry: _ClientRegistry, args: argparse.Namespace) -> None:
    """Separate from _driver_loop's 10 Hz tick -- SK_JOYSTICK is reported at
    50 Hz by a real bridge (docs/02 §4), independent of the rover's own
    TELEM cadence."""
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    while True:
        now = loop.time()
        if now >= next_tick:
            next_tick = _advance_deadline(next_tick, JOYSTICK_PERIOD_S, now)
            payload = state.build_joystick_frame()
            if payload is not None:
                _send_frame(registry, wire.SK_JOYSTICK, 0, payload, args.lossy)
        await asyncio.sleep(max(0.0, next_tick - loop.time()))


async def _driver_loop(state: RoverState, registry: _ClientRegistry, args: argparse.Namespace) -> None:
    loop = asyncio.get_running_loop()
    scan_period = LIDAR_SCAN_PERIOD_S if args.lidar else SONAR_SCAN_PERIOD_S

    now = loop.time()
    next_tick = now
    next_hello = now
    next_scan = now
    next_status = now

    while True:
        now = loop.time()
        state.tick()
        silent = state.is_silent()

        if not silent and (state.hello_requested or now >= next_hello):
            state.hello_requested = False
            next_hello = _advance_deadline(next_hello, HELLO_PERIOD_S, now)
            payload = wire.encode_hello(state.build_hello())
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, payload, args.lossy)

        if not silent:
            telem_payload = wire.encode_telem(state.build_telem())
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, telem_payload, args.lossy)

        if now >= next_scan:
            next_scan = _advance_deadline(next_scan, scan_period, now)
            if not silent:
                for frag in state.build_scan_fragments():
                    _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, frag, args.lossy)

        # Acks are sent immediately in _rx_loop (docs/02 §6.8 RTT measurement
        # shouldn't be stretched by this unrelated 100ms telemetry tick).
        pending_events = state.drain_pending_events()
        if not silent:
            for ev in pending_events:
                _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, wire.encode_event(ev), args.lossy)

        if now >= next_status:
            next_status = _advance_deadline(next_status, BRIDGE_STATUS_PERIOD_S, now)
            status = wire.BridgeStatus(
                uptime_ms=state.now_ms(), rx_count=state.seq, tx_ok=state.seq, tx_fail=0,
                channel=11, last_rssi=args.rssi, rover_paired=True,
            )
            _send_frame(registry, wire.SK_BRIDGE_STATUS, 0, wire.encode_bridge_status(status), 0)

        next_tick = _advance_deadline(next_tick, TELEM_PERIOD_S, now)
        await asyncio.sleep(max(0.0, next_tick - loop.time()))


def build_state(args: argparse.Namespace) -> RoverState:
    state = RoverState(
        bme280=args.env == "bme280",
        bmp280=args.env == "bmp280",
        dht11=args.env == "dht11",
        encoders=args.encoders,
        ina219=args.ina219,
        lidar=args.lidar,
        pwm_max=args.pwm_max,
        reboot_after_s=args.reboot_after,
        silent_after_s=args.rover_silent_after,
        silent_for_s=args.rover_silent_for,
        joystick_demo=args.joystick_demo,
        joystick_demo_estop=args.joystick_demo_estop,
        joystick_fault=args.joystick_fault,
        joystick_silent_after_s=args.joystick_silent_after,
        joystick_silent_for_s=args.joystick_silent_for,
    )
    return state


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    env_group = parser.add_mutually_exclusive_group()
    env_group.add_argument("--bme280", dest="env", action="store_const", const="bme280")
    env_group.add_argument("--bmp280", dest="env", action="store_const", const="bmp280")
    env_group.add_argument("--dht11", dest="env", action="store_const", const="dht11")
    parser.set_defaults(env="bme280")
    parser.add_argument("--encoders", action="store_true")
    parser.add_argument("--ina219", action="store_true")
    parser.add_argument("--lidar", action="store_true")
    parser.add_argument("--lossy", type=int, default=0, help="drop N%% of frames")
    parser.add_argument("--rssi", type=int, default=-70)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--pwm-max", type=int, default=_default_pwm_max(), dest="pwm_max")
    parser.add_argument(
        "--reboot-after", type=float, default=None,
        help="simulate one rover reboot at this uptime in seconds (GS-2 testing)",
    )
    parser.add_argument(
        "--rover-silent-after", type=float, default=None, dest="rover_silent_after",
        help="stop HELLO/TELEM/SCAN/EVENT/ACK at this uptime in seconds (BRIDGE_STATUS keeps flowing)",
    )
    parser.add_argument(
        "--rover-silent-for", type=float, default=None, dest="rover_silent_for",
        help="how long the rover stays silent, in seconds (requires --rover-silent-after)",
    )
    parser.add_argument(
        "--joystick-demo", action="store_true",
        help="emit SK_JOYSTICK at 50 Hz: centre, forward, turn, reverse, centre (loops forever, never touches the button)",
    )
    parser.add_argument(
        "--joystick-demo-estop", action="store_true",
        help="press the left stick button once, 10s after start, then never again -- for testing E-STOP in isolation",
    )
    parser.add_argument(
        "--joystick-fault", action="store_true",
        help="inject wildly jumping SK_JOYSTICK values every frame, to test fault detection",
    )
    parser.add_argument(
        "--joystick-silent-after", type=float, default=None, dest="joystick_silent_after",
        help="stop SK_JOYSTICK at this uptime in seconds (requires --joystick-demo/-fault)",
    )
    parser.add_argument(
        "--joystick-silent-for", type=float, default=None, dest="joystick_silent_for",
        help="how long SK_JOYSTICK stays silent, in seconds",
    )
    return parser.parse_args(argv)


async def run_server(args: argparse.Namespace) -> asyncio.base_events.Server:
    state = build_state(args)
    registry = _ClientRegistry()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_client(reader, writer, state, registry, args)

    server = await asyncio.start_server(_handler, args.host, args.port)
    asyncio.create_task(_driver_loop(state, registry, args))
    asyncio.create_task(_joystick_loop(state, registry, args))
    server._rover_state = state  # tests only: direct state access, bypassing the wire
    return server


async def _amain(argv: Optional[list[str]] = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = parse_args(argv)
    server = await run_server(args)
    addr = server.sockets[0].getsockname()
    log.info("fake_rover listening on %s:%s", *addr[:2])
    async with server:
        await server.serve_forever()


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
