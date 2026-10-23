"""Unit tests for ground_station/app/joystick.py — no simulator/app needed.
P1 regression (see docs/PROGRESS_ROVER_MAIN.md Phase 6 live-test findings):
a stick button held through an estop_reset must not immediately re-latch.
"""
from __future__ import annotations

import time

from ground_station.app import wire
from ground_station.app.joystick import JoystickController

CONFIG = {
    "deadband_pct": 8, "centre_band": 300, "joystick_timeout_ms": 200,
    "fault_jump_pct": 50, "fault_repeat_count": 3,
    "invert_l": False, "invert_r": False, "speed_limit_default": 1.0,
}


def _calibrated_controller() -> JoystickController:
    j = JoystickController(CONFIG)
    t = time.time() * 1000
    for i in range(30):
        f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=0, seq=i % 256)
        j.on_frame(f, t + i * 20)
    assert j.status == "ok"
    return j


def test_button_press_fires_once_while_held():
    j = _calibrated_controller()
    t = time.time() * 1000
    fired = 0
    for k in range(50):  # 1s at 50Hz, button held throughout
        f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=1, seq=k)
        j.on_frame(f, t + k * 20)
        if j.take_pending_estop():
            fired += 1
    assert fired == 1


def test_estop_reset_while_held_does_not_relatch():
    """P1: press, reset, keep holding -> must stay reset."""
    j = _calibrated_controller()
    t = time.time() * 1000

    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=1, seq=0)
    j.on_frame(f, t)
    assert j.take_pending_estop() is True

    j.on_estop_reset()  # operator resets while the button is still down

    for k in range(1, 30):
        f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=1, seq=k)
        j.on_frame(f, t + k * 20)
        assert j.take_pending_estop() is False, f"re-latched while held at frame {k}"


def test_release_then_press_again_fires_after_reset():
    """P1: after reset, releasing and pressing again must E-STOP again."""
    j = _calibrated_controller()
    t = time.time() * 1000

    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=1, seq=0)
    j.on_frame(f, t)
    assert j.take_pending_estop() is True
    j.on_estop_reset()

    # release
    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=0, seq=1)
    j.on_frame(f, t + 20)
    assert j.take_pending_estop() is False

    # fresh press
    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=1, seq=2)
    j.on_frame(f, t + 40)
    assert j.take_pending_estop() is True


def test_right_button_also_guarded_by_reset():
    j = _calibrated_controller()
    t = time.time() * 1000

    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=0b10, seq=0)
    j.on_frame(f, t)
    assert j.take_pending_estop() is True
    j.on_estop_reset()

    f = wire.JoystickState(lx=2048, ly=2048, rx=2048, ry=2048, buttons=0b10, seq=1)
    j.on_frame(f, t + 20)
    assert j.take_pending_estop() is False
