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
TILT_LIMIT_DEG = 35.0

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

    mode: str = "idle"
    drive_l: float = 0.0
    drive_r: float = 0.0
    servo_mode: str = "sweep"
    servo_angle_deg: int = 90
    sweep_angle_deg: float = 0.0
    sweep_dir: int = 1

    estop_latched: bool = False
    wd_ok: bool = True
    last_cmd_mono: Optional[float] = None
    last_accepted_mode: Optional[str] = None
    last_accepted_flags: Optional[int] = None

    hello_requested: bool = True  # send HELLO immediately on boot
    wd_stop_sent: bool = False
    pending_events: list[EventMsg] = field(default_factory=list)
    pending_acks: list[wire.AckMsg] = field(default_factory=list)

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

    def tick(self) -> None:
        """Advance drift/decay and enforce safety rules. Call at ~10 Hz."""
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

        # watchdog: docs/02 §5.1
        if self.last_cmd_mono is None:
            age_ms = None
        else:
            age_ms = int((now - self.last_cmd_mono) * 1000)
        if age_ms is None or age_ms > WATCHDOG_MS:
            self.wd_ok = False
            self.drive_l = 0.0
            self.drive_r = 0.0
            if not self.wd_stop_sent:
                self.wd_stop_sent = True
                self._emit_event("warn", "WD_STOP", "no cmd for 500 ms")
        else:
            self.wd_ok = True
            self.wd_stop_sent = False

        # estop latch: motors forced 0 regardless of drive
        if self.estop_latched:
            self.drive_l = 0.0
            self.drive_r = 0.0

        # tilt: docs/02 §5.3
        if abs(self.roll_deg) > TILT_LIMIT_DEG or abs(self.pitch_deg) > TILT_LIMIT_DEG:
            self.drive_l = 0.0
            self.drive_r = 0.0
            self._emit_event("warn", "TILT", f"roll={self.roll_deg:.1f} pitch={self.pitch_deg:.1f}")

        # battery critical: docs/02 §5.4
        if self.vbat_v < BATT_CRIT_V:
            self.drive_l = max(-0.3, min(0.3, self.drive_l))
            self.drive_r = max(-0.3, min(0.3, self.drive_r))
            self._emit_event("error", "BATT_CRIT", f"vbat {self.vbat_v:.1f} V")
        elif self.vbat_v < 10.5:
            self._emit_event("warn", "BATT_LOW", f"vbat {self.vbat_v:.1f} V")

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
        """docs/02 §6.8 ack rules; §5.2 estop latch."""
        self.last_cmd_mono = time.monotonic()

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

        if not self.estop_latched:
            self.drive_l = max(-1.0, min(1.0, cmd.drive.l))
            self.drive_r = max(-1.0, min(1.0, cmd.drive.r))

        self.mode = cmd.mode
        self.servo_mode = cmd.servo.mode
        self.servo_angle_deg = cmd.servo.angle_deg

        if cmd.request_hello:
            self.hello_requested = True

        ack_rule_a = (
            self.last_accepted_mode is not None
            and (cmd.mode != self.last_accepted_mode or cmd_flags != self.last_accepted_flags)
        )
        ack_rule_b = cmd.seq % 10 == 0
        self.last_accepted_mode = cmd.mode
        self.last_accepted_flags = cmd_flags

        if ack_rule_a or ack_rule_b:
            ack = wire.AckMsg(t=self.now_ms(), seq=self.next_seq(), ack_seq=cmd.seq, ok=True)
            self.pending_acks.append(ack)
            return ack
        return None

    def drain_pending_acks(self) -> list[wire.AckMsg]:
        acks, self.pending_acks = self.pending_acks, []
        return acks

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
        sonar_dist = self._sonar_dist_cm(self.sweep_angle_deg)
        pwm_l = int(self.drive_l * 255)
        pwm_r = int(self.drive_r * 255)
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
            sonar=TelemSonar(angle_deg=self.sweep_angle_deg, dist_cm=sonar_dist),
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


async def _rx_loop(reader: asyncio.StreamReader, state: RoverState) -> None:
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
            continue
        state.apply_cmd(cmd)


async def handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: RoverState,
    registry: _ClientRegistry,
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
        await _rx_loop(reader, state)
    except (ConnectionResetError, BrokenPipeError, OSError) as exc:
        log.info("client %s disconnected: %s", peer, exc)
    finally:
        registry.writer = None
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass
        log.info("client disconnected: %s", peer)


async def _driver_loop(state: RoverState, registry: _ClientRegistry, args: argparse.Namespace) -> None:
    next_hello = 0.0
    next_scan = 0.0
    next_status = 0.0
    scan_period = LIDAR_SCAN_PERIOD_S if args.lidar else SONAR_SCAN_PERIOD_S

    while True:
        now = time.monotonic()
        state.tick()

        if state.hello_requested or now >= next_hello:
            state.hello_requested = False
            next_hello = now + HELLO_PERIOD_S
            payload = wire.encode_hello(state.build_hello())
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, payload, args.lossy)

        telem_payload = wire.encode_telem(state.build_telem())
        _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, telem_payload, args.lossy)

        if now >= next_scan:
            next_scan = now + scan_period
            for frag in state.build_scan_fragments():
                _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, frag, args.lossy)

        for ack in state.drain_pending_acks():
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, wire.encode_ack(ack), args.lossy)

        for ev in state.drain_pending_events():
            _send_frame(registry, wire.SK_RX_FROM_ROVER, args.rssi, wire.encode_event(ev), args.lossy)

        if now >= next_status:
            next_status = now + BRIDGE_STATUS_PERIOD_S
            status = wire.BridgeStatus(
                uptime_ms=state.now_ms(), rx_count=state.seq, tx_ok=state.seq, tx_fail=0,
                channel=11, last_rssi=args.rssi, rover_paired=True,
            )
            _send_frame(registry, wire.SK_BRIDGE_STATUS, 0, wire.encode_bridge_status(status), 0)

        await asyncio.sleep(TELEM_PERIOD_S)


def build_state(args: argparse.Namespace) -> RoverState:
    state = RoverState(
        bme280=args.env == "bme280",
        bmp280=args.env == "bmp280",
        dht11=args.env == "dht11",
        encoders=args.encoders,
        ina219=args.ina219,
        lidar=args.lidar,
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
    return parser.parse_args(argv)


async def run_server(args: argparse.Namespace) -> asyncio.base_events.Server:
    state = build_state(args)
    registry = _ClientRegistry()

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_client(reader, writer, state, registry)

    server = await asyncio.start_server(_handler, args.host, args.port)
    asyncio.create_task(_driver_loop(state, registry, args))
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
