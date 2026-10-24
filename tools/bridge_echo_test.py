"""Bridge acceptance check (docs/06 Phase 10). Opens a COM port talking to ground_bridge,
listens for a few seconds, and verifies BRIDGE_STATUS/JOYSTICK rates and framing are healthy.

Usage:  python tools/bridge_echo_test.py COM3 [--seconds 5]

Exit 0 only if BRIDGE_STATUS arrives at ~1 Hz AND JOYSTICK at ~50 Hz AND there were zero
CRC/decode errors over the window; otherwise prints the specific failing condition and exits 1.

Reuses ground_station/app/wire.py's COBS+CRC decoder rather than reimplementing framing here.
"""
from __future__ import annotations

import argparse
import sys
import time

import serial

from ground_station.app import wire

BAUD = 921600


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help='e.g. "COM3" or "/dev/ttyUSB0"')
    ap.add_argument("--seconds", type=float, default=5.0)
    args = ap.parse_args()

    try:
        ser = serial.Serial(args.port, baudrate=BAUD, timeout=0.2)
    except (serial.SerialException, OSError) as exc:
        print(f"could not open {args.port}: {exc}")
        return 1

    status_count = 0
    joy_count = 0
    rx_from_rover_count = 0
    crc_errors = 0
    last_joy = None

    buf = bytearray()
    deadline = time.monotonic() + args.seconds
    try:
        while time.monotonic() < deadline:
            chunk = ser.read(4096)
            if not chunk:
                continue
            buf += chunk
            *frames, buf_tail = buf.split(b"\x00")
            buf = bytearray(buf_tail)
            for raw in frames:
                if not raw:
                    continue
                try:
                    frame = wire.decode_serial_frame(bytes(raw))
                except wire.WireError:
                    crc_errors += 1
                    continue
                if frame.kind == wire.SK_BRIDGE_STATUS:
                    status_count += 1
                elif frame.kind == wire.SK_JOYSTICK:
                    joy_count += 1
                    last_joy = wire.decode_joystick(frame.payload)
                    print(
                        f"\rjoystick  lx={last_joy.lx:4d} ly={last_joy.ly:4d} "
                        f"rx={last_joy.rx:4d} ry={last_joy.ry:4d} buttons={last_joy.buttons:02b}",
                        end="",
                        flush=True,
                    )
                elif frame.kind == wire.SK_RX_FROM_ROVER:
                    rx_from_rover_count += 1
    finally:
        ser.close()
    print()

    status_hz = status_count / args.seconds
    joy_hz = joy_count / args.seconds
    print(f"BRIDGE_STATUS: {status_count} frames ({status_hz:.2f} Hz)")
    print(f"JOYSTICK:      {joy_count} frames ({joy_hz:.2f} Hz)")
    print(f"RX_FROM_ROVER: {rx_from_rover_count} frames")
    print(f"CRC/decode errors: {crc_errors}")

    failures = []
    if not (0.8 <= status_hz <= 1.2):
        failures.append(f"BRIDGE_STATUS rate {status_hz:.2f} Hz outside [0.8, 1.2]")
    if not (40 <= joy_hz <= 60):
        failures.append(f"JOYSTICK rate {joy_hz:.2f} Hz outside [40, 60]")
    if crc_errors:
        failures.append(f"{crc_errors} CRC/decode errors")

    if failures:
        print("FAIL: " + "; ".join(failures))
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
