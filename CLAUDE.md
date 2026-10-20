# Rover Ground Station — project memory for Claude

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

## Hard rules
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

## Stack
- Ground station: Python 3.12, FastAPI + uvicorn, pydantic v2, pyserial, cobs, numpy, pytest.
- Frontend: plain HTML/CSS/JS in `ground_station/app/web/` (no build step), uPlot vendored.
- Firmware: PlatformIO + Arduino framework (arduino-esp32 3.x), libraries: ArduinoJson (debug only),
  PacketSerial (bridge), Adafruit BME280, BH1750, MPU6050 (or own I2C code), ESP32Servo.
  Projects: `firmware/rover_main`, `firmware/ground_bridge`, `firmware/rover_cam` (future).
  Each has `include/secrets.h` (gitignored: PEER_MAC, ESPNOW_CHANNEL, optional PMK/LMK) and a committed
  `secrets.example.h`. Both include `../common/rover_protocol.h`.

## Commands
- Setup: `py -3.12 -m venv .venv` → `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate`
- Install: `pip install -r ground_station/requirements.txt`
- Simulator: `python simulator/fake_rover.py [--encoders --ina219 --lidar --camera --bmp280 --lossy 5]`
- Ground station (sim): `python -m ground_station.app --link socket://127.0.0.1:8765`
- Ground station (real): `python -m ground_station.app --link COM5` (Windows) / `--link /dev/ttyUSB0`
- Tests: `pytest -q`
- Firmware: `pio run -d firmware/rover_main -t upload` · `pio device monitor -b 115200`

## Style
- Small modules, type hints, docstrings on public functions; units in field names.
- Firmware: no `delay()` in loop, no `String` in hot paths, no heavy work in ESP-NOW callbacks.
- One feature per commit, imperative messages.
- When unsure about hardware behaviour, ask instead of guessing.
