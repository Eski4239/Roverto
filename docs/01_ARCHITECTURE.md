# 01 — System Architecture

## 1. Overview

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

## 2. Link details

### 2.1 ESP-NOW (rover_main ⇄ ground_bridge)
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

### 2.2 USB serial (ground_bridge ⇄ laptop)
- 921600 baud, 8N1 (fallback 460800 if the USB chip complains).
- Frames: `COBS(kind | rssi | payload | crc16)` + `0x00` delimiter (see docs/02 §4).
- The bridge is **transparent**: it does not decode telemetry, so protocol changes never require
  re-flashing it. It only adds RX RSSI and sends a 1 Hz `BridgeStatus`.

### 2.3 Rates & bandwidth
| Message | Direction | Rate | Bytes | Load |
|---------|-----------|------|-------|------|
| TELEM   | rover → GS | 10 Hz | 129 | 1.3 KB/s |
| SCAN sonar | rover → GS | ~0.5 Hz | ~70 | tiny |
| SCAN lidar (future) | rover → GS | 10 Hz × 4 parts | 231 | 9 KB/s |
| HELLO | rover → GS | 0.2 Hz | 38 | tiny |
| CMD | GS → rover | 10 Hz | 30 | 0.3 KB/s |
| Video (future) | cam → laptop | 10–15 fps | 8–15 KB/frame | ≤ 200 KB/s over WiFi |

## 3. Logical vs. wire protocol
- **Wire protocol** = binary C structs on the radio (`rover_protocol.h`, mirrored in Python `wire.py`).
- **Logical protocol** = the JSON messages in docs/02 §2–3. Python decodes every binary frame into
  these pydantic models immediately. Everything above the link layer (state, logging, UI, simulator
  tests, future mapping) only sees the logical JSON. `NaN` on the wire → `null` in JSON.

## 4. Repository layout

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

## 5. Firmware structure

### 5.1 rover_main
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

### 5.2 ground_bridge
- Serial RX → COBS decode → CRC check → `esp_now_send(rover_mac, payload)`.
- ESP-NOW RX callback → push `(rssi, bytes)` into a FreeRTOS queue → loop COBS-encodes to serial.
- 1 Hz `BridgeStatus`. Onboard LED (GPIO2) blinks on RX. Never invents commands.

## 6. Power notes that affect software
- Battery 3S Li-ion 9.0–12.6 V → divider 100 kΩ / 33 kΩ → ≤ 3.13 V on **GPIO34 (ADC1)**.
  (ADC2 pins are unusable while the radio is on.) Calibrate against a multimeter at 2–3 points.
- SoC from a Li-ion lookup table, low-pass filtered.
- Radio TX + motor start can brown out the ESP32 → `reset_reason` in HELLO; dashboard flags brownouts.
- The ground_bridge is powered by the laptop USB — no battery concerns.
