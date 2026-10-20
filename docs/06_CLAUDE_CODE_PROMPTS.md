# 06 — Claude Code Prompt Sequence

Use one prompt per phase, in order, each in a **new conversation** started in plan mode (`/plan`).
Every prompt ends with an acceptance check — run it yourself before committing.
Copy the text inside the boxes as-is.

---

## Phase 0 — Orientation (no code)
```
Read @CLAUDE.md and every file in @docs/. Do not write any code yet.
1. Summarise the system in 10 bullet points so I can check you understood it.
2. List any contradictions or gaps you find between the docs.
3. List the questions you need answered before Phase 1.
```
✔ Check: the summary matches the docs; fix any gaps in the docs before moving on.

---

## Phase 1 — Scaffold + protocol models
```
Create the repository layout from docs/01_ARCHITECTURE.md section 3 (empty modules with docstrings
are fine except where stated). Add .gitignore (.venv, logs/, __pycache__, secrets.h), README.md
with run instructions, and ground_station/requirements.txt.

Implement ground_station/app/protocol.py: pydantic v2 models for every message in
docs/02_TELEMETRY_PROTOCOL.md (hello, telem, scan, event, cmd, ack), with:
- all hardware-dependent fields Optional (None allowed),
- unknown fields ignored,
- a parse_message(raw: str) function that returns the right model or raises a clear error.

Write tests/test_protocol.py using the exact JSON examples from docs/02, plus: a telem with
missing blocks, a telem with extra unknown fields, a BMP280 hello (hum null), invalid JSON.
Set up the .venv and run pytest.
```
✔ Check: `pytest -q` passes.

---

## Phase 2 — Fake rover simulator
```
Implement simulator/fake_rover.py: a WebSocket server on 127.0.0.1:8765 that behaves like the
real rover per docs/02:
- sends hello on connect and every 5 s, telem at 10 Hz, a sonar scan every 2 s, events when
  thresholds are crossed;
- realistic signals: battery slowly drains 12.6 -> 9.8 V, temperature drifts, lux changes,
  IMU noise, sonar distances from a simple fake room;
- obeys cmd: drive changes pwm, estop latches, estop_reset clears, and the 500 ms watchdog
  stops the motors and emits WD_STOP;
- CLI flags to toggle each hardware item: --bme280/--bmp280/--dht11, --encoders, --ina219,
  --camera, --lidar (lidar sends 360-point scans at 10 Hz), --lossy 5 (drop 5 % of packets).
Use the models from protocol.py so the simulator can never drift from the protocol.
Add tests that start the simulator, connect, and verify hello + telem arrive and the watchdog fires.
```
✔ Check: `python simulator/fake_rover.py --encoders --lidar` runs; tests pass.

---

## Phase 3 — Backend core
```
Implement the ground station backend:
- rover_link.py: async WebSocket client to --rover URL, auto-reconnect with backoff, sends cmd
  at 10 Hz as heartbeat, tracks link state OK/STALE/LOST, packet loss from seq gaps, RTT from acks.
- state.py: latest hello (capabilities), latest telem, ring-buffer history (5 min) per numeric field.
- logger.py: per-session folder logs/<YYYYMMDD_HHMMSS>/ with raw.jsonl (both directions + receive
  time) and telem.csv / events.csv.
- main.py + __main__.py: FastAPI app, `python -m ground_station.app --rover ws://127.0.0.1:8765`,
  serves web/ at http://localhost:8000, and /ws/ui that pushes a combined state snapshot at 10 Hz
  and accepts UI commands (drive, mode, servo, estop, estop_reset).
Thresholds go in ground_station/app/config.toml (values from docs/03 section 2).
Add tests with the simulator for reconnect and logging.
```
✔ Check: start simulator + backend; kill the simulator → backend shows LOST, restart → reconnects.

---

## Phase 4 — Dashboard layout + top bar
```
Build the frontend in ground_station/app/web/ (plain HTML/CSS/JS, no build step, no CDN — vendor any
library into web/vendor/). Implement the full grid layout from docs/03 section 1 with placeholder
cards, plus a fully working TOP BAR: link state, RSSI, RTT, loss %, mission clock, mode, battery,
REC indicator, E-STOP button (Space key).
Implement the hardware-absent rules from docs/03 ("NOT INSTALLED" card, "—" for null, grey + age
when LOST) as a reusable JS helper used by every panel. Dark theme, works at 1366x768.
```
✔ Check: run simulator with and without `--ina219`; the current widget switches between value and NOT INSTALLED.

---

## Phase 5 — Environment + Rover health panels
```
Implement the ENVIRONMENT and ROVER HEALTH panels from docs/03:
- environment: temp, hum, press, alt, lux with value, unit, 5-min sparkline, session min/max;
  handle BMP280 (no humidity) and DHT11 (no pressure) cases;
- health: motor L/R commanded vs rpm bars, roll/pitch attitude indicator, yaw compass,
  sonar distance + mini radar of the last scan, power (V, I, W, SoC trend), sys stats;
- colour thresholds from config.toml (served by the backend, not hard-coded in JS).
Use one vendored chart library (uPlot preferred for performance). Keep CPU low: redraw charts at
most 2 Hz.
```
✔ Check: run `--bmp280` and `--dht11` variants; nothing crashes, correct fields show "—"/NOT INSTALLED.

---

## Phase 6 — Control panel + safety
```
Implement the CONTROL panel from docs/03 section 3: WASD/arrow driving with a speed-limit slider,
Shift boost, mode selector, servo sweep/fixed, buzzer. Keys only act while the page is focused;
blur/close -> backend sends zero drive. E-STOP sends estop 3x 50 ms apart; reset requires a confirm.
Show watchdog state and last_cmd_age_ms. Write a test (simulator) proving: stop sending cmd ->
WD_STOP within 600 ms; estop latched ignores drive until estop_reset.
```
✔ Check: drive the simulator from the browser; close the tab → motors go to 0.

---

## Phase 7 — Recording, replay, export
```
Implement replay.py and `python -m ground_station.app --replay <raw.jsonl> [--speed 2]`, feeding the
UI exactly as a live rover would (controls disabled, "REPLAY" banner). Add an export button that
downloads the current session's CSVs as a zip, and an EVENT LOG panel with level filter.
```
✔ Check: record 2 minutes from the simulator, replay at 2× speed, charts look identical.

---

## Phase 8 — Video panel (works before the camera exists)
```
Implement video.py: backend proxies an MJPEG stream (URL from hello.hw.camera.url) to /video and
measures fps + frame age. Add a --camera mode to the simulator that serves a fake MJPEG stream
(OpenCV-generated frames with a moving pattern and timestamp) on http://127.0.0.1:8081/stream.
Frontend VIDEO panel: stream, overlay with heading + sonar distance + fps, STALE badge after 1 s,
NOT INSTALLED card when camera absent.
```
✔ Check: simulator with and without `--camera`.

---

## Phase 9 — Map panel stub (mapping stays on the back burner)
```
Implement only a MAP panel stub: a polar plot of the latest `scan` (sonar or lidar), rover arrow at
the centre, range rings every 50 cm. Create ground_station/app/mapping/__init__.py with an
interface (class Mapper: update(scan, pose) -> None; get_grid() -> numpy array | None) and a
NullMapper that does nothing. Do NOT implement SLAM.
```
✔ Check: `--lidar` shows a 360° outline of the fake room; without it, the sonar sweep shows.

---

## Phase 10 — Firmware: rover_main
```
Create firmware/rover_main as a PlatformIO project (board esp32doit-devkit-v1, Arduino framework,
ArduinoJson, a WebSocket server library). Follow docs/01 section 4 (driver interface + non-blocking
loop) and the pin table in docs/04 section 1.
Implement drivers: mpu6050 (complementary filter), bme280 with chip-ID detection (bme/bmp) and
dht11 fallback, bh1750, hc-sr04 + servo sweep producing scan messages, battery divider with
calibration constants, buzzer, tb6612 motors. Stub drivers that report present=false: encoders,
ina219, lidar. WiFi AP ROVER-AP at 192.168.4.1, WebSocket on port 81, hello/telem/scan/event exactly
per docs/02, and all four safety rules from docs/02 section 4.
secrets.h (gitignored) + secrets.example.h. Explain how to flash and monitor serial output.
```
✔ Check: flash, join ROVER-AP, run `python -m ground_station.app --rover ws://192.168.4.1:81`; dashboard shows real data.

---

## Phase 11 — Bench integration test
```
Write docs/07_BENCH_TEST.md: a step-by-step checklist to test the real rover on a stand (wheels in
the air): each sensor vs a reference, watchdog (turn laptop WiFi off -> motors stop), E-STOP, tilt
cut-off, battery calibration, WiFi range test at 5/10/20 m with RSSI and loss %. Include a results
table we can fill in for the course report.
```

---

## FUTURE hardware prompts (use when the part arrives — see docs/04)

**F1 – ESP32-CAM**
```
The ESP32-CAM has arrived. Following docs/04 section C, create firmware/rover_cam (PlatformIO,
AI-Thinker board), join ROVER-AP with static IP 192.168.4.2, serve /stream (QVGA MJPEG) and /status.
Update rover_main so hello.hw.camera.present reflects whether 192.168.4.2/status answers.
No changes to the dashboard should be needed — tell me if any are.
```

**F2 – Wheel encoders**
```
We fitted <LM393 optical / Hall> encoders with <N> counts per revolution on GPIO36/39. Following
docs/04 section D, implement the encoders driver (interrupts, debounce, RPM over 100 ms), odometry
(wheel radius <r> m, track width <b> m) and a per-wheel PID speed loop with a config flag to
enable it. Update the simulator if its encoder model differs.
```

**F3 – INA219**
```
INA219 fitted at I2C 0x40 with a <0.1/0.01> ohm shunt. Implement the driver per docs/04 section E,
fill pwr.ibat_a and pwr.p_w, and add mAh-used + runtime estimate in the ground station.
```

**F4 – LiDAR**
```
We have an <LD06/LD19> on UART2 RX GPIO16, mounted with a <deg> offset. Implement the lidar driver
per docs/04 section F (packet parse + CRC, 1-degree bins, one scan per revolution, src "lidar").
Measure the main loop rate before/after; if it drops below 80 Hz, propose moving lidar to ESP32 #2.
```

**F5 – Mapping (only when the team decides)**
```
/plan We want to start mapping. Using logged raw.jsonl files in logs/ (lidar scans + odom), compare
3 approaches (occupancy grid with odometry only, ICP scan matching, BreezySLAM) for our hardware.
Recommend one, then implement it behind the Mapper interface in ground_station/app/mapping/.
```

---

## Utility prompts (any time)

**Protocol change**
```
I want to add <field> to <message>. Update docs/02, protocol.py, fake_rover.py, the firmware
driver and tests together, per the rule in CLAUDE.md. Show me the diff of docs/02 first.
```

**Code review before a commit**
```
Review the uncommitted changes against CLAUDE.md rules and docs/02. List problems by severity.
Don't change code until I confirm.
```

**Debugging**
```
<paste the error / serial log>. Explain the likely cause, how to confirm it, then propose a fix.
```
