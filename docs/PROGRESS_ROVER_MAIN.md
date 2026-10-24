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

## 0. Current focus (update at the end of every session)

**Now:** R0 done — toolchain builds (pioarduino **55.03.312** = arduino-esp32 3.3.12, pinned per D-001),
both MACs read with `tools/mac_reader` (`pio run -d tools/mac_reader -t upload --upload-port COMx`).
⚠ Run `pio` from PowerShell / the PlatformIO terminal, **not Git Bash**: the Espressif toolchain
installer refuses MSYS/MinGW shells ("MSys/Mingw is not supported") and the first build fails.
**Proposed to GS:** D-016 (assisted threshold 10 cm) and Q-6 (sonar angle convention) — need Pablo's OK
and a docs/02 PR.
**Board MACs** (WiFi STA MAC; boards physically labelled):

| Board | Role | MAC |
|-------|------|-----|
| ESP32 #1 | rover_main | `20:50:0D:07:83:14` (ESP32-D0WD-V3 rev 3.1, 4 MB) |
| ESP32 #2 | ground_bridge | `20:50:0D:00:7D:FC` |

**Next:** R1 skeleton of `firmware/rover_main` (`secrets.h`: PEER_MAC = bridge MAC). Pablo: bridge `secrets.h` PEER_MAC = rover MAC.
**Safety/mode behaviour source of truth:** docs/02 §5 (Q-3/Q-4/Q-5 agreed); D-014 is superseded.

**Session ritual for any agent working on rover_main:** at start `git pull`; at the end update §0,
§2 status and §5 session log, commit and push.

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
| R0 | Toolchain: PlatformIO + pioarduino platform (D-001), USB drivers, read both board MACs | **DONE** 2026-10-24 | `pio run` builds an empty sketch; MACs written down |
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
| D-014 | ~~**Provisional safety behaviour = simulator behaviour** until Q-3/Q-4/Q-5 are decided, so the dashboard behaves the same with sim and real rover: TILT auto-resumes when back under the limit; BATT_LOW < 10.5 V, BATT_CRIT < 9.9 V (drive limited to 30 %); every mode drives like `manual`. Firmware adds what the sim lacks: hysteresis (TILT resume < 30°, battery +0.2 V) and events rate-limited (one per state change, see GS-1).~~ | **SUPERSEDED** 2026-10-20 by the agreed Q-3/Q-4/Q-5 now in docs/02 §5 (rules 3, 4, 4b). Firmware follows docs/02, not the simulator, where they differ | sim should follow docs/02 §5 (see GS-1) |
| D-016 | **`assisted` obstacle threshold 20 cm → 10 cm.** 20 cm is too conservative for the rover's size (Victor). For the threshold to mean anything the front reading must be fresh: in sweep mode 0° is only seen about once per ~2 s round trip, and the rover covers tens of cm in that time. Proposal: in `assisted` the rover parks the servo at front (sweep ignored) and pings every ~60 ms; forward is blocked if front < 10 cm **or** the last front reading is older than 200 ms / no echo (fail-safe). Final value confirmed by a stopping-distance measurement in R8/R12. Needs a docs/02 §5 rule 4b PR + `OBSTACLE_DIST_CM` in the simulator. | **PROPOSED** 2026-10-24 | ⚠ OBSTACLE fires at 10 cm; servo doesn't sweep in assisted. Dashboard sonar colour thresholds (config.toml) unchanged unless GS wants it |
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

- **Q-6 Sonar angle convention:** docs/02 §2.3 says rover frame, 0° = front, CCW+, but the servo
  (`servo_angle_deg` 0–180 in CmdMsg) has front at ~90°, and `ScanMsg.start_cdeg` is `uint16`
  (no negative angles). The simulator sweeps 0–180 and treats 0 as front. Proposal: scan/telem
  angle = servo angle − 90 (−90…+90, left = +), encoded as `(angle × 100) mod 36000` on the wire
  (so −90° = 27000); `servo_angle_deg` in CmdMsg stays the raw servo angle (90 = front). Must be
  settled before R8. → docs/02 PR.

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
- **GS-3 Drive preset radar shows only the current beam, not the sweep outline** (known issue, not
  fixed yet — flagged during Phase 6 live testing, 2026-10-23). `surroundingswidget.js`'s large
  sonar panel draws a single `<polyline>` from the centre to the latest `telem.sonar` reading each
  tick, same as `sonarwidget.js`'s small radar line — neither widget accumulates the points from a
  full sweep (the periodic `scan` message, docs/02 §2.3) into a drawn outline/trail. The Science
  preset's `SonarWidget` has the same limitation. Low priority: cosmetic, doesn't affect any safety
  behaviour; would need its own small change (consume `snapshot.scan.pts` and draw all of them,
  fading older sweeps) rather than a quick fix bundled into something else.
  **GS also:** if TELEM arrives but no HELLO has been seen since the restart, set
  `CMD_REQUEST_HELLO` on the next CmdMsgs until a HELLO arrives (D-015's "HELLO first" can be lost
  on the radio). Simulator gets a `--reboot-after N` flag to test this without killing the process.
- **GS-4 BME280 confirmed fitted (2026-10-24, for Victor):** docs/04 §0/§A now say **FITTED**, not
  "buy now" — the module is on the board. At R6, verify chip ID at 0x76/0x77 reads **0x60**
  (BME280, has humidity) and not **0x58** (BMP280 — no humidity; `hw.env.model` must still report
  `"bmp280"` and `hum_pct` stays `NaN`/`null`, per D-009, if that's what you actually get). Take the
  `alt_m` pressure reference at boot, before the first TELEM. GS side is already fully wired for
  this (env fields, `hw.env.model`, simulator `--bme280` default, dashboard Environment tiles with
  per-model gating) — no GS changes needed once R6 lands.

## 5. Session log (newest first)

### 2026-10-24 — rover side: R0 toolchain + MAC reader (Victor + Claude)
- Added `tools/mac_reader` (PlatformIO): prints the WiFi STA MAC (`esp_read_mac`, the one ESP-NOW
  uses) and a ready-to-paste `PEER_MAC` line. Builds with pioarduino 55.03.312 (arduino-esp32
  3.3.12), now pinned. Usable by the GS side for the bridge board too.
- Proposed D-016 (assisted obstacle threshold 20 → 10 cm, with fresh front reading) and Q-6
  (sonar angle convention vs servo angle / unsigned `start_cdeg`). Waiting for GS review.
- Both MACs read with mac_reader and recorded in §0 (rover 20:50:0D:07:83:14, bridge 20:50:0D:00:7D:FC). R0 DONE.
- Next: R1 skeleton.

### 2026-10-23 — GS side: Phase 6 merged
Manual driving: two thumbsticks (tank drive) wired to the ground_bridge, reported via SK_JOYSTICK;
laptop maps them to CmdMsg. Stick button = E-STOP. Keyboard backup. Next GS: Phase 10 ground_bridge
firmware (reads the sticks, needed for R3).

### 2026-10-23 — GS side: Phase 6 second live-test follow-up (Pablo + Claude)
Re-tested the two items reported from a live screenshot (input=Keyboard, simulator
without any joystick flags, holding D):
1. **Drive preset motor/attitude still blank**: could not reproduce against the current
   code in several manual Playwright runs (motor bars and roll/pitch/yaw all updated
   correctly while driving). Most likely the live session was against a stale browser
   cache or a backend process predating the 2026-10-22 `this.root.querySelector` fix —
   no further code change made. Added
   `test_drive_preset_motor_and_attitude_update_with_plain_keyboard` (Playwright,
   `tests/test_layout_playwright.py`) matching the exact reported scenario (plain
   simulator, no joystick flags, hold D, read Drive's motor value AND roll/pitch/yaw
   text) to lock in the working behaviour and catch any future regression.
2. **SAFETY: joystick widget showing OK/-1.00/-1.00 with no frames or after loss**: also
   could not reproduce at the backend (WS protocol) level or in a real browser session —
   both the never-received and frames-stop-mid-drive scenarios correctly showed
   NO JOYSTICK/LOST with drive 0 throughout testing. Added the three requested
   regression tests to `tests/test_joystick.py` regardless, since this is a safety
   property worth locking in permanently even though it couldn't be reproduced this
   session: `test_never_received_joystick_frame_drives_zero_for_2s`,
   `test_frames_stop_mid_drive_zeroes_within_200ms_and_shows_lost`,
   `test_joystick_status_text_matches_backend_state_in_every_case`. All three pass
   against current code.
3. **GS-3** (radar beam vs sweep outline) logged above as a known, not-yet-fixed issue —
   no code change.
`pytest -q` and `pytest -m layout` both green after this round; see below for counts.

### 2026-10-22 (3) — GS side: Phase 6 live-test follow-up (Pablo + Claude)
Live testing of the Phase 6 build surfaced two real issues (not an E-STOP
defect, as first suspected):
- **Demo pattern confusion**: `--joystick-demo` pressed the stick button
  once per 6-7s loop as part of a combined drive+button script. That made
  a correctly-working E-STOP look broken (it kept re-latching every loop).
  Split into two flags: `--joystick-demo` is now pure driving (centre →
  forward → turn → reverse → centre, loops forever, never touches the
  button); new `--joystick-demo-estop` presses the button exactly once,
  10s after start, never again — for testing E-STOP in isolation.
- **Drive preset never updated**: `MotorWidget`, `AttitudeWidget`, and
  `StripsWidget` are each mounted twice (once per preset that shows them),
  but all three built their markup with the *same* internal element ids
  every time. `document.getElementById` only ever finds the first match in
  the whole page (Systems, since it's first in index.html) — the Drive
  instance's identically-id'd elements were "ghost" nodes nothing ever
  wrote to, regardless of which preset was visible. Fixed by scoping every
  internal lookup to `this.root.querySelector(...)` instead of the global
  `document`. Confirmed live with a real browser (Playwright): the Drive
  preset's motor bars and sonar distance now track the demo pattern
  independently of Systems/Science. Also scoped `SonarWidget` similarly
  for consistency, even though it's currently single-instance.
New tests: `tests/test_layout_playwright.py::test_drive_preset_motor_and_sonar_update_while_driving`
(drives via keyboard, watches the Drive preset specifically — catches a
regression back to the global-document bug even if Systems still looks
fine), plus `test_joystick.py` updates for the split demo flags
(`test_demo_estop_fires_exactly_once_never_again`, renamed
`test_demo_estop_pattern_includes_release_after_button_press`).
`pytest -q`: 97 passed. `pytest -m layout`: 9 passed.

### 2026-10-22 (2) — GS side: Phase 6 controls with joysticks (Pablo + Claude)
- Backend: new `ground_station/app/joystick.py` (`JoystickController`) decodes `SK_JOYSTICK`
  frames (already wire-ready since the protocol/joystick-serial PR), does per-axis centre
  calibration (0.5 s window after bridge connect/TAKE CONTROL/switch-to-Joystick), ±8% deadband,
  per-axis invert, tank-drive mapping, and fault/lost detection. `main.py`'s `_ingest_loop` now has
  the missing `SK_JOYSTICK` branch; a new `_joystick_timeout_loop` polls the 200 ms lost-frame rule.
- Input selector (Joystick/Keyboard) is backend-authoritative: `main.py` tracks `input_mode` for the
  controlling tab and only lets joystick-derived drive reach the outgoing `CmdMsg` when a tab
  controls, has Joystick selected, and calibration/fault checks say OK — the actual safety
  enforcement, not just a UI convention. New WS message `set_input_mode`; TAKE CONTROL always
  resets to Keyboard and re-arms calibration.
- Either stick button E-STOPs immediately via the same immediate-send path as the UI E-STOP
  button, even with nobody in control; `estop_reset` stays controller-tab-only as before.
- Three new GS-synthesized `EventCode`s (`JOYSTICK_NOT_CENTRED`, `JOYSTICK_LOST`,
  `JOYSTICK_FAULT`), same precedent as `ROVER_RESTART` — documented in docs/02 §6.13.
- Keyboard input (W/S/A/D + arrows, Shift boost) is computed entirely client-side
  (`keyboard.js`, pure `driveFromKeys()` + a thin `KeyboardInput` class), sent through the existing
  `socket.sendCmd({drive:...})` path at ≤20 Hz; blur/TAKE CONTROL/mode-switch all release held keys.
- `controlpanel.js` rewritten: live input selector, joystick widget (two stick circles, deadband
  ring, button dot, status text, resulting L/R), mode/servo/buzzer/speed-limit all wired to
  `socket.sendCmd()`. New `config.toml [control]` table (deadband/centre-band/timeout/fault
  thresholds/invert/speed-limit-default), exposed via `GET /config`.
- Simulator: `--joystick-demo` (scripted centre→forward→turn→release→button-press pattern at
  50 Hz) and `--joystick-fault` (wild per-frame jump) flags, plus `--joystick-silent-after/-for`
  (mirrors `--rover-silent-after/-for`'s idiom) for testing the 200 ms timeout without touching
  HELLO/TELEM/SCAN/EVENT/ACK.
- New `tests/test_joystick.py` (7 end-to-end tests over a real simulator+app, same pattern as
  `test_cmd_heartbeat.py`) and `tests_js/test_keyboard.mjs` (pure `driveFromKeys()` unit tests).
  Full suite: 87 passed (pytest), 16 passed (node --test).
- Next GS: Phase 10 `ground_bridge` (needed for R3) once hardware/wiring for the physical
  thumbsticks is ready; Phase 7 (event log UI, filtering) is also open.

### 2026-10-22 — GS side: Phase 5 + 5b merged
- Command heartbeat is single-path (10 Hz, never resends stale commands).
- E-STOP sent immediately; `estop_reset` only accepted from the controlling tab.
- Reconnecting tabs return as viewers.
- Next GS: Phase 6 controls, then Phase 10 ground_bridge (needed for R3).

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
