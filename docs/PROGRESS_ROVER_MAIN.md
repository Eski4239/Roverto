# rover_main — progress log & design decisions

**Owner:** Victor (rover electronics + `firmware/rover_main`).
**Ground station / dashboard:** Eski4239 (`ground_station/`, `simulator/`).
**Purpose:** shared memory between both humans *and* both Claude agents. Read this before touching
anything that talks to the rover. Newest entries on top in the session log (§5).

How to use this file
- Decisions have an ID (`D-xxx`) and a status: **PROPOSED** (rover side suggests, GS side please
  review) · **AGREED** (both confirmed) · **DONE** (implemented and tested).
- Anything marked **⚠ GS impact** changes what the ground station sees or must do.
- Anything that touches `docs/02` or `firmware/common/` still follows CLAUDE.md rule 1 (one commit,
  reviewed PR, golden files regenerated). This log does **not** replace docs/02; it records *why*.

---

## 1. Ownership

| Area | Owner | Notes |
|------|-------|-------|
| Rover hardware: wiring, power tree, sensor mounting | Victor | pin plan in docs/04 §1 |
| `firmware/rover_main` (Phase 11) | Victor | |
| `firmware/ground_bridge` (Phase 10) | Eski4239 | runs on the GS-side ESP32 (Q-1, agreed 2026-10-20) |
| `ground_station/`, `simulator/` (Phases 2–9) | Eski4239 | |
| `docs/02`, `firmware/common/rover_protocol.h` | shared, PR only | |
| Bench test doc (Phase 12) | both | |

## 2. Status

State of the repo when this log started (2026-10-20): Phase 0 and Phase 1 done (protocol models,
wire codec, golden tests). Verified: `tools/golden_gen.cpp` compiled against `rover_protocol.h`
reproduces all 8 `tests/golden/*.hex` byte-for-byte → the wire protocol is frozen, Track B can start.
Same day, GS side pushed Phases 2–4 (simulator, backend core, dashboard layout + top bar).

rover_main plan (each step is flashed and tested on its own before the next):

| # | Step | Status | Test |
|---|------|--------|------|
| R0 | Toolchain: PlatformIO + pioarduino platform (D-001), USB drivers, read both board MACs | TODO | `pio run` builds an empty sketch; MACs written down |
| R1 | Skeleton: `platformio.ini`, `secrets.example.h`, `millis()` scheduler, `Driver` interface, `loop_hz`, serial console with `dump_golden` | TODO | `dump_golden` hex == `tests/golden/telem.hex` and `cmd.hex` (proves struct packing on the target compiler) |
| R2 | Motors (TB6612) + safety core: watchdog 500 ms, E-STOP latch, PWM ramp, PWM_MAX | TODO | wheels in the air; bench serial drive (D-006); no command → stop ≤ 500 ms |
| R3 | ESP-NOW link: peer from `secrets.h`, RX cb → buffer only, CmdMsg validation, HELLO / TELEM / ACK / EVENT | TODO | with bridge (or temp. second-board sketch): dashboard shows link OK |
| R4 | IMU MPU-6050: tolerant WHO_AM_I, gyro bias at boot, complementary filter 50 Hz, TILT cut-off | TODO | tilt by hand > 35° → motors stop + TILT event |
| R5 | Battery: divider (D-002), 2-point calibration, SoC LUT, filtering, BATT_LOW / BATT_CRIT | TODO | ±0.1 V vs multimeter |
| R6 | Env: chip-ID detection BME280 / BMP280, DHT11 fallback, `alt_m` reference | TODO | breathe → hum ↑; lift 1 m → alt ≈ +1 m |
| R7 | BH1750 light | TODO | cover / torch → lux changes |
| R8 | HC-SR04 (non-blocking, D-005) + SG90 sweep → ScanMsg, OBSTACLE event | TODO | box at 50 cm shows in sweep |
| R9 | Buzzer, sys stats, `reset_reason`, BOOT event | TODO | |
| R10 | Stub drivers (present=false, NaN): encoders, INA219, LiDAR | TODO | HELLO bits 5/6/8 = 0 |
| R11 | End-to-end with real ground station (`--link auto`) | TODO | unplug bridge → wheels stop ≤ 0.5 s |
| R12 | Bench test (Phase 12, docs/07) incl. ESP-NOW range | TODO | |

## 3. Decisions

| ID | Decision | Status | GS impact |
|----|----------|--------|-----------|
| D-001 | **Toolchain:** official `platformio/platform-espressif32` does not ship arduino-esp32 3.x; use the community **pioarduino** platform (`platform = https://github.com/pioarduino/platform-espressif32/releases/download/stable/platform-espressif32.zip`). Pin the exact release in `platformio.ini` once it builds, so both boards use the same core. Same applies to `ground_bridge`. | **AGREED** 2026-10-20 | bridge uses same platform |
| D-002 | **Battery divider 100k/33k → 100k/22k.** With 100k/33k, 12.6 V gives 3.13 V on GPIO34, above the ESP32 ADC's accurate range at 12 dB attenuation (~150–2450 mV) and at saturation. 100k/22k gives 2.27 V @ 12.6 V and 1.62 V @ 9.0 V. Multiplier becomes 122/22. docs/01 §6 and docs/04 §B to be updated. | **AGREED** 2026-10-20 | none (value on the wire unchanged) |
| D-003 | **Single `seq` counter** for *all* rover→GS messages (HELLO, TELEM, each SCAN fragment, EVENT, ACK), as docs/02 §1 says "per sender". Loss % on the GS is computed over all message types. | AGREED — already done this way in `simulator/fake_rover.py` and `state.py` `LinkTracker` (tolerates reordering) | none |
| D-004 | **`mot.pwm_l/pwm_r` = PWM actually applied** after clamp, ramp, safety cut-offs and PWM_MAX (not the raw `drive` × 255). So after E-STOP/WD/TILT the GS sees 0 even if it is still sending drive. | **AGREED** 2026-10-20 | ⚠ UI "cmd vs rpm" bars show applied PWM |
| D-005 | **HC-SR04 never blocks the loop:** no `pulseIn()`. TRIG pulse, then ECHO edges timed in a GPIO interrupt with `micros()`; timeout 25 ms → `dist_cm = NaN` / `0xFFFF`. | **AGREED** 2026-10-20 | none |
| D-006 | **Bench drive over USB serial** behind build flag `BENCH_SERIAL_CMD` (off by default): console command `drive <l> <r>` feeds the same CmdMsg path and the same 500 ms watchdog. For R2 before the radio link exists. Never enabled in the competition build. | **AGREED** 2026-10-20 | none |
| D-007 | **PWM ramp** (slew limit, e.g. ≤ 10 PWM steps per 10 ms) on both motors to reduce brownouts when motors start while the radio transmits. E-STOP / WD / TILT cut to 0 *immediately*, no ramp down. | **AGREED** 2026-10-20 | none |
| D-008 | **MPU-6050 own I2C code** (not the Adafruit lib): accept WHO_AM_I 0x68 and common clone IDs, so clone boards don't show "NOT INSTALLED". Gyro bias averaged for ~1 s at boot → the rover must be still at power-on. | **AGREED** 2026-10-20 | none |
| D-009 | **Env detection:** read register 0xD0 at 0x76/0x77 first; 0x60 → Adafruit_BME280, 0x58 → Adafruit_BMP280 (`hum_pct = NaN`), nothing → try DHT11 (`press_hpa = alt_m = NaN`). | **AGREED** 2026-10-20 | none (already in docs/02 §2.1) |
| D-010 | **CmdMsg validation** before it counts as "valid" for the watchdog: source MAC == `PEER_MAC`, len == 30, magic/ver/type OK, `drive_l/r` finite, mode ≤ 3. Otherwise ignored + CMD_REJECTED (max 1 event/s). | **AGREED** 2026-10-20 | none |
| D-011 | `chip_temp_c` from `temperatureRead()` is unreliable on many classic ESP32s (often a constant). Sent as-is; GS should treat it as indicative only. | **AGREED** 2026-10-20 | ⚠ don't alarm hard on it |
| D-012 | **Simulator parity for CmdMsg handling** (mirror `fake_rover.py` `apply_cmd`): ack rule (a) is not evaluated on the first CmdMsg after boot (no previous to compare); if one CmdMsg carries both `estop` and `estop_reset`, reset wins (latch released); servo and mode are applied even while E-STOP is latched, drive is not. | **AGREED** 2026-10-20 | none (matches sim) |
| D-013 | **Motors provisional: Arduino-kit TT gear motors (3–6 V).** `PWM_MAX` is a constant in `config.h`; until the TB6612 VM supply is confirmed, default **PWM_MAX = 120** (≈6 V average from a 12.6 V battery). `drive = ±1.0` maps to ±PWM_MAX. Re-tune when the final motors are chosen. | **AGREED** 2026-10-20 | ⚠ `pwm_l/r` on the wire peak at ±PWM_MAX, not ±255 |
| D-014 | **Provisional safety behaviour = simulator behaviour** until Q-3/Q-4/Q-5 are decided, so the dashboard behaves the same with sim and real rover: TILT auto-resumes when back under the limit; BATT_LOW < 10.5 V, BATT_CRIT < 9.9 V (drive limited to 30 %); every mode drives like `manual`. Firmware adds what the sim lacks: hysteresis (TILT resume < 30°, battery +0.2 V) and events rate-limited (one per state change, see GS-1). | **AGREED** 2026-10-20 | see GS-1 |
| D-015 | **On boot `seq` starts at 0 and `t_ms` = `millis()`** (restarts at 0 on every reset). The first message after boot is a HELLO with `reset_reason` (docs/02 §2.1), sent before any TELEM. | **AGREED** 2026-10-20 (GS: Pablo) — details in GS-2 | ⚠ GS detects a reboot by `t_ms` going backwards (GS-2) |

## 4. Open questions (answer here, then turn into decisions)

- ~~**Q-1** Who writes `firmware/ground_bridge`?~~ → **Eski4239** (2026-10-20). Rover side needs it
  for R3; if it isn't ready by then, rover side writes a throw-away test sketch.
- **Q-2 Motor supply:** is TB6612 VM fed straight from the 3S battery (up to 12.6 V)? TT motors are
  usually rated 3–6 V and TB6612 is 1.2 A/channel continuous. If VM = battery, cap PWM_MAX ≈ 120/255
  (~6 V average). Need the motor datasheet / measured stall current.
  **2026-10-20:** final motors not chosen; provisionally Arduino-kit TT motors → D-013. Still need:
  how VM is wired.
- **Q-3 TILT behaviour:** latch until E-STOP reset, or auto-resume when |roll|,|pitch| < 30° *and* a
  zero-drive CmdMsg has been received? Proposal: auto-resume with that hysteresis.
- **Q-4 BATT_LOW threshold:** docs/02 §5 only defines BATT_CRIT (< 9.9 V). Proposal: BATT_LOW < 10.5 V
  (matches the red threshold in docs/03), both with 0.2 V hysteresis and 3 s persistence so motor
  current sag doesn't spam events. → needs a docs/02 PR.
- **Q-5 Modes:** `assisted` and `auto` have no defined behaviour. Proposal: `assisted` = manual but
  forward drive blocked while front sonar < 20 cm (OBSTACLE event); `auto` = rejected
  (AckMsg ok=0, CMD_REJECTED) until navigation exists. → needs a docs/02 PR.
- **Q-3/Q-4/Q-5 AGREED 2026-10-20 (GS: Pablo) as proposed:** TILT auto-resumes when |roll|,|pitch| < 30° and a zero-drive CmdMsg has been received; BATT_LOW < 10.5 V (0.2 V hysteresis, 3 s persistence, same for BATT_CRIT); `assisted` = manual with forward drive blocked while front sonar < 20 cm (OBSTACLE event); `auto` rejected (AckMsg ok=0 + CMD_REJECTED) until navigation exists. Written into docs/02 §5.

### Notes for the GS side (found while reviewing Phases 2–4)
- **GS-1 Event spam in the simulator:** `RoverState.tick()` runs at 10 Hz and appends TILT,
  BATT_CRIT and BATT_LOW events on *every* tick while the condition holds (≈10 events/s, each
  using a seq). rover_main will emit them once per state change (plus WD_STOP already works that
  way in the sim). Suggest the sim does the same, so event log and loss % look like the real rover.
- **GS-2 Early rover reboots aren't detected:** `state.py` resets loss tracking on a backward seq jump
  ≥ `RESTART_BACKWARD_JUMP` (1000). The rover sends ≈12 msgs/s, so a reboot in the first ~80 s of
  uptime (typical: brownout at the first motor start) jumps back < 1000 and is missed → wrong loss %
  for 10 s. Suggest also resetting when a HELLO / TELEM header `t_ms` goes backwards vs the last one
  received (rover `millis()` restarts at 0 on every boot; it only wraps after 49 days). See D-015.
  **AGREED 2026-10-20 (GS side, Pablo).** Implementation on the GS side (`state.py`), in this order:
  1. **Primary:** `t_ms` of any rover message < `last_t_ms − 500` → rover restart. Tolerance 500 ms
     covers any reordering; `t_ms` is one clock per sender (same idea as D-003).
     Exception: `last_t_ms > 2^32 − 60 000` and new `t_ms` small → `millis()` wrap (49.7 days), not a restart.
  2. **Secondary:** HELLO with `seq == 0` → restart (catches a reboot even if the first TELEM is lost).
  3. **Fallback:** keep the backward seq jump ≥ `RESTART_BACKWARD_JUMP`.
  On restart: reset loss window + seq baseline, drop pending RTT timestamps and partial scan
  fragments, emit GS event `ROVER_RESTART` with the `reset_reason` from the next HELLO
  (BROWNOUT / PANIC / *WDT → warn). Mission clock keeps running. A link reconnect (bridge/USB)
  is *not* a rover restart.
  **GS also:** if TELEM arrives but no HELLO has been seen since the restart, set
  `CMD_REQUEST_HELLO` on the next CmdMsgs until a HELLO arrives (D-015's "HELLO first" can be lost
  on the radio). Simulator gets a `--reboot-after N` flag to test this without killing the process.

## 5. Session log (newest first)

### 2026-10-21 — GS Phase 5 fixes (Pablo + Claude)
- GS side finished Phase 5 (environment/rover health panels + fixes from `wip/phase-5-panels`):
  topbar mode indicator, `env.alt_m` in the environment panel, sparkline downsampling/min-span,
  2 s graceful shutdown, and the command heartbeat below.
- **Backend now owns the 10 Hz CmdMsg heartbeat** (`ground_station/app/main.py`): it generates and
  sends a fresh `CmdMsg` every 100 ms itself, independent of whether a browser tab is connected or
  sending anything — RTT now shows a real number without touching E-STOP, and the rover's 500 ms
  watchdog stays satisfied with zero UI clients connected.
- **One UI tab is "in control"** at a time: first connected tab controls drive/mode/servo/buzzer;
  other tabs are view-only (dashboard shows "VIEW ONLY"). No auto-promotion if the controller
  disconnects — a "TAKE CONTROL" button appears for any tab once nobody is in control.
  E-STOP/E-STOP-RESET bypass this gating as a safety exception: any connected tab's E-STOP is
  always honored and merged into the next heartbeat tick, regardless of control state.
- Found and fixed two real latency bugs surfaced while chasing RTT (not GS-protocol issues, so no
  docs/02 change): `Link._reader_loop` was calling `ser.read(4096)`, which pyserial blocks on until
  either 4096 bytes arrive or the full read timeout elapses — switched to `read(1)` + drain
  `in_waiting`. `simulator/fake_rover.py` was batching the ack onto its own 100 ms telemetry tick
  instead of writing it the moment `apply_cmd` processes the CmdMsg — now sent immediately from
  `_rx_loop`, matching how real rover_main is expected to reply within one loop iteration (~10 ms).
- Added `tests/test_cmd_heartbeat.py` (heartbeat/RTT/control-handoff/E-STOP-bypass/shutdown, run
  against the real simulator) and a small JS test suite (`tests_js/`, run via `node --test`, wired
  into `pytest -q` via `tests/test_js.py`; skips with a message if Node isn't installed).

### 2026-10-20 (3) — GS reply (Pablo + Claude)
- **D-015 and GS-2 AGREED** with the detection order and refinements written under GS-2
  (t_ms primary, HELLO seq 0 secondary, seq jump fallback; request HELLO if missing).
  Also recorded in docs/02 §6.10. GS implementation is done before Phase 5.
- **GS reply: D-001…D-014 all AGREED as written; Q-3, Q-4, Q-5 AGREED as proposed** (docs/02 §5,
  docs/01 §6, docs/04 §B, docs/03 thresholds updated). GS still to implement: GS-1, GS-2,
  D-004/D-013 PWM scaling, D-011 chip temp, assisted/auto in the simulator.

### 2026-10-20 (2) — answers + review of GS Phases 2–4
- Q-1 answered: Eski4239 owns `ground_bridge`.
- Motors not decided; provisional Arduino TT motors → D-013 (PWM_MAX = 120 by default).
- Reviewed `simulator/fake_rover.py`, `state.py`, `link.py`: D-003 confirmed (single seq, GS loss
  calc already handles it). Recorded sim behaviour the firmware will mirror (D-012, D-014) and one
  suggestion for the sim (GS-1).
- After rebase on `431c7bd` (Phase 4 fixes): GS now detects a rover reboot by a backward seq jump
  ≥ 1000. Added GS-2 (early reboots) + D-015.

### 2026-10-20 — kickoff (Victor + Claude)
- Read the whole repo (CLAUDE.md, docs/01–06, TEAM_BRIEF, rover_protocol.h, wire.py, protocol.py,
  tests, golden_gen.cpp).
- Verified golden files == C structs (compiled `golden_gen.cpp`, 8/8 identical).
- Wrote this log: rover_main step plan R0–R12, proposed decisions D-001…D-011, open questions Q-1…Q-5.
- Next: R0 (toolchain + MACs) and answers to Q-1/Q-2 before writing motor code.
