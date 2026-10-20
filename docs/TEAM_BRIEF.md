# Rover Project — Team Brief (all-in-one context for Claude)

> **What this is:** every design decision, the protocol, the pin plan, the hardware roadmap and the build
> prompts for our Space Vehicles & Missiles rover, in one file. Give it to Claude so it has full
> context before writing any Arduino (ESP32) or Python code.
> Generated from the repo files on 2026-10-20 by `tools/build_brief.py`. If you change a doc in the repo, regenerate this
> file (or just tell Claude which section changed).

## How to use this with Claude Pro

**Option A — Claude chat (claude.ai / desktop app)**
1. Create a new **Project** called "Rover firmware + ground station".
2. Upload this file (`TEAM_BRIEF.md`) to the project's **knowledge**. Also upload
   `firmware/common/rover_protocol.h` (it's also copied in §6 below).
3. Paste this into the project's **custom instructions**:
   ```
   You are helping build the firmware (ESP32, Arduino framework via PlatformIO) and the Python ground
   station for our university rover. TEAM_BRIEF.md is the source of truth: follow its "Hard rules",
   protocol and pin plan exactly. Never invent protocol fields; if something is missing or
   contradictory, ask first. Give complete files with their repo path, not fragments. Keep all
   safety rules (500 ms watchdog, E-STOP latch, tilt and battery limits).
   ```
4. Start each phase in a new chat using the prompts in §8 (Phase 0 first).
   Chat Claude can't run code: paste its files into the repo, run the check, paste errors back.

**Option B — Claude Code in VS Code (recommended for writing code)**
Clone the repo; Claude Code reads `CLAUDE.md` automatically, and the prompts in §8 work as-is. Setup in §7.

## Current status & decisions (2026-10-20)
| Topic | Decision |
|-------|----------|
| Rover controller | ESP32 DevKit V1 #1 ("rover_main") |
| Telemetry link | **ESP-NOW** between rover_main and ESP32 DevKit V1 #2 ("ground_bridge") plugged into the laptop via USB serial |
| Data format | Logical JSON (agreed) on the laptop; compact binary structs on the radio (ESP-NOW frames ≤ 250 B) |
| Env sensor | BME280 being fitted now (verify it isn't a BMP280); DHT11 kept as fallback |
| Video | Future ESP32-CAM, own WiFi AP; not through the bridge |
| Encoders, INA219, LiDAR | Future — software must already support them (fields exist, UI shows "NOT INSTALLED") |
| Mapping / navigation | Back burner. LiDAR is the likely sensor. Keep SCAN message + map stub only |
| Language | Python 3.12 ground station; C++ (Arduino) firmware |

## Contents
1. CLAUDE.md — hard rules, stack, commands
2. Architecture (docs/01)
3. Protocol (docs/02)
4. Dashboard spec (docs/03)
5. Hardware roadmap + pin plan (docs/04)
6. firmware/common/rover_protocol.h
7. VS Code + Claude Code setup (docs/05)
8. Build prompts (docs/06)

---



# §1. CLAUDE.md  (`CLAUDE.md`)

## Rover Ground Station — project memory for Claude

University project (Space Vehicles & Missiles, Universidad Europea, Year 3).
A small ESP32 rover + a **ground station** on any laptop. Telemetry and commands travel over
**ESP-NOW** between the rover's ESP32 and a second ESP32 ("ground_bridge") plugged into the laptop by
USB. Video (future) comes from an ESP32-CAM over its own WiFi access point.

Read before doing any work:
- `docs/01_ARCHITECTURE.md` — system, links, folder layout, firmware structure
- `docs/02_TELEMETRY_PROTOCOL.md` — **single source of truth** for every message (logical JSON, binary wire, serial framing)
- `firmware/common/rover_protocol.h` — the C structs of the wire protocol
- `docs/03_DASHBOARD_SPEC.md` — panels, behaviour, "not installed" states
- `docs/04_FUTURE_HARDWARE.md` — pin plan + hardware we don't have yet (software must be ready for it)
- `docs/06_CLAUDE_CODE_PROMPTS.md` — the build sequence we follow
- `docs/PROGRESS_ROVER_MAIN.md` — rover_main progress, design decisions (PROPOSED/AGREED) and open
  questions; check its "GS impact" items before changing anything that talks to the rover

### Hard rules
1. **Protocol first.** A field change updates, in one commit: `docs/02`, `rover_protocol.h`,
   `ground_station/app/wire.py`, `ground_station/app/protocol.py`, `simulator/fake_rover.py`, the
   firmware drivers (`firmware/rover_main`), and the golden files (`tools/golden_gen.cpp` → `tests/golden/`).
   `firmware/common/` and `docs/02` are shared ground: change them only via a reviewed pull request.
   Every wire message must stay ≤ 250 bytes (`static_assert`).
2. **Hardware is optional.** Missing hardware → `NaN` on the wire → `null` in JSON → "NOT INSTALLED" or
   "—" in the UI. Never fake zeros, never crash. HELLO `hw_present` says what exists.
3. **Safety is never removed.** rover_main stops the motors if no valid CmdMsg for 500 ms; E-STOP latches;
   tilt and low-battery limits. The dashboard E-STOP is always visible. Don't weaken these "temporarily".
4. **The bridge stays dumb.** ground_bridge forwards bytes, adds RSSI and status. It never decodes
   telemetry and never generates commands, so protocol changes don't require re-flashing it.
5. **Simulator parity.** `simulator/fake_rover.py` emits the exact serial byte stream of the bridge over
   TCP, with flags to enable/disable each hardware item.
6. **Mapping/navigation is on the back burner.** Keep the map panel and SCAN message; no SLAM until asked.
7. Must run on Windows, macOS, Linux. `pathlib`, no absolute paths. The laptop may be offline →
   vendor all frontend libraries locally.
8. **Dependency reminder.** Whenever you add, remove or change anything in
   `ground_station/requirements.txt`, end your reply with a clearly visible line:
   "⚠ requirements.txt changed — everyone must run `pip install -r ground_station/requirements.txt`
   after pulling." Run that install yourself in the .venv before running tests.

### Stack
- Ground station: Python 3.12, FastAPI + uvicorn, pydantic v2, pyserial, cobs, numpy, pytest.
- Frontend: plain HTML/CSS/JS in `ground_station/app/web/` (no build step), uPlot vendored.
- Firmware: PlatformIO + Arduino framework (arduino-esp32 3.x), libraries: ArduinoJson (debug only),
  PacketSerial (bridge), Adafruit BME280, BH1750, MPU6050 (or own I2C code), ESP32Servo.
  Projects: `firmware/rover_main`, `firmware/ground_bridge`, `firmware/rover_cam` (future).
  Each has `include/secrets.h` (gitignored: PEER_MAC, ESPNOW_CHANNEL, optional PMK/LMK) and a committed
  `secrets.example.h`. Both include `../common/rover_protocol.h`.

### Commands
- Setup: `py -3.12 -m venv .venv` → `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate`
- Install: `pip install -r ground_station/requirements.txt`
- Simulator: `python simulator/fake_rover.py [--encoders --ina219 --lidar --camera --bmp280 --lossy 5]`
- Ground station (sim): `python -m ground_station.app --link socket://127.0.0.1:8765`
- Ground station (real): `python -m ground_station.app --link COM5` (Windows) / `--link /dev/ttyUSB0`
- Tests: `pytest -q`
- Firmware: `pio run -d firmware/rover_main -t upload` · `pio device monitor -b 115200`

### Style
- Small modules, type hints, docstrings on public functions; units in field names.
- Firmware: no `delay()` in loop, no `String` in hot paths, no heavy work in ESP-NOW callbacks.
- One feature per commit, imperative messages.
- When unsure about hardware behaviour, ask instead of guessing.

---


# §2. Architecture  (`docs/01_ARCHITECTURE.md`)

## 01 — System Architecture

### 1. Overview

```
 ┌──────────────────── ROVER ────────────────────┐                ┌─────────────────── LAPTOP (ground station) ───────────────────┐
 │                                               │                │                                                               │
 │  ESP32 #1 "rover_main"                        │    ESP-NOW     │  ESP32 #2 "ground_bridge"   USB serial    Python backend      │
 │   ├─ TB6612FNG → 2× TT motors                 │  2.4 GHz radio │   (plugged into laptop)    921600 baud    (FastAPI)           │
 │   ├─ MPU-6050 IMU            (I2C)            │◄──────────────►│   transparent forwarder  ◄────────────►  ├─ link   (pyserial)  │
 │   ├─ BME280 temp/hum/press   (I2C)            │  binary msgs   │   + RSSI + link stats     COBS frames    ├─ wire   (binary↔model)
 │   ├─ BH1750 light            (I2C)            │  ≤ 250 B each  │                                          ├─ protocol (pydantic)│
 │   ├─ HC-SR04 on SG90 servo   (sweep)          │                │                                          ├─ state / logger     │
 │   ├─ Battery voltage divider (ADC1)           │                │                                          ├─ video  [later]     │
 │   ├─ Buzzer                                   │                │                                          ├─ mapping [stub]     │
 │   ├─ [FUTURE] wheel encoders                  │                │                                          └─ web UI localhost:8000
 │   ├─ [FUTURE] INA219 current sensor           │                │                                                               │
 │   └─ [FUTURE] LiDAR (UART2)                   │                │  Browser dashboard (any OS)                                   │
 │                                               │   WiFi (HTTP)  │                                                               │
 │  ESP32-CAM "rover_cam" [FUTURE]               │◄──────────────►│  laptop WiFi joins "ROVER-CAM" only when video is needed      │
 │   └─ own WiFi AP "ROVER-CAM", MJPEG stream    │  MJPEG video   │                                                               │
 └───────────────────────────────────────────────┘                └───────────────────────────────────────────────────────────────┘
```

Two independent links:
1. **Telemetry + commands**: rover_main ⇄ ESP-NOW ⇄ ground_bridge ⇄ USB ⇄ Python. Works without any
   WiFi network; the laptop keeps its normal WiFi/internet.
2. **Video** (future): ESP32-CAM runs its own WiFi access point; the laptop joins it to receive MJPEG.
   ESP-NOW frames are far too small for video, so the camera never goes through the bridge.

### 2. Link details

#### 2.1 ESP-NOW (rover_main ⇄ ground_bridge)
- Peer-to-peer, connectionless, no router. Both boards in `WIFI_STA` mode, **not** connected to any AP,
  on a fixed channel (default **channel 11**, in `secrets.h`). The ESP32-CAM AP uses a different
  channel (default **1**) to reduce interference.
- Pairing: each board prints its MAC at boot; put the other board's MAC in its `secrets.h`
  (`PEER_MAC`). Optional: ESP-NOW encryption (PMK/LMK in `secrets.h`) so nobody else can drive the rover.
- Payload limit **250 bytes** per frame → compact binary structs (`firmware/common/rover_protocol.h`).
  Lidar scans are fragmented into ≤100-point parts.
- Optional range boost: Espressif Long-Range mode (`WIFI_PROTOCOL_LR`) on **both** boards; lower data
  rate but enough for our ~2 KB/s telemetry. Measure range in the bench test before relying on it.
- Delivery: ESP-NOW reports per-frame send success (MAC-level ACK). We do **not** retransmit
  telemetry (fresh data beats old data); commands are re-sent every 100 ms anyway.

#### 2.2 USB serial (ground_bridge ⇄ laptop)
- 921600 baud, 8N1 (fallback 460800 if the USB chip complains).
- Frames: `COBS(kind | rssi | payload | crc16)` + `0x00` delimiter (see docs/02 §4).
- The bridge is **transparent**: it does not decode telemetry, so protocol changes never require
  re-flashing it. It only adds RX RSSI and sends a 1 Hz `BridgeStatus`.

#### 2.3 Rates & bandwidth
| Message | Direction | Rate | Bytes | Load |
|---------|-----------|------|-------|------|
| TELEM   | rover → GS | 10 Hz | 129 | 1.3 KB/s |
| SCAN sonar | rover → GS | ~0.5 Hz | ~70 | tiny |
| SCAN lidar (future) | rover → GS | 10 Hz × 4 parts | 231 | 9 KB/s |
| HELLO | rover → GS | 0.2 Hz | 38 | tiny |
| CMD | GS → rover | 10 Hz | 30 | 0.3 KB/s |
| Video (future) | cam → laptop | 10–15 fps | 8–15 KB/frame | ≤ 200 KB/s over WiFi |

### 3. Logical vs. wire protocol
- **Wire protocol** = binary C structs on the radio (`rover_protocol.h`, mirrored in Python `wire.py`).
- **Logical protocol** = the JSON messages in docs/02 §2–3. Python decodes every binary frame into
  these pydantic models immediately. Everything above the link layer (state, logging, UI, simulator
  tests, future mapping) only sees the logical JSON. `NaN` on the wire → `null` in JSON.

### 4. Repository layout

```
rover-software/
├─ CLAUDE.md
├─ README.md
├─ docs/                         ← planning docs + TEAM_BRIEF.md
├─ ground_station/
│  ├─ requirements.txt           ← fastapi, uvicorn, pydantic, pyserial, cobs, numpy, pytest
│  └─ app/
│     ├─ __main__.py             ← python -m ground_station.app --link <url>
│     ├─ main.py                 ← FastAPI app, routes, /ws/ui
│     ├─ protocol.py             ← pydantic models = logical protocol (docs/02 §2–3)
│     ├─ wire.py                 ← binary structs ↔ models, COBS + CRC16 framing
│     ├─ link.py                 ← pyserial serial_for_url(): "COM5", "/dev/ttyUSB0" or "socket://127.0.0.1:8765"
│     ├─ state.py                ← latest values, capabilities, 5-min history
│     ├─ logger.py               ← logs/<YYYYMMDD_HHMMSS>/raw.jsonl + telem.csv + events.csv + raw.bin
│     ├─ replay.py
│     ├─ config.toml             ← thresholds, serial port, camera URL, wheel geometry
│     ├─ video.py                ← [later]
│     ├─ mapping/                ← [stub interface only]
│     └─ web/                    ← index.html, css/, js/, vendor/ (offline chart lib)
├─ simulator/
│  └─ fake_rover.py              ← TCP server on 127.0.0.1:8765 emitting the SAME byte stream as the bridge
├─ firmware/
│  ├─ common/rover_protocol.h    ← the one C definition of the wire protocol
│  ├─ rover_main/                ← PlatformIO, ESP32 DevKit V1 on the rover
│  ├─ ground_bridge/             ← PlatformIO, ESP32 DevKit V1 on the laptop
│  └─ rover_cam/                 ← PlatformIO, ESP32-CAM [future]
├─ tests/
└─ logs/                         ← gitignored
```

The simulator speaks the bridge's serial byte stream over TCP, so `link.py` uses identical code for
real hardware (`--link COM5`) and simulation (`--link socket://127.0.0.1:8765`) — pyserial's
`serial_for_url` handles both. This also means the binary codec is tested on every simulator run.

### 5. Firmware structure

#### 5.1 rover_main
Each hardware item is a **driver module** with the same interface; missing hardware is a driver
that reports `present=false` and leaves its fields `NaN`:

```cpp
struct Driver {
  const char* name;            // "bme280", "encoders", ...
  bool present = false;        // set by begin()
  virtual bool begin() = 0;    // false if hardware not detected
  virtual void update() = 0;   // called from loop at its own rate
  virtual void fill(TelemMsg& t) = 0;  // write fields, or leave NaN if !present
};
```

Non-blocking loop (`millis()`-based, no `delay()`):
- 100 Hz: motor output, watchdog, (future) encoder RPM
- 50 Hz: IMU read + complementary filter
- 10 Hz: build + send TELEM
- 1 Hz: BME280, BH1750, battery, sys stats; HELLO every 5 s
- ~60 ms: servo step + HC-SR04 ping → SCAN when the sweep completes
- ESP-NOW receive callback only copies the CmdMsg into a buffer + timestamp; logic runs in loop().

#### 5.2 ground_bridge
- Serial RX → COBS decode → CRC check → `esp_now_send(rover_mac, payload)`.
- ESP-NOW RX callback → push `(rssi, bytes)` into a FreeRTOS queue → loop COBS-encodes to serial.
- 1 Hz `BridgeStatus`. Onboard LED (GPIO2) blinks on RX. Never invents commands.

### 6. Power notes that affect software
- Battery 3S Li-ion 9.0–12.6 V → divider 100 kΩ / 33 kΩ → ≤ 3.13 V on **GPIO34 (ADC1)**.
  (ADC2 pins are unusable while the radio is on.) Calibrate against a multimeter at 2–3 points.
- SoC from a Li-ion lookup table, low-pass filtered.
- Radio TX + motor start can brown out the ESP32 → `reset_reason` in HELLO; dashboard flags brownouts.
- The ground_bridge is powered by the laptop USB — no battery concerns.

---


# §3. Protocol  (`docs/02_TELEMETRY_PROTOCOL.md`)

## 02 — Telemetry & Command Protocol (v1)

**Single source of truth.** Three layers:

| Layer | Where | Defined in |
|-------|-------|-----------|
| Logical (JSON) | Python state, logs, UI, tests | §2–3 of this file + `ground_station/app/protocol.py` |
| Wire (binary, ESP-NOW) | rover_main ⇄ ground_bridge | `firmware/common/rover_protocol.h` + `ground_station/app/wire.py` |
| Serial framing (USB) | ground_bridge ⇄ laptop | §4 of this file |

A field change must update **all of**: this file, `rover_protocol.h`, `wire.py`, `protocol.py`,
`simulator/fake_rover.py`, the firmware drivers that fill/read the field, and the golden files
(`tools/golden_gen.cpp` → `tests/golden/`) — in one commit.

### 1. Conventions
- Wire: little-endian, packed, ≤ 250 bytes per message, header `MsgHeader` (magic `0xA7`, ver, type,
  flags, seq u16, t_ms u32).
- `NaN` (wire) ⇔ `null` (JSON) = no data / hardware not installed. **Never send fake 0.**
- Distances in arrays: `0xFFFF` (wire) ⇔ `null` (JSON).
- `seq` per sender, +1 per message, wraps at 65535 → packet loss detection.
- Unknown JSON fields are ignored; unknown wire `type` is logged and dropped.

### 2. Rover → Ground station (logical JSON)

#### 2.1 `hello` — on boot, every 5 s, and when requested
Tells the dashboard **which hardware exists**. Wire: `HelloMsg` (`hw_present` bitmask).

```json
{"v":1,"type":"hello","t":120,"seq":0,
 "fw":"rover_main 0.1.0","reset_reason":"POWERON",
 "hw":{
   "imu":      {"present":true,  "model":"mpu6050"},
   "env":      {"present":true,  "model":"bme280"},
   "light":    {"present":true,  "model":"bh1750"},
   "sonar":    {"present":true,  "model":"hc-sr04", "servo":true},
   "battery":  {"present":true,  "cells":3},
   "current":  {"present":false, "model":"ina219"},
   "encoders": {"present":false, "cpr":0},
   "lidar":    {"present":false, "model":null},
   "buzzer":   {"present":true},
   "camera":   {"present":false, "url":"http://192.168.4.1/stream"}
 }}
```
- `env.model` comes from the chip ID: `0x60` = bme280 (has humidity), `0x58` = **bmp280 (no humidity)**,
  or dht11 fallback (no pressure). The UI adapts.
- `camera` is **not** sent by the rover (the camera is on a separate WiFi link). The ground station
  fills it by probing `camera_url` from `config.toml` every 5 s.

#### 2.2 `telem` — 10 Hz. Wire: `TelemMsg` (129 B)

```json
{"v":1,"type":"telem","t":12345,"seq":88,
 "env":   {"temp_c":22.4, "hum_pct":41.0, "press_hpa":1012.3, "alt_m":0.4},
 "light": {"lux":340},
 "pwr":   {"vbat_v":11.42, "soc_pct":71, "ibat_a":null, "p_w":null},
 "mot":   {"pwm_l":180, "pwm_r":175, "rpm_l":null, "rpm_r":null},
 "odom":  {"x_m":null, "y_m":null, "dist_m":null},
 "imu":   {"roll_deg":1.2, "pitch_deg":-0.4, "yaw_deg":87.5,
           "ax_g":0.01, "ay_g":-0.02, "az_g":1.00, "gz_dps":0.3, "temp_c":31.2},
 "sonar": {"angle_deg":45, "dist_cm":63},
 "state": {"mode":"manual", "estop":false, "wd_ok":true, "last_cmd_age_ms":40},
 "sys":   {"rssi_dbm":-61, "heap_b":182000, "uptime_s":340, "loop_hz":98, "chip_temp_c":48}}
```

| Block | Source | Notes |
|-------|--------|-------|
| env | BME280 now | `alt_m` relative to pressure at boot |
| light | BH1750 | |
| pwr | divider now, INA219 future | `ibat_a`, `p_w` null until INA219 |
| mot | TB6612 commands; encoders future | `pwm` −255…255, sign = direction; `rpm` null until encoders |
| odom | encoders + IMU yaw, future | null until encoders |
| imu | MPU-6050 | yaw drifts (no magnetometer) — expected |
| sonar | HC-SR04 on servo | latest ping; full sweep in `scan` |
| state | firmware | mode: idle·manual·assisted·auto |
| sys | ESP32 | `rssi_dbm` = signal of our commands as received by the rover |

#### 2.3 `scan` — one complete sweep / revolution. Wire: `ScanMsg`, fragmented
```json
{"v":1,"type":"scan","t":13000,"seq":95,"src":"sonar","scan_id":12,
 "pose":{"x_m":null,"y_m":null,"yaw_deg":87.5},
 "pts":[[0,120],[10,118],[20,null]]}
```
- `pts` = `[angle_deg, dist_cm]`, rover frame, 0° = front, counter-clockwise positive.
- Wire: up to 100 points per fragment (`part`/`parts`, same `scan_id`). Python reassembles; if a
  fragment is missing after 300 ms the scan is emitted with the missing angles as `null`.
- Sonar sweep (e.g. 0–180° in 10° steps = 19 pts) fits in one fragment; lidar 360 pts → 4 fragments.

#### 2.4 `event`. Wire: `EventMsg`
```json
{"v":1,"type":"event","t":14000,"seq":101,"level":"warn","code":"BATT_LOW","msg":"vbat 10.4 V"}
```
Codes: BOOT, BATT_LOW, BATT_CRIT, TILT, WD_STOP, ESTOP, SENSOR_LOST, OBSTACLE, CMD_REJECTED.

#### 2.5 `ack`. Wire: `AckMsg` — rules in §6.8
```json
{"v":1,"type":"ack","t":5010,"seq":90,"ack_seq":42,"ok":true}
```

### 3. Ground station → Rover

#### 3.1 `cmd` — 10 Hz while the dashboard runs (this IS the heartbeat). Wire: `CmdMsg` (30 B)
```json
{"v":1,"type":"cmd","t":5000,"seq":42,
 "drive":{"l":0.6,"r":0.6},
 "mode":"manual",
 "servo":{"mode":"sweep","angle_deg":90},
 "estop":false, "estop_reset":false, "buzzer":false, "request_hello":false,
 "goto":null}
```
- `drive` −1.0…1.0, rover clamps. `estop:true` latches until a cmd with `estop_reset:true`.
- `goto` `{x_m,y_m}` reserved for future navigation (NaN on the wire = none).

#### 3.2 Ground-station-only data (never on the radio)
The backend adds a `link` block to the UI snapshot:
```json
"link":{"state":"OK","rx_hz":10.0,"loss_pct":0.4,"rtt_ms":23,
        "rssi_bridge_dbm":-58,"rssi_rover_dbm":-61,"bridge_tx_fail":3,"serial_port":"COM5"}
```
`state`: OK (< 300 ms since last telem) · STALE (300 ms–2 s) · LOST (> 2 s) · NO_BRIDGE (serial port missing).

### 4. Serial framing (ground_bridge ⇄ laptop)

```
frame   = COBS( kind[1] | rssi[1] | payload[N] | crc16_le[2] ) , 0x00
kind    = 0x01 RX_FROM_ROVER   bridge→laptop  payload = one wire message, rssi = RX RSSI (int8)
          0x02 TX_TO_ROVER     laptop→bridge  payload = one wire message (CmdMsg), rssi = 0
          0x03 BRIDGE_STATUS   bridge→laptop  payload = BridgeStatus (19 B), 1 Hz
          0x04 BRIDGE_LOG      bridge→laptop  payload = ASCII text (debug)
crc16   = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, xorout 0) over kind|rssi|payload
```
- Arduino side: the `PacketSerial` library does COBS + 0x00 delimiting.
- Python side: `cobs` package (`cobs.cobs.encode/decode`), CRC with a 10-line function or `crcmod`.
- Bad CRC / bad magic → drop + count, never crash.

#### Python struct formats (must match `rover_protocol.h`, verified sizes)
| Message | `struct` format | bytes |
|---------|-----------------|-------|
| MsgHeader | `<BBBBHI` | 10 |
| HelloMsg | `<BBBBHI20sHBBBBBB` | 38 |
| TelemMsg | `<BBBBHIfffffffffhhfffffffffffffffBBHbIIHf` | 129 |
| ScanMsg | header `<BBBBHIBBBBfffHHB` (31 B), **then** `n` × `<H` dist_cm appended — send/parse only 31 + 2n bytes | 31 + 2n |
| EventMsg | `<BBBBHIBB60s` | 72 |
| AckMsg | `<BBBBHIHB` | 13 |
| CmdMsg | `<BBBBHIffBBBBff` | 30 |
| BridgeStatus | `<IIIIBbB` | 19 |

Golden-bytes tests: `tests/golden/*.hex` are generated **from the real C structs** by
`tools/golden_gen.cpp` (independent of wire.py); `tests/golden/expected.json` is the JSON each must
decode to (floats with 1e-4 tolerance). wire.py must decode every .hex to the expected JSON and
re-encode it to the identical bytes. In Phase 11 the firmware's `dump_golden` serial command must
print the same hex — that closes the loop on real hardware.
Regenerate: `g++ -std=c++17 -I firmware/common tools/golden_gen.cpp -o golden_gen && ./golden_gen tests/golden`.

### 5. Safety rules (enforced in rover_main, mirrored in the simulator)
1. No valid CmdMsg for **500 ms** → motors 0, event WD_STOP, `wd_ok=false`. (Laptop crash, bridge
   unplugged, out of range — all end here.)
2. `estop` latched → motors 0 regardless of drive, until `estop_reset`.
3. |roll| or |pitch| > 35° → motors 0, event TILT.
4. `vbat_v` < 9.9 V → BATT_CRIT, drive limited to 30 %.
5. CmdMsg with wrong magic/version or from an unknown MAC → ignored, CMD_REJECTED event (rate-limited).

### 6. Clarifications (decided after the Phase 0 review, 2026-10-20)

1. **Servo** — JSON: nested as `hw.sonar.servo` (bool). Wire: separate bit `HW_SERVO` (10).
   wire.py maps the bit ⇄ `hw.sonar.servo`. No top-level `hw.servo` key.
2. **Camera** — `HW_CAMERA` (bit 7) is **reserved, always 0** from the rover. `hw.camera` is owned by
   the ground station (HTTP probe of `camera_url`). wire.py never creates `hw.camera`; state.py adds it.
3. **Buzzer** — bit `HW_BUZZER` only, no model/detail. Intentional.
4. **`model` strings** — only `env.model` and `lidar.model` come from the wire. The other `model`
   values in the hello example (`mpu6050`, `bh1750`, `hc-sr04`, `ina219`) are fixed defaults that
   protocol.py fills in when `present` is true; tests check `present` and wire-carried fields only.
5. **reset_reason** — `uint8_t` from `esp_reset_reason()`, mapped in wire.py:
   0 UNKNOWN · 1 POWERON · 2 EXT · 3 SW · 4 PANIC · 5 INT_WDT · 6 TASK_WDT · 7 WDT · 8 DEEPSLEEP ·
   9 BROWNOUT · 10 SDIO · 11 USB · 12 JTAG · 13 EFUSE · 14 PWR_GLITCH · 15 CPU_LOCKUP;
   anything else → `"UNKNOWN_<n>"`. Dashboard shows BROWNOUT, PANIC and any *WDT as a warning event.
6. **Event text** — firmware writes ASCII with `snprintf(msg, 60, ...)`: silently truncated to 59 chars
   + NUL. Python decodes up to the first NUL, `errors="replace"`.
7. **Scan pose** — every fragment of one scan carries the **same** pose: the pose at the start of
   the scan. Python takes it from the first fragment received. Motion during a sweep is ignored for
   now (mapping can de-skew later).
8. **Ack rules** — the rover sends one AckMsg (`ack_seq` = that CmdMsg's seq) when **either**
   (a) `mode` or `cmd_flags` differ from the previous accepted CmdMsg, **or** (b) `seq % 10 == 0`
   (≈ 1 Hz, so RTT is measured continuously). At most one ack per CmdMsg. Changes to drive or
   servo values alone don't trigger (a).
9. **E-STOP sending** — the GS sets `CMD_ESTOP` on the next 3 CmdMsgs, then clears the bit; the
   latch lives on the rover. Clearing the bit does not release the latch — only `CMD_ESTOP_RESET` does.
10. **Rover restart / time base** (D-015, GS-2 in docs/PROGRESS_ROVER_MAIN.md) — on every boot the
    rover starts `seq` at 0 and `t_ms` = `millis()` (0 at boot, wraps after 49.7 days), and sends a
    HELLO (with `reset_reason`) before any TELEM. The GS declares a rover restart when `t_ms` goes
    back by more than 500 ms (except a 49.7-day wrap), or on a HELLO with `seq == 0`, or on a
    backward `seq` jump ≥ 1000; it then resets loss/RTT/scan state and logs `ROVER_RESTART`. If the
    GS has TELEM but no HELLO since the restart, it sets `CMD_REQUEST_HELLO` until one arrives.

---


# §4. Dashboard spec  (`docs/03_DASHBOARD_SPEC.md`)

## 03 — Dashboard Specification

Browser UI served by the backend at `http://localhost:8000`. Dark theme by default (readable in a
dim demo room), works at 1366×768 laptop resolution, no internet required.

### 1. Layout

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ TOP BAR: ● LINK OK  COM5  RSSI ↑−61 ↓−58 dBm  RTT 23 ms  loss 0.4 %  T+00:05:40 │
│          vbat 11.4 V ▮▮▮▮▯ 71 %                     [● REC]        [  E-STOP  ]  │
├───────────────────────────────┬──────────────────────────────────────────────────┤
│ VIDEO                         │ MAP  (stub now: polar plot of latest scan)       │
│ live MJPEG + overlays         │ later: occupancy grid, rover pose, trail,        │
│ "CAMERA NOT INSTALLED"        │ click-to-set waypoint                            │
├───────────────┬───────────────┴───────────────┬──────────────────────────────────┤
│ ENVIRONMENT   │ ROVER HEALTH                  │ CONTROL                          │
│ temp  22.4 °C │ motors L/R: cmd vs rpm bars   │ WASD / arrows / gamepad          │
│ hum   41 %    │ attitude: roll/pitch gauge,   │ speed limit slider               │
│ press 1012 hPa│   yaw compass                 │ mode: manual|assisted|auto       │
│ lux   340     │ sonar: distance + mini radar  │ servo: sweep | fixed [angle]     │
│ each with 5-min│ power: V, I*, W*, SoC trend  │ buzzer button                    │
│ sparkline     │ sys: heap, loop Hz, uptime    │ (* = not installed yet)          │
├───────────────┴───────────────────────────────┴──────────────────────────────────┤
│ EVENT LOG (filter by level)   ·   SESSION: recording to logs/20261020_1530/      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2. Panel behaviour

| Panel        | Data                        | Update | Notes |
|--------------|-----------------------------|--------|-------|
| Top bar      | `link` (docs/02 §3.2), `sys`, `pwr`, `state` | 10 Hz | Link state: OK / STALE / LOST / NO_BRIDGE (USB bridge unplugged → show "Plug in ground bridge" and a serial-port picker). RSSI both directions: rover's view of our commands (↑) and bridge's view of the rover (↓). Loss % from `seq` gaps, RTT from cmd→ack, bridge TX failures. |
| Video        | MJPEG via backend proxy `/video` from `camera_url` (ESP32-CAM AP) | stream | Overlay: heading, sonar distance, "STALE" if no frame for 1 s. If the laptop isn't on the ROVER-CAM WiFi, say so. |
| Map          | `scan`                       | per scan | Phase 1: polar plot of the last sweep. Mapping later. |
| Environment  | `env`, `light`               | 1 Hz shown | Value + unit + sparkline (last 5 min) + min/max of session |
| Rover health | `mot`, `imu`, `sonar`, `pwr`, `sys` | 10 Hz | Colour thresholds below |
| Control      | sends `cmd`                  | 10 Hz  | Keys only active when page focused; releasing keys → 0 |
| Event log    | `event` + backend events     | on event | Newest on top, warn/error highlighted |

#### Hardware-absent behaviour (key requirement)
When `hello.hw.<item>.present == false`, the related widgets render a greyed card with
**"NOT INSTALLED — see docs/04_FUTURE_HARDWARE.md"**. When a value is `null` but the hardware is
present, show **"—"** and a "no data" tooltip. When the link is LOST, all values freeze, turn grey
and show their age ("12 s ago").

#### Thresholds (configurable in `ground_station/app/config.toml`)
| Value            | Green     | Amber          | Red        |
|------------------|-----------|----------------|------------|
| vbat_v (3S)      | > 11.1    | 10.5–11.1      | < 10.5     |
| roll/pitch       | < 20°     | 20–30°         | > 30°      |
| rssi_dbm         | > −67     | −67…−80        | < −80      |
| sonar dist_cm    | > 50      | 20–50          | < 20       |
| last_cmd_age_ms  | < 200     | 200–500        | > 500      |
| chip_temp_c      | < 60      | 60–75          | > 75       |

### 3. Controls & safety in the UI
- **E-STOP**: always visible, also bound to `Space`. Sends `estop:true` immediately (3 times, 50 ms
  apart). Reset needs a confirm click → `estop_reset:true`.
- Drive: `W/S` forward/back, `A/D` turn, `Shift` = boost to speed limit. Gamepad via the browser
  Gamepad API (optional, later).
- If the browser tab loses focus or closes → backend stops sending drive values (sends zeros) →
  rover watchdog is the final backstop.

### 4. Recording & replay
- Every session writes `logs/<timestamp>/raw.jsonl` (every message, both directions, with laptop
  receive time) plus convenience CSVs (`telem.csv`, `events.csv`).
- `python -m ground_station.app --replay logs/<timestamp>/raw.jsonl` feeds the UI from the log —
  essential for the report/demo and for developing mapping later from real data.
- Export button: download the current session's CSVs.

### 5. Out of scope for now
- Mapping/SLAM, path planning, autonomy (map panel is a stub).
- Multi-user / remote access over the internet.

---


# §5. Hardware roadmap  (`docs/04_FUTURE_HARDWARE.md`)

## 04 — Hardware Roadmap: now, next, future

The software is built so every item below can be plugged in later **without changing the protocol
or the dashboard** — only a firmware driver gets enabled and `hello.hw.<item>.present` becomes `true`.
Prices are rough estimates (Oct 2026), check before buying.

### 0. Status overview

| # | Item                         | Status        | Protocol fields ready     | Est. cost |
|---|------------------------------|---------------|---------------------------|-----------|
| A | BME280 temp/hum/pressure     | **NOW**       | `env.*`                   | €5–10     |
| B | Battery voltage divider      | **NOW** (resistors on hand) | `pwr.vbat_v`, `pwr.soc_pct` | €0 |
| — | ESP32 #2 as ground_bridge (USB, ESP-NOW) | **NOW** (board on hand) | all | €0 |
| C | ESP32-CAM + USB programmer (ESP32-CAM-MB) | FUTURE | `hw.camera`, `/video` | €10–15 |
| D | Wheel encoders               | FUTURE        | `mot.rpm_*`, `odom.*`     | €5–15     |
| E | INA219 current sensor        | FUTURE        | `pwr.ibat_a`, `pwr.p_w`   | €3–6      |
| F | LiDAR (LDROBOT LD06 / LD19)  | FUTURE        | `scan` with `src:"lidar"` | €70–100   |
| G | 2nd MP1584EN 5 V regulator (camera + lidar rail) | FUTURE | — | €2–4 |

### 1. Pin reservation (ESP32 DevKit V1, `rover_main`)
Reserve these now so future hardware never forces a rewire. Verify against your board's pinout.

| Function              | GPIO        | Notes |
|-----------------------|-------------|-------|
| I2C SDA / SCL         | 21 / 22     | MPU-6050 0x68, BME280 0x76/0x77, BH1750 0x23, INA219 0x40 — no address clashes |
| TB6612 PWMA/AIN1/AIN2 | 25 / 26 / 27 | |
| TB6612 PWMB/BIN1/BIN2 | 32 / 33 / 4  | avoid GPIO 12 (boot strapping) |
| TB6612 STBY           | 23          | |
| Servo SG90            | 18          | own 5 V supply, common GND |
| HC-SR04 TRIG / ECHO   | 5 / 19      | **ECHO is 5 V → divider (e.g. 1 k / 2 k) to 3.3 V** |
| Buzzer                | 13          | |
| Battery divider       | 34 (ADC1)   | input-only pin, fine |
| Encoder L / R  [future] | 36 / 39   | input-only, use module's pull-ups |
| LiDAR RX (UART2) [future] | 16      | LD06 TX → GPIO16; LD06 needs 5 V, ~180 mA |
| Spare                 | 17, 14, 15, 2 | |

### 2. Implementation steps

#### A. BME280 (now)
1. Buy a module **explicitly marked BME280** (BMP280 has no humidity). Wire to I2C, 3.3 V.
2. Firmware: driver reads chip ID → `hw.env.model` = `bme280` / `bmp280`. Read at 1 Hz.
3. Set pressure reference at boot → `alt_m` relative altitude.
4. Keep the DHT11 as a fallback driver (`hw.env.model:"dht11"`, `press_hpa:null`).
5. ✔ Test: breathe on it → humidity rises; lift 1 m → `alt_m` changes ~ +1 m (noisy, ±0.5 m).

#### B. Battery voltage divider (now)
1. 100 kΩ (top) / 33 kΩ (bottom) from battery + to GND, mid-point → GPIO34. 100 nF cap mid-point → GND.
2. Firmware: average 16 samples, `analogReadMilliVolts()`, multiply by (133/33), then a 2-point
   calibration against a multimeter (9.5 V and 12.4 V).
3. SoC from a 3S Li-ion lookup table (not linear). Low-pass filter so it doesn't jump when motors start.
4. ✔ Test: dashboard reading within ±0.1 V of the multimeter across the range.

#### C. ESP32-CAM (future)
1. Buy ESP32-CAM (AI-Thinker, OV2640) **with the ESP32-CAM-MB USB board** (no USB on the CAM itself).
2. Power from its own 5 V regulator (item G) — it browns out on WiFi peaks if it shares a weak rail.
3. Firmware `firmware/rover_cam/`: create WiFi AP `ROVER-CAM` on **channel 1** (ESP-NOW uses 11),
   IP 192.168.4.1, serve `/stream` (MJPEG, QVGA 320×240, quality ~12) and `/status`.
4. The laptop joins `ROVER-CAM` for video (it loses internet meanwhile; telemetry is unaffected
   because it goes over the USB bridge). The ground station probes `camera_url/status` to set
   `hw.camera.present`.
5. Ground station: `video.py` proxies the stream to `/video`, measures fps, flags STALE.
6. ✔ Test: ≥10 fps at 3 m from the laptop; latency < 300 ms (film a stopwatch).
7. Later: camera calibration (checkerboard) → needed if vision is used for mapping/landmarks.

#### D. Wheel encoders (future)
Option 1 (cheap, keeps TT motors): LM393 slotted optical sensor + 20-slot disc per wheel.
Option 2 (better): TT/N20/JGA25 motors with built-in Hall encoders (more counts, direction-aware).
1. Mount, wire signal → GPIO36/39, 3.3 V supply.
2. Firmware: interrupt counter with debounce (ignore pulses < 1 ms apart), RPM over a 100 ms window.
   Optical sensors don't know direction → take sign from the commanded `pwm_l/pwm_r`.
3. `odom`: differential-drive equations using wheel radius + track width (measure them, put in config),
   heading from IMU yaw fused with encoder difference.
4. Unlocks: closed-loop speed (PID per wheel) so the rover drives straight.
5. ✔ Test: drive 2.00 m measured with tape → `odom.dist_m` within 5 %.

#### E. INA219 (future)
1. Insert in series with battery + after the BMS (max 3.2 A with the stock 0.1 Ω shunt — check your
   peak motor current; use a 0.01 Ω shunt module if higher).
2. Firmware: I2C 0x40, read bus V, current, power at 10 Hz. It also gives a better `vbat_v` than the divider.
3. Ground station: integrate current → mAh used; estimate remaining runtime.
4. ✔ Test: wheels free vs. wheels blocked → current clearly rises; matches multimeter ±10 %.

#### F. LiDAR (future — mapping is on the back burner)
Recommended: **LDROBOT LD06 or LD19** — 360°, ~12 m, 10 Hz, one-way UART 230400 baud, 5 V. Simple
packet format, Arduino libraries exist. Alternative: RPLIDAR C1 (UART 460800).
1. Mount on top, clear 360° view, centre aligned with rover rotation axis if possible. Note the
   orientation offset in config.
2. Power from the 5 V rail of item G (motor inside the lidar draws ~180 mA).
3. Firmware: UART2 RX on GPIO16, parse packets (CRC check), bin into 1° buckets → send each
   revolution as 4 SCAN fragments (`src = SCAN_LIDAR`). ESP32 #2 is now the ground bridge, so if
   `rover_main` loop rate drops below 80 Hz, run lidar parsing as a FreeRTOS task on core 0 or add a
   third ESP32.
4. Ground station: map panel already draws `scan` as a polar plot → works on day one.
5. Mapping phase (when we decide): occupancy grid from scans + `odom` pose; consider BreezySLAM or
   a simple ICP scan-matcher in Python; A* on the grid → `cmd.goto` waypoints.
6. ✔ Test: place a box 1.00 m away → scan shows 100 cm ± 3 cm at the correct angle.

#### G. Second 5 V regulator (future, with C or F)
One MP1584EN for ESP32 + logic, a second one for camera + lidar + servo. Prevents brownouts and
servo noise resetting the ESP32. Add 470 µF on each 5 V rail.

### 3. Future shopping list (copy into LISTA)
- [ ] BME280 module (verify it's BME, not BMP) — **buy now**
- [ ] ESP32-CAM AI-Thinker + ESP32-CAM-MB programmer
- [ ] 2× LM393 slotted speed sensor + 20-slot encoder discs (or encoder motors)
- [ ] INA219 module
- [ ] LDROBOT LD06 or LD19 LiDAR
- [ ] 1× MP1584EN extra + 2× 470 µF capacitors
- [ ] Resistors for dividers: 100 k, 33 k, 1 k, 2 k (probably on hand)

---


# §6. rover_protocol.h  (`firmware/common/rover_protocol.h`)

```cpp
// rover_protocol.h — binary wire protocol v1 (radio link, ESP-NOW)
// Single C definition shared by firmware/rover_main and firmware/ground_bridge.
// Mirror in Python: ground_station/app/wire.py (struct format strings + golden-bytes tests).
// Logical meaning of every field: docs/02_TELEMETRY_PROTOCOL.md
//
// Rules:
//  - Little-endian, packed, every message <= 250 bytes (ESP-NOW v1 payload limit).
//  - float NaN  = "no data / hardware not installed"  (becomes JSON null on the laptop)
//  - uint16 0xFFFF in distance arrays = no echo / no return
//  - Never reorder or resize fields without bumping PROTO_VER.
#pragma once
#include <stdint.h>

#define PROTO_MAGIC 0xA7
#define PROTO_VER   1
#define ESPNOW_MAX_PAYLOAD 250

enum MsgType : uint8_t {
  MSG_HELLO = 0x01,   // rover -> GS, on boot, every 5 s, and on CMD_REQUEST_HELLO
  MSG_TELEM = 0x02,   // rover -> GS, 10 Hz
  MSG_SCAN  = 0x03,   // rover -> GS, per sweep / revolution (fragmented)
  MSG_EVENT = 0x04,   // rover -> GS, on event
  MSG_ACK   = 0x05,   // rover -> GS, reply to non-drive commands
  MSG_CMD   = 0x10,   // GS -> rover, 10 Hz (also the heartbeat)
};

enum HwBit : uint16_t {           // HelloMsg.hw_present bit positions
  HW_IMU = 0, HW_ENV = 1, HW_LIGHT = 2, HW_SONAR = 3, HW_BATTERY = 4,
  HW_CURRENT = 5, HW_ENCODERS = 6,
  HW_CAMERA = 7,   // RESERVED: always 0 from the rover; camera presence is probed by the ground station
  HW_LIDAR = 8, HW_BUZZER = 9,
  HW_SERVO = 10,   // maps to JSON hw.sonar.servo
};

enum EnvModel   : uint8_t { ENV_NONE = 0, ENV_BME280 = 1, ENV_BMP280 = 2, ENV_DHT11 = 3 };
enum LidarModel : uint8_t { LIDAR_NONE = 0, LIDAR_LD06 = 1, LIDAR_LD19 = 2, LIDAR_RPLIDAR_C1 = 3 };
enum Mode       : uint8_t { MODE_IDLE = 0, MODE_MANUAL = 1, MODE_ASSISTED = 2, MODE_AUTO = 3 };
enum ScanSrc    : uint8_t { SCAN_SONAR = 1, SCAN_LIDAR = 2 };
enum EvLevel    : uint8_t { EV_INFO = 0, EV_WARN = 1, EV_ERROR = 2 };
enum EvCode     : uint8_t {
  EV_BOOT = 1, EV_BATT_LOW = 2, EV_BATT_CRIT = 3, EV_TILT = 4, EV_WD_STOP = 5,
  EV_ESTOP = 6, EV_SENSOR_LOST = 7, EV_OBSTACLE = 8, EV_CMD_REJECTED = 9,
};

// TelemMsg.state_flags
#define ST_ESTOP  (1u << 0)
#define ST_WD_OK  (1u << 1)
// CmdMsg.cmd_flags
#define CMD_ESTOP         (1u << 0)
#define CMD_ESTOP_RESET   (1u << 1)
#define CMD_BUZZER        (1u << 2)
#define CMD_REQUEST_HELLO (1u << 3)

#pragma pack(push, 1)

struct MsgHeader {          // 10 bytes
  uint8_t  magic;           // PROTO_MAGIC
  uint8_t  ver;             // PROTO_VER
  uint8_t  type;            // MsgType
  uint8_t  flags;           // reserved, 0
  uint16_t seq;             // per-sender counter, wraps
  uint32_t t_ms;            // sender millis()
};

struct HelloMsg {           // 38 bytes
  MsgHeader h;
  char     fw[20];          // "rover_main 0.1.0", NUL-padded
  uint16_t hw_present;      // bitmask of HwBit
  uint8_t  env_model;       // EnvModel (from chip ID: 0x60 BME280, 0x58 BMP280)
  uint8_t  lidar_model;     // LidarModel
  uint8_t  cells;           // battery series cells (3)
  uint8_t  reset_reason;    // esp_reset_reason()
  uint8_t  encoder_cpr;     // counts per wheel rev, 0 if none
  uint8_t  reserved;
};

struct TelemMsg {           // 129 bytes
  MsgHeader h;
  // env (BME280 / BMP280 / DHT11)
  float temp_c, hum_pct, press_hpa, alt_m;
  float lux;                                  // BH1750
  // power
  float vbat_v, soc_pct, ibat_a, p_w;         // ibat/p_w NaN until INA219
  // motors
  int16_t pwm_l, pwm_r;                       // commanded, -255..255 (sign = direction)
  float rpm_l, rpm_r;                         // NaN until encoders
  // odometry (NaN until encoders)
  float x_m, y_m, dist_m;
  // imu (MPU-6050)
  float roll_deg, pitch_deg, yaw_deg, ax_g, ay_g, az_g, gz_dps, imu_temp_c;
  // sonar (latest single ping)
  float sonar_angle_deg, sonar_dist_cm;       // dist NaN = no echo
  // state
  uint8_t  mode;                              // Mode
  uint8_t  state_flags;                       // ST_*
  uint16_t last_cmd_age_ms;
  int8_t   rssi_dbm;                          // RSSI of last CMD as seen by the rover
  // sys
  uint32_t heap_b;
  uint32_t uptime_s;
  uint16_t loop_hz;
  float    chip_temp_c;
};

#define SCAN_MAX_PTS 100
struct ScanMsg {            // 231 bytes when n = 100 (send only 31 + 2*n bytes)
  MsgHeader h;
  uint8_t  src;             // ScanSrc
  uint8_t  scan_id;         // increments per complete sweep / revolution
  uint8_t  part;            // fragment index 0..parts-1
  uint8_t  parts;           // total fragments (lidar 360 pts -> 4)
  float    yaw_deg;         // pose at start of scan
  float    x_m, y_m;        // NaN without odometry
  uint16_t start_cdeg;      // angle of dist_cm[0], centi-degrees, rover frame (0 = front, CCW+)
  uint16_t step_cdeg;       // angle step between points, centi-degrees
  uint8_t  n;               // valid points in this fragment
  uint16_t dist_cm[SCAN_MAX_PTS]; // 0xFFFF = no return
};
#define SCAN_HEADER_BYTES 31

struct EventMsg {           // 72 bytes
  MsgHeader h;
  uint8_t level;            // EvLevel
  uint8_t code;             // EvCode
  char    msg[60];          // ASCII, NUL-terminated; snprintf truncates silently to 59 chars
};

struct AckMsg {             // 13 bytes
  MsgHeader h;
  uint16_t ack_seq;         // seq of the CmdMsg being acknowledged
  uint8_t  ok;              // 1 accepted, 0 rejected
};

struct CmdMsg {             // 30 bytes
  MsgHeader h;
  float   drive_l, drive_r; // -1.0..1.0 fraction of max PWM (rover clamps)
  uint8_t mode;             // Mode
  uint8_t servo_mode;       // 0 sweep, 1 fixed
  uint8_t servo_angle_deg;  // used when servo_mode = 1
  uint8_t cmd_flags;        // CMD_*
  float   goto_x_m, goto_y_m; // NaN = none (future waypoint navigation)
};

#pragma pack(pop)

// ---------- Serial framing between ground_bridge and laptop (USB, 921600 baud) ----------
// Each frame:  COBS( kind[1] | rssi[1] | payload[N] | crc16[2] ) followed by 0x00 delimiter
// crc16 = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over kind|rssi|payload, little-endian.
enum SerialKind : uint8_t {
  SK_RX_FROM_ROVER = 0x01,  // bridge -> laptop: payload = one radio message, rssi = RX RSSI
  SK_TX_TO_ROVER   = 0x02,  // laptop -> bridge: payload = one radio message to send, rssi = 0
  SK_BRIDGE_STATUS = 0x03,  // bridge -> laptop, 1 Hz: payload = BridgeStatus
  SK_BRIDGE_LOG    = 0x04,  // bridge -> laptop: payload = ASCII text
};

#pragma pack(push, 1)
struct BridgeStatus {       // 19 bytes
  uint32_t uptime_ms;
  uint32_t rx_count;        // radio frames received from rover
  uint32_t tx_ok;           // esp_now_send callbacks with success
  uint32_t tx_fail;
  uint8_t  channel;         // WiFi channel used for ESP-NOW
  int8_t   last_rssi;
  uint8_t  rover_paired;    // 1 if rover peer added
};
#pragma pack(pop)

#ifdef __cplusplus
static_assert(sizeof(MsgHeader)    == 10,  "MsgHeader size");
static_assert(sizeof(HelloMsg)     == 38,  "HelloMsg size");
static_assert(sizeof(TelemMsg)     == 129, "TelemMsg size");
static_assert(sizeof(ScanMsg)      == 231, "ScanMsg size");
static_assert(sizeof(EventMsg)     == 72,  "EventMsg size");
static_assert(sizeof(AckMsg)       == 13,  "AckMsg size");
static_assert(sizeof(CmdMsg)       == 30,  "CmdMsg size");
static_assert(sizeof(BridgeStatus) == 19,  "BridgeStatus size");
static_assert(sizeof(ScanMsg) <= ESPNOW_MAX_PAYLOAD, "ScanMsg too big for ESP-NOW");
#endif
```

---


# §7. VS Code setup  (`docs/05_VSCODE_SETUP.md`)

## 05 — Setting up VS Code + Claude Code

Goal: every team member opens the same repo in VS Code, with Claude Code in a side panel that
already knows the project (via `CLAUDE.md` and these docs).

### Step 0 — Move the code OUT of OneDrive
Keep the docs in OneDrive if you like, but put the **git repo** in a normal folder, e.g.
`C:\dev\rover-software`. OneDrive syncing `.git/` and `.venv/` causes locked files, sync conflicts
and corrupted repos. Share code between teammates through GitHub instead.

### Step 1 — Install the tools (each team member)
1. **VS Code** 1.94 or newer — https://code.visualstudio.com
2. **Python 3.12** — https://www.python.org (Windows: tick "Add python.exe to PATH")
3. **Git** — https://git-scm.com
4. **USB driver** for the ESP32 DevKit (CP210x or CH340, depending on the chip next to the USB port)
5. A **paid Claude account** (Pro/Max/Team) — required for Claude Code. No API key needed.

### Step 2 — VS Code extensions
Open Extensions (`Ctrl+Shift+X`) and install:
- **Claude Code** (publisher: Anthropic)
- **Python** + **Pylance** (Microsoft)
- **PlatformIO IDE** (for ESP32 firmware)
- Optional: **GitLens**, **Error Lens**

If the Claude Code icon doesn't appear, run "Developer: Reload Window" from `Ctrl+Shift+P`.

### Step 3 — Create the repo
`C:\dev` does not exist by default — you create it. Use **PowerShell** (Start menu → "PowerShell"),
not Command Prompt:
```powershell
New-Item -ItemType Directory -Force C:\dev
Copy-Item -Recurse "C:\Users\Usuario\Desktop\OneDrive\Univesidad Europea\Year 3\Space Vehicles & Missiles\Rover Project\rover-software" C:\dev\
cd C:\dev\rover-software
git init
git add .
git commit -m "Add planning docs and CLAUDE.md"
```
If Windows refuses to create `C:\dev` (locked-down PC), use `$HOME\dev` instead — any folder
**outside OneDrive** works.

No terminal? In File Explorer: open `C:\`, New → Folder → `dev`, then copy the `rover-software`
folder into it. Afterwards run the `git` lines from a terminal opened in that folder.

Create a **private** GitHub repo, add teammates as collaborators, then:
```powershell
git remote add origin https://github.com/<you>/rover-software.git
git branch -M main ; git push -u origin main
```
Teammates: `git clone` it into their own `C:\dev`.

### Step 4 — Open in VS Code and start Claude Code
1. `File → Open Folder… → C:\dev\rover-software`
2. Click the **Spark icon** (Claude Code) in the left Activity Bar or top-right of an open file.
3. Sign in with your Claude account the first time.
4. **Don't run `/init`** — `CLAUDE.md` already exists and `/init` would rewrite it.
5. Check the permission mode at the bottom of the prompt box. Start in a mode that **asks before
   editing** until you trust the workflow. Use **plan mode** (`/plan`) for each new phase so you
   review the plan before any code is written.
6. Reference files in prompts with `@`, e.g. `@docs/02_TELEMETRY_PROTOCOL.md`.

### Step 5 — Python environment (Claude Code can do this in Prompt 1, or do it yourself)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r ground_station/requirements.txt
```
In VS Code: `Ctrl+Shift+P → Python: Select Interpreter → .venv`.

### Step 5b — Turn on the repo's Git reminders (once per clone)
```powershell
git config core.hooksPath tools/hooks
```
After this, `git pull` prints a warning whenever `ground_station/requirements.txt` changed, telling
you to run `pip install -r ground_station/requirements.txt`.

### Step 6 — Work loop (per prompt in 06_CLAUDE_CODE_PROMPTS.md)
1. New Claude Code conversation per phase (keeps context focused).
2. Paste the prompt → review the plan → approve.
3. Review the diffs Claude shows; ask for changes in plain language.
4. Run the acceptance check listed under the prompt yourself.
5. `git commit` (or ask Claude to commit) → `git push`.
6. If something breaks: Claude Code has checkpoints/rewind, and git is your real safety net.

### Team workflow tips
- One person per phase/branch: `git checkout -b phase-3-dashboard`, merge via Pull Request.
- If you change the protocol, the PR must touch `docs/02`, `protocol.py` and `fake_rover.py` together
  (rule in CLAUDE.md — Claude Code will follow it).
- Commit `CLAUDE.md` changes too: it is the shared memory for everyone's Claude Code.

---


# §8. Build prompts  (`docs/06_CLAUDE_CODE_PROMPTS.md`)

## 06 — Claude Prompt Sequence

Works in **Claude Code** (VS Code, repo open — it reads CLAUDE.md automatically) and in **Claude chat**
(Pro) inside a Claude Project that has `docs/TEAM_BRIEF.md` as knowledge. In chat, Claude can't run
anything: ask for complete files, paste them into the repo, run the checks yourself, paste errors back.

One prompt per phase, each in a **new conversation**. In Claude Code start with `/plan`.
Every prompt ends with a check — run it before committing.

### Two parallel tracks
- **Track A – Python ground station:** Phases 1–9 (works fully with the simulator, no hardware).
- **Track B – Firmware:** Phases 10–11. Can start as soon as Phase 1 is merged (the wire protocol is
  then frozen and golden-tested on the Python side).

---

### Phase 0 — Orientation (no code)
```
Read CLAUDE.md, every file in docs/ and firmware/common/rover_protocol.h. Do not write code yet.
1. Summarise the system in 10 bullet points so I can check you understood it.
2. List contradictions or gaps between the docs.
3. List the questions you need answered before Phase 1.
```
✔ Check: summary matches the docs; fix gaps in the docs first.

---

### Phase 1 — Scaffold + protocol + wire codec   (Track A, unblocks Track B)
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

### Phase 2 — Fake rover simulator
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

### Phase 3 — Backend core
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

### Phase 4 — Dashboard layout + top bar
```
Build ground_station/app/web/ (plain HTML/CSS/JS, no build step, no CDN — vendor uPlot into
web/vendor/). Full grid from docs/03 §1 with placeholder cards and a working TOP BAR (link state,
serial port, both RSSIs, RTT, loss, mission clock, mode, battery, REC, E-STOP on Space).
NO_BRIDGE shows "Plug in ground bridge" + port picker. Implement the hardware-absent rules from
docs/03 as one reusable JS helper used by every panel. Dark theme, 1366x768.
```
✔ Check: simulator with/without `--ina219` → current widget switches value ↔ NOT INSTALLED.

---

### Phase 5 — Environment + Rover health panels
```
Implement ENVIRONMENT and ROVER HEALTH from docs/03: env values + 5-min sparklines + session min/max
(handle bmp280 = no humidity, dht11 = no pressure); motor cmd vs rpm bars, attitude indicator, yaw
compass, sonar distance + mini radar, power (V, I, W, SoC trend), sys stats. Thresholds come from
config.toml via the backend. Redraw charts at most 2 Hz.
```
✔ Check: `--bmp280` and `--dht11` runs show "—"/NOT INSTALLED correctly, nothing crashes.

---

### Phase 6 — Control + safety
```
Implement CONTROL from docs/03 §3: WASD/arrows, speed limit, Shift boost, mode, servo sweep/fixed,
buzzer. Keys act only while the page is focused; blur/close -> drive 0. E-STOP sets the estop flag
on the next 3 CmdMsgs immediately (don't wait for the 10 Hz tick); reset needs a confirm.
Show wd_ok and last_cmd_age_ms. Simulator tests: stop CmdMsg -> WD_STOP within 600 ms; estop
latched ignores drive until estop_reset.
```
✔ Check: drive the simulator from the browser; close the tab → motors 0.

---

### Phase 7 — Recording, replay, export
```
replay.py + `python -m ground_station.app --replay logs/<ts>/raw.jsonl [--speed 2]` feeding the UI
like a live rover (controls disabled, REPLAY banner). Export button (zip of the session CSVs).
EVENT LOG panel with level filter.
```
✔ Check: record 2 min, replay at 2× → identical charts.

---

### Phase 8 — Video panel (before the camera exists)
```
video.py: proxy MJPEG from config camera_url to /video, measure fps and frame age, probe
camera_url/status every 5 s to fill hello.hw.camera. Simulator flag --camera serves a fake MJPEG
stream (OpenCV frames, moving pattern + timestamp) on http://127.0.0.1:8081/stream.
VIDEO panel: stream + overlay (heading, sonar distance, fps), STALE after 1 s, NOT INSTALLED card.
```
✔ Check: works with and without `--camera`.

---

### Phase 9 — Map panel stub
```
MAP panel stub only: polar plot of the latest scan (sonar or lidar), rover arrow, range rings every
50 cm. mapping/__init__.py with class Mapper (update(scan, pose); get_grid() -> ndarray|None) and a
NullMapper. Do NOT implement SLAM.
```
✔ Check: `--lidar` shows the fake room outline; without it the sonar sweep.

---

### Phase 10 — Firmware: ground_bridge   (Track B)
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
- The bridge must NOT decode telemetry or generate commands.
secrets.example.h committed, secrets.h gitignored. Explain flashing and how to find each board's MAC.
Also write tools/bridge_echo_test.py: opens the port, checks BRIDGE_STATUS arrives and CRCs are valid.
```
✔ Check: bridge plugged in → `python tools/bridge_echo_test.py COM5` passes; dashboard shows "LOST" (not NO_BRIDGE).

---

### Phase 11 — Firmware: rover_main   (Track B)
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

### Phase 12 — Bench test
```
Write docs/07_BENCH_TEST.md: checklist for the rover on a stand (wheels in the air): each sensor vs
a reference, watchdog (unplug bridge -> motors stop), E-STOP, tilt cut-off, battery calibration,
ESP-NOW range test at 5/10/20/50 m (normal vs Long-Range mode) recording RSSI and loss %.
Include result tables for the course report.
```

---

### FUTURE hardware prompts (when the part arrives — docs/04)

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

### Utility prompts
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

---
