# 01 — System Architecture

## 1. Overview

```
 ┌──────────────────────── ROVER ────────────────────────┐        ┌──────────── LAPTOP (ground station) ────────────┐
 │                                                       │        │                                                 │
 │  ESP32 #1  "rover_main"  (WiFi Access Point)          │  WiFi  │  Python backend (FastAPI)                       │
 │   ├─ TB6612FNG → 2× TT motors                         │◄──────►│   ├─ rover_link   (WebSocket client to rover)   │
 │   ├─ MPU-6050 IMU            (I2C)                    │  WS    │   ├─ protocol     (pydantic models, validation) │
 │   ├─ BME280 temp/hum/press   (I2C)                    │  :81   │   ├─ state        (latest values + history)     │
 │   ├─ BH1750 light            (I2C)                    │        │   ├─ logger       (CSV/SQLite per session)      │
 │   ├─ HC-SR04 on SG90 servo   (sweep)                  │        │   ├─ video        (MJPEG proxy / OpenCV) [later]│
 │   ├─ Battery voltage divider (ADC1)                   │        │   ├─ mapping      (stub)            [back burner]│
 │   ├─ Buzzer                                           │        │   └─ web server → browser UI (localhost:8000)   │
 │   ├─ [FUTURE] wheel encoders (interrupt GPIO)         │        │                                                 │
 │   ├─ [FUTURE] INA219 current sensor (I2C)             │  HTTP  │  Browser dashboard (any OS, any browser)        │
 │   └─ [FUTURE] LiDAR (UART2)                           │  MJPEG │   video · map · env · health · control · log    │
 │                                                       │◄──────►│                                                 │
 │  ESP32-CAM "rover_cam" [FUTURE] (joins rover AP)      │  :80   │  simulator/fake_rover.py  (replaces the rover   │
 │   └─ MJPEG stream  http://192.168.4.2/stream          │        │   during development, same protocol)            │
 │                                                       │        │                                                 │
 │  ESP32 #2 — spare (later: offload motors/lidar)       │        │                                                 │
 └───────────────────────────────────────────────────────┘        └─────────────────────────────────────────────────┘
```

## 2. Network topology — rover is the Access Point

- `rover_main` creates WiFi network `ROVER-AP` (WPA2, password in `secrets.h`), fixed IP `192.168.4.1`.
- Laptop joins `ROVER-AP`. ESP32-CAM joins it as a station with static IP `192.168.4.2`.
- Why not campus WiFi: eduroam is WPA2-Enterprise (ESP32 support is painful) and university networks
  usually isolate clients, so laptop ↔ rover traffic would be blocked. AP mode works anywhere, including
  the demo room.
- Consequence: the laptop has no internet while connected → **all frontend libraries are vendored locally**.

| Channel   | Direction       | Transport           | Endpoint                    | Rate        |
|-----------|-----------------|---------------------|-----------------------------|-------------|
| Telemetry | rover → laptop  | WebSocket, JSON     | `ws://192.168.4.1:81`       | 10 Hz       |
| Scans     | rover → laptop  | same WebSocket      | (msg type `scan`)           | per sweep   |
| Commands  | laptop → rover  | same WebSocket      | (msg type `cmd`)            | 10 Hz + on change |
| Video     | rover → laptop  | HTTP MJPEG          | `http://192.168.4.2/stream` | 10–15 fps   |
| Browser   | backend → UI    | WebSocket, JSON     | `ws://localhost:8000/ws/ui` | 10 Hz       |

The browser never talks to the rover directly. The backend is the only client of the rover, so
logging, validation and (later) mapping all happen in one place.

## 3. Repository layout

```
rover-software/
├─ CLAUDE.md
├─ README.md
├─ .gitignore
├─ docs/                       ← these planning docs
├─ ground_station/
│  ├─ requirements.txt
│  └─ app/
│     ├─ __main__.py           ← CLI entry: python -m ground_station.app
│     ├─ main.py               ← FastAPI app, routes, UI websocket
│     ├─ protocol.py           ← pydantic models (mirror of docs/02)
│     ├─ rover_link.py         ← connects to rover WS, reconnects, sends cmds/heartbeat
│     ├─ state.py              ← latest telemetry, capability manifest, ring-buffer history
│     ├─ logger.py             ← session logs (logs/YYYYMMDD_HHMMSS/*.csv + raw.jsonl)
│     ├─ replay.py             ← replays raw.jsonl as if it were a rover
│     ├─ video.py              ← [later] MJPEG proxy + frame grabber
│     ├─ mapping/              ← [back burner] stub module, interface only
│     └─ web/                  ← index.html, css/, js/, vendor/ (chart lib, offline)
├─ simulator/
│  └─ fake_rover.py            ← WS server on :8765 speaking the protocol, hardware flags
├─ firmware/
│  ├─ rover_main/              ← PlatformIO project (ESP32 DevKit V1)
│  └─ rover_cam/               ← PlatformIO project (ESP32-CAM) [future]
├─ tests/
└─ logs/                       ← gitignored
```

## 4. Software layers on the rover (`rover_main`)

Each hardware item is a **driver module** with the same interface, so missing hardware is just a
module that reports `present=false`:

```cpp
struct Driver {
  const char* name;      // "bme280", "encoders", ...
  bool begin();          // returns false if hardware not detected
  bool present;          // set from begin()
  void update();         // called from loop at its own rate
  void toJson(JsonObject& out); // writes its block, or nothing if !present
};
```

Main loop tasks (non-blocking, `millis()`-based):
- 100 Hz: motor control, watchdog check, encoder RPM (future)
- 50 Hz: IMU read + complementary filter (roll/pitch/yaw)
- 10 Hz: build + send `telem`
- 1 Hz: BME280, BH1750, battery, system stats
- servo sweep step + HC-SR04 ping every ~60 ms → `scan` when a sweep completes

## 5. Power notes that affect software
- Battery: 3S Li-ion 9.0–12.6 V → divider 100 kΩ / 33 kΩ → ≤ 3.13 V on **GPIO34/35/36/39 (ADC1)**.
  ADC2 pins do not work while WiFi is on. ESP32 ADC is non-linear: calibrate with a multimeter at
  3 points, store the correction in firmware.
- Report `vbat` and a % estimate from a Li-ion discharge table (not linear).
- WiFi TX + motors starting can brown out the ESP32; firmware reports `reset_reason` in `hello`
  so the dashboard can flag brownout resets.
