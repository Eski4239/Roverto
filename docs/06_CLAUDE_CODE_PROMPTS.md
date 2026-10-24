# 06 — Claude Prompt Sequence

Works in **Claude Code** (VS Code, repo open — it reads CLAUDE.md automatically) and in **Claude chat**
(Pro) inside a Claude Project that has `docs/TEAM_BRIEF.md` as knowledge. In chat, Claude can't run
anything: ask for complete files, paste them into the repo, run the checks yourself, paste errors back.

One prompt per phase, each in a **new conversation**. In Claude Code start with `/plan`.
Every prompt ends with a check — run it before committing.

## Two parallel tracks
- **Track A – Python ground station:** Phases 1–9 (works fully with the simulator, no hardware).
- **Track B – Firmware:** Phases 10–11. Can start as soon as Phase 1 is merged (the wire protocol is
  then frozen and golden-tested on the Python side).

---

## Phase 0 — Orientation (no code)
```
Read CLAUDE.md, every file in docs/ and firmware/common/rover_protocol.h. Do not write code yet.
1. Summarise the system in 10 bullet points so I can check you understood it.
2. List contradictions or gaps between the docs.
3. List the questions you need answered before Phase 1.
```
✔ Check: summary matches the docs; fix gaps in the docs first.

---

## Phase 1 — Scaffold + protocol + wire codec   (Track A, unblocks Track B)
```
Create the repository layout from docs/01 §4 (empty modules with docstrings are fine unless stated),
.gitignore (.venv, logs/, __pycache__, **/secrets.h, .pio/), README run instructions, and
ground_station/requirements.txt (fastapi, uvicorn, pydantic>=2, pyserial, cobs, numpy, pytest).

1. protocol.py: pydantic v2 models for the logical messages in docs/02 §2–3 (hello, telem, scan,
   event, ack, cmd) — hardware-dependent fields Optional, unknown fields ignored.
2. wire.py: encode/decode between the binary structs in firmware/common/rover_protocol.h and those
   models, using the struct formats in docs/02 §4 (assert sizes). NaN <-> None, 0xFFFF <-> None,
   hw_present bitmask <-> hello.hw, enums <-> strings. Scan fragment reassembly by scan_id with a
   300 ms timeout. Serial framing: COBS + CRC-16/CCITT-FALSE exactly as docs/02 §4.
3. tests: round-trip every message type; the JSON examples from docs/02 must survive
   model -> bytes -> model; corrupted CRC and bad magic are rejected without exceptions escaping;
   lidar scan in 4 fragments reassembles; a missing fragment yields nulls.
   Golden tests: every tests/golden/*.hex decodes to tests/golden/expected.json (float tol 1e-4)
   and re-encodes to identical bytes; serial_frame_telem.hex passes COBS + CRC. Apply the decisions
   in docs/02 §6.
Set up .venv and run pytest.
```
✔ Check: `pytest -q` green.

---

## Phase 2 — Fake rover simulator
```
Implement simulator/fake_rover.py: a TCP server on 127.0.0.1:8765 that emits EXACTLY the serial
byte stream the ground_bridge would (docs/02 §4: SK_RX_FROM_ROVER frames with a fake RSSI, plus
SK_BRIDGE_STATUS at 1 Hz) and accepts SK_TX_TO_ROVER frames carrying CmdMsg. Use wire.py.
Behaviour like the real rover (docs/02): HELLO on start/every 5 s/on request, TELEM 10 Hz, sonar
SCAN every 2 s, EVENTs on thresholds; battery drains 12.6 -> 9.8 V, temperature drifts, IMU noise,
sonar distances from a simple fake room. Obeys CmdMsg incl. estop latch/reset and the 500 ms watchdog.
Flags: --bme280/--bmp280/--dht11, --encoders, --ina219, --lidar (4-fragment 360-pt scans at 10 Hz),
--lossy N (drop N % of frames), --rssi -70.
Tests: connect, receive HELLO + TELEM, watchdog fires when CmdMsg stops.
```
✔ Check: `python simulator/fake_rover.py --encoders --lidar` runs; tests pass.

---

## Phase 3 — Backend core
```
Implement:
- link.py: pyserial serial_for_url(--link) so "COM5", "/dev/ttyUSB0" and "socket://127.0.0.1:8765"
  all work; reader thread -> asyncio queue; COBS frame splitting; auto-reopen if the port disappears
  (state NO_BRIDGE); sends CmdMsg at 10 Hz (the heartbeat) via SK_TX_TO_ROVER.
  `--link auto` picks the first USB serial port that sends valid BRIDGE_STATUS frames.
- state.py: latest hello, telem, scan; link block from docs/02 §3.2 (OK/STALE/LOST/NO_BRIDGE,
  rx_hz, loss % from seq gaps, RTT from acks, both RSSIs, bridge tx_fail); 5-min ring buffers.
- logger.py: logs/<YYYYMMDD_HHMMSS>/ raw.jsonl (decoded logical messages both directions + laptop
  time), raw.bin (raw serial bytes), telem.csv, events.csv.
- main.py/__main__.py: `python -m ground_station.app --link ...`, serve web/ at
  http://localhost:8000, /ws/ui pushes a combined snapshot at 10 Hz, accepts UI commands.
- config.toml: thresholds from docs/03 §2, camera_url, serial baud 921600.
Tests with the simulator: reconnect after the simulator restarts; logs are written.
```
✔ Check: kill the simulator → LOST; restart → OK again without restarting the backend.

---

## Phase 4 — Dashboard layout + top bar
```
Build ground_station/app/web/ (plain HTML/CSS/JS, no build step, no CDN — vendor uPlot into
web/vendor/). Full grid from docs/03 §1 with placeholder cards and a working TOP BAR (link state,
serial port, both RSSIs, RTT, loss, mission clock, mode, battery, REC, E-STOP on Space).
NO_BRIDGE shows "Plug in ground bridge" + port picker. Implement the hardware-absent rules from
docs/03 as one reusable JS helper used by every panel. Dark theme, 1366x768.
```
✔ Check: simulator with/without `--ina219` → current widget switches value ↔ NOT INSTALLED.

---

## Phase 5 — Environment + Rover health panels
```
Implement ENVIRONMENT and ROVER HEALTH from docs/03: env values + 5-min sparklines + session min/max
(handle bmp280 = no humidity, dht11 = no pressure); motor cmd vs rpm bars, attitude indicator, yaw
compass, sonar distance + mini radar, power (V, I, W, SoC trend), sys stats. Thresholds come from
config.toml via the backend. Redraw charts at most 2 Hz.
```
✔ Check: `--bmp280` and `--dht11` runs show "—"/NOT INSTALLED correctly, nothing crashes.

---

## Phase 6 — Control + safety
```
Implement CONTROL from docs/03 §3: WASD/arrows, speed limit, Shift boost, mode, servo sweep/fixed,
buzzer. Keys act only while the page is focused; blur/close -> drive 0. E-STOP sets the estop flag
on the next 3 CmdMsgs immediately (don't wait for the 10 Hz tick); reset needs a confirm.
Show wd_ok and last_cmd_age_ms. Simulator tests: stop CmdMsg -> WD_STOP within 600 ms; estop
latched ignores drive until estop_reset.
(Once Phase 10 lands, SK_JOYSTICK is another input source feeding this same CmdMsg-generation path
alongside WASD — no behavior to build yet, just merge both sources when that revisit happens.)
```
✔ Check: drive the simulator from the browser; close the tab → motors 0.

---

## Phase 7 — Recording, replay, export
```
replay.py + `python -m ground_station.app --replay logs/<ts>/raw.jsonl [--speed 2]` feeding the UI
like a live rover (controls disabled, REPLAY banner). Export button (zip of the session CSVs).
EVENT LOG panel with level filter.
```
✔ Check: record 2 min, replay at 2× → identical charts.

---

## Phase 8 — Video panel (before the camera exists)
```
video.py: proxy MJPEG from config camera_url to /video, measure fps and frame age, probe
camera_url/status every 5 s to fill hello.hw.camera. Simulator flag --camera serves a fake MJPEG
stream (OpenCV frames, moving pattern + timestamp) on http://127.0.0.1:8081/stream.
VIDEO panel: stream + overlay (heading, sonar distance, fps), STALE after 1 s, NOT INSTALLED card.
```
✔ Check: works with and without `--camera`.

---

## Phase 9 — Map panel stub
```
MAP panel stub only: polar plot of the latest scan (sonar or lidar), rover arrow, range rings every
50 cm. mapping/__init__.py with class Mapper (update(scan, pose); get_grid() -> ndarray|None) and a
NullMapper. Do NOT implement SLAM.
```
✔ Check: `--lidar` shows the fake room outline; without it the sonar sweep.

---

## Phase 10 — Firmware: ground_bridge   (Track B)
```
Create firmware/ground_bridge as a PlatformIO project (board esp32doit-devkit-v1, Arduino framework
arduino-esp32 3.x, PacketSerial). Include ../common/rover_protocol.h (add build_flags -I).
Follow docs/01 §2 and §5.2 and docs/02 §4 exactly:
- WIFI_STA, not connected, esp_wifi_set_channel(ESPNOW_CHANNEL); add rover peer from secrets.h
  (PEER_MAC, optional PMK/LMK); print own MAC at boot.
- Serial 921600: COBS frames; SK_TX_TO_ROVER -> CRC check -> esp_now_send to the rover.
- ESP-NOW RX callback (new esp_now_recv_info_t signature) -> copy bytes + rx_ctrl->rssi into a
  FreeRTOS queue; loop() emits SK_RX_FROM_ROVER frames. Ignore frames from unknown MACs.
- SK_BRIDGE_STATUS at 1 Hz; LED GPIO2 blinks on RX; SK_BRIDGE_LOG for debug text.
- Read the two joystick modules per docs/04 §1b: analogRead on the four VRx/VRy pins, digitalRead
  (INPUT_PULLUP) on the two SW pins; emit SK_JOYSTICK frames (JoystickState) at 50 Hz.
- The bridge must NOT decode telemetry or generate commands — this applies to joystick input too:
  it only reports raw stick state, never computes drive values.
secrets.example.h committed, secrets.h gitignored. Explain flashing and how to find each board's MAC.
Also write tools/bridge_echo_test.py: opens the port, checks BRIDGE_STATUS arrives and CRCs are valid.
```
✔ Check: bridge plugged in → `python tools/bridge_echo_test.py COM5` passes; dashboard shows "LOST" (not NO_BRIDGE).

Before rover_main (Phase 11) exists, `tools/espnow_beacon` is a temporary PlatformIO sketch for a
second ESP32 that stands in for the rover: it sends golden HelloMsg/TelemMsg to the bridge's MAC,
prints any CmdMsg it receives, and replies with AckMsg. Flash it, test the bridge end-to-end, then
reflash rover_main once it's ready — see `tools/espnow_beacon/README.md`.

---

## Phase 11 — Firmware: rover_main   (Track B)
```
Create firmware/rover_main (PlatformIO, esp32doit-devkit-v1, Arduino 3.x) including
../common/rover_protocol.h. Follow docs/01 §5.1 (driver interface, non-blocking loop) and the pin
table in docs/04 §1. ESP-NOW like the bridge (same channel, bridge MAC as peer).
Drivers: mpu6050 (complementary filter), env with chip-ID detection (bme280/bmp280) + dht11 fallback,
bh1750, hc-sr04 + SG90 sweep -> ScanMsg, battery divider with calibration constants, buzzer, tb6612.
Stub drivers reporting present=false with NaN fields: encoders, ina219, lidar.
Send HelloMsg/TelemMsg/ScanMsg/EventMsg/AckMsg exactly per docs/02; enforce all five safety rules
in docs/02 §5. Serial command "dump_golden" prints hex of a fixed TelemMsg and CmdMsg for
tests/golden/. Explain flashing, pairing (MACs into secrets.h) and serial monitoring.
```
✔ Check: rover on, bridge plugged in, `python -m ground_station.app --link auto` → real data on the dashboard; unplug the bridge → wheels stop within 0.5 s.

---

## Phase 12 — Bench test
```
Write docs/07_BENCH_TEST.md: checklist for the rover on a stand (wheels in the air): each sensor vs
a reference, watchdog (unplug bridge -> motors stop), E-STOP, tilt cut-off, battery calibration,
ESP-NOW range test at 5/10/20/50 m (normal vs Long-Range mode) recording RSSI and loss %.
Include result tables for the course report.
```

---

## FUTURE hardware prompts (when the part arrives — docs/04)

**F1 – ESP32-CAM**
```
The ESP32-CAM arrived. Per docs/04 §C create firmware/rover_cam (AI-Thinker): WiFi AP ROVER-CAM on
channel 1, 192.168.4.1, /stream (QVGA MJPEG) and /status. The ground station already probes
camera_url — tell me if anything else needs changing.
```
**F2 – Wheel encoders**
```
We fitted <LM393 optical / Hall> encoders, <N> counts/rev, on GPIO36/39. Per docs/04 §D implement the
encoders driver (interrupts, debounce, RPM over 100 ms), odometry (wheel radius <r> m, track
<b> m), optional per-wheel PID behind a config flag. Set HW_ENCODERS and encoder_cpr in HELLO.
```
**F3 – INA219**
```
INA219 at 0x40 with a <0.1/0.01> ohm shunt. Per docs/04 §E fill ibat_a/p_w, set HW_CURRENT, and add
mAh used + runtime estimate in the ground station.
```
**F4 – LiDAR**
```
<LD06/LD19> on UART2 RX GPIO16, mounted with <deg> offset. Per docs/04 §F parse packets + CRC,
1-degree bins, 4 ScanMsg fragments per revolution (src SCAN_LIDAR). Measure loop_hz before/after;
if < 80 Hz move parsing to a FreeRTOS task on core 0.
```
**F5 – Mapping (only when the team decides)**
```
We want to start mapping. Using logs/*/raw.jsonl (lidar scans + odom), compare occupancy grid from
odometry, ICP scan matching and BreezySLAM for our hardware; recommend one and implement it behind
the Mapper interface.
```

## Utility prompts
**Protocol change**
```
Add <field> to <message>. Update docs/02, rover_protocol.h (keep <= 250 B, update static_asserts),
wire.py, protocol.py, fake_rover.py, firmware drivers and golden tests together. Show the docs/02
diff first.
```
**Review before commit**
```
Review the uncommitted changes against CLAUDE.md rules and docs/02. List problems by severity; don't
change code until I confirm.
```
**Debug**
```
<paste error / serial log>. Explain the likely cause, how to confirm it, then propose a fix.
```
