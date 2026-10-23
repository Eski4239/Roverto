"""Phase 6 — joystick drive input (docs/02 §6.12, docs/04 §1b, docs/PROGRESS_ROVER_MAIN.md).

ground_bridge only reports raw SK_JOYSTICK frames (bridge stays dumb); this
module owns everything that turns them into a safe CmdDrive: per-axis centre
calibration, deadband, invert, tank-drive mapping, and the fault/lost/
not-centred safety states. main.py feeds it decoded wire.JoystickState
frames and polls it for the 200 ms timeout rule; it never talks to the wire
or the websocket itself.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from ground_station.app import wire

RAW_CENTRE = 2048.0
RAW_MAX = 4095.0
CALIBRATION_WINDOW_MS = 500.0

Status = str  # "not_centred" | "ok" | "lost" | "fault"


@dataclass
class StickReading:
    x: float  # -1..1, after calibration/deadband/invert (0.0 before calibration)
    y: float
    raw_x: int
    raw_y: int


class JoystickController:
    def __init__(self, config: dict) -> None:
        self._deadband = config.get("deadband_pct", 8) / 100.0
        self._centre_band = config.get("centre_band", 300)
        self._timeout_ms = config.get("joystick_timeout_ms", 200)
        self._fault_jump_pct = config.get("fault_jump_pct", 50) / 100.0
        self._fault_repeat_count = config.get("fault_repeat_count", 3)
        self._invert_l = bool(config.get("invert_l", False))
        self._invert_r = bool(config.get("invert_r", False))
        self.speed_limit = float(config.get("speed_limit_default", 1.0))

        self.status: Status = "not_centred"
        self.drive_l = 0.0
        self.drive_r = 0.0
        self.left = StickReading(0.0, 0.0, 0, 0)
        self.right = StickReading(0.0, 0.0, 0, 0)
        self.buttons = 0
        self.ever_seen_frame = False

        self._calibrating = True
        self._calib_start_ms: Optional[float] = None
        self._calib_samples: list[wire.JoystickState] = []
        self._centre_l = (RAW_CENTRE, RAW_CENTRE)
        self._centre_r = (RAW_CENTRE, RAW_CENTRE)

        self._last_recv_ms: Optional[float] = None
        self._prev_norm: Optional[tuple[float, float, float, float]] = None
        self._fault_streak = 0

        self._pending_estop = False
        self._pending_event: Optional[str] = None  # one-shot code to emit, set on state change
        # P1: after an estop_reset, ignore the buttons until both are seen
        # released -- a button held straight through the reset must not
        # immediately re-latch via what would otherwise look like a fresh
        # press (belt-and-suspenders alongside main.py also zeroing the
        # estop_remaining exemption-window counter on reset).
        self._ignore_buttons_until_released = False

    def reset_calibration(self) -> None:
        """Bridge (re)connect, TAKE CONTROL, or switching input to Joystick
        (the prompt's three triggers) re-arm the 0.5 s centre-learning
        window and force sticks ignored until it passes again."""
        self._calibrating = True
        self._calib_start_ms = None
        self._calib_samples = []
        self.status = "not_centred"
        self.drive_l = 0.0
        self.drive_r = 0.0
        self._prev_norm = None
        self._fault_streak = 0

    def take_pending_estop(self) -> bool:
        """One-shot: true if a stick button fired since the last call."""
        fired = self._pending_estop
        self._pending_estop = False
        return fired

    def on_estop_reset(self) -> None:
        """Called by main.py when the controlling tab's estop_reset is
        accepted. Arms the "ignore buttons until both released" guard
        (prompt P1) so a button still held through the reset can't
        immediately re-latch -- it must be released and pressed again."""
        self._ignore_buttons_until_released = bool(self.buttons)

    def take_pending_event(self) -> Optional[str]:
        """One-shot event code to log, or None."""
        code = self._pending_event
        self._pending_event = None
        return code

    def on_frame(self, frame: wire.JoystickState, recv_wall_ms: Optional[float] = None) -> None:
        if recv_wall_ms is None:
            recv_wall_ms = time.time() * 1000.0
        self.ever_seen_frame = True
        self._last_recv_ms = recv_wall_ms

        was_pressed = self.buttons
        self.buttons = frame.buttons
        if self._ignore_buttons_until_released:
            if frame.buttons == 0:
                self._ignore_buttons_until_released = False
            # buttons held through a reset never produce a pending E-STOP
            # until they've been seen fully released first (prompt P1).
        else:
            if (frame.buttons & 0b01) and not (was_pressed & 0b01):
                self._pending_estop = True
            if (frame.buttons & 0b10) and not (was_pressed & 0b10):
                self._pending_estop = True

        if self._calibrating:
            self._run_calibration(frame, recv_wall_ms)
            return

        self._apply_frame(frame)

    def _run_calibration(self, frame: wire.JoystickState, recv_wall_ms: float) -> None:
        if self._calib_start_ms is None:
            self._calib_start_ms = recv_wall_ms
        self._calib_samples.append(frame)
        if recv_wall_ms - self._calib_start_ms < CALIBRATION_WINDOW_MS:
            return

        lx = sum(s.lx for s in self._calib_samples) / len(self._calib_samples)
        ly = sum(s.ly for s in self._calib_samples) / len(self._calib_samples)
        rx = sum(s.rx for s in self._calib_samples) / len(self._calib_samples)
        ry = sum(s.ry for s in self._calib_samples) / len(self._calib_samples)
        plausible = all(
            abs(v - RAW_CENTRE) <= self._centre_band for v in (lx, ly, rx, ry)
        )
        self._calibrating = False
        self._calib_samples = []
        if not plausible:
            self.status = "not_centred"
            self._pending_event = "JOYSTICK_NOT_CENTRED"
            self._calibrating = True  # stay ignored; needs an explicit re-trigger
            self._calib_start_ms = None
            return
        self._centre_l = (lx, ly)
        self._centre_r = (rx, ry)
        self.status = "ok"
        self._prev_norm = None
        self._fault_streak = 0

    def _normalise(self, raw: float, centre: float) -> float:
        span = (RAW_MAX - centre) if raw >= centre else centre
        if span <= 0:
            return 0.0
        v = (raw - centre) / span
        v = max(-1.0, min(1.0, v))
        if abs(v) < self._deadband:
            return 0.0
        # rescale so the stick still reaches +-1 at full deflection past the deadband
        sign = 1.0 if v > 0 else -1.0
        return sign * (abs(v) - self._deadband) / (1.0 - self._deadband)

    def _apply_frame(self, frame: wire.JoystickState) -> None:
        lx = self._normalise(frame.lx, self._centre_l[0])
        ly = self._normalise(frame.ly, self._centre_l[1])
        rx = self._normalise(frame.rx, self._centre_r[0])
        ry = self._normalise(frame.ry, self._centre_r[1])

        if self._prev_norm is not None:
            jumps = [abs(a - b) > self._fault_jump_pct * 2 for a, b in zip((lx, ly, rx, ry), self._prev_norm)]
            if any(jumps):
                self._fault_streak += 1
            else:
                self._fault_streak = 0
        self._prev_norm = (lx, ly, rx, ry)

        if self._fault_streak >= self._fault_repeat_count:
            if self.status != "fault":
                self._pending_event = "JOYSTICK_FAULT"
            self.status = "fault"
            self.drive_l = 0.0
            self.drive_r = 0.0
            self.left = StickReading(lx, ly, frame.lx, frame.ly)
            self.right = StickReading(rx, ry, frame.rx, frame.ry)
            return

        self.status = "ok"
        self.left = StickReading(lx, ly, frame.lx, frame.ly)
        self.right = StickReading(rx, ry, frame.rx, frame.ry)

        left_y = -ly if self._invert_l else ly
        right_y = -ry if self._invert_r else ry
        self.drive_l = max(-1.0, min(1.0, left_y * self.speed_limit))
        self.drive_r = max(-1.0, min(1.0, right_y * self.speed_limit))

    def poll_timeout(self, now_wall_ms: Optional[float] = None) -> None:
        if now_wall_ms is None:
            now_wall_ms = time.time() * 1000.0
        if self._last_recv_ms is None or self._calibrating:
            return
        age_ms = now_wall_ms - self._last_recv_ms
        if age_ms >= self._timeout_ms:
            if self.status != "lost":
                self._pending_event = "JOYSTICK_LOST"
            self.status = "lost"
            self.drive_l = 0.0
            self.drive_r = 0.0

    def to_block(self) -> dict:
        return {
            "available": self.ever_seen_frame,
            "status": self.status,
            "left": {"x": self.left.x, "y": self.left.y, "button": bool(self.buttons & 0b01)},
            "right": {"x": self.right.x, "y": self.right.y, "button": bool(self.buttons & 0b10)},
            "drive": {"l": self.drive_l, "r": self.drive_r},
            "deadband_pct": self._deadband * 100.0,
        }
