# Rover Ground Station — project memory for Claude Code

University project (Space Vehicles & Missiles, Universidad Europea, Year 3).
We are building a small rover (ESP32-based) and a **ground-station dashboard** that runs on any
laptop, receives telemetry + video over WiFi, displays it, and sends commands back.

Read these before doing any work:
- `docs/01_ARCHITECTURE.md` — system overview, network topology, folder layout
- `docs/02_TELEMETRY_PROTOCOL.md` — **single source of truth** for every message
- `docs/03_DASHBOARD_SPEC.md` — panels, behaviour, "not installed" states
- `docs/04_FUTURE_HARDWARE.md` — hardware we don't have yet (software must be ready for it)
- `docs/06_CLAUDE_CODE_PROMPTS.md` — the build sequence we follow

## Hard rules
1. **Protocol first.** Any new field goes into `docs/02_TELEMETRY_PROTOCOL.md` AND
   `ground_station/app/protocol.py` (pydantic models) AND `simulator/fake_rover.py` in the same change.
   Never invent a field in the UI or firmware only.
2. **Hardware is optional.** Every sensor/subsystem can be absent. The rover announces what it has in
   the `hello` message (`hw` capabilities). The UI must show a clear "NOT INSTALLED" placeholder,
   never crash, never show fake zeros. Fields for missing hardware are `null` or the block is omitted.
3. **Safety is never removed.** The rover firmware stops the motors if no valid command/heartbeat
   arrives for 500 ms. The dashboard E-STOP is always visible. Do not weaken either "temporarily".
4. **Simulator parity.** Everything the real rover can send, `simulator/fake_rover.py` can send, with
   CLI flags to enable/disable each hardware item (e.g. `--no-bme280 --encoders --lidar`).
5. **Mapping/navigation is on the back burner.** Keep the map panel and `scan` message as stubs;
   don't build SLAM until we say so.
6. Keep it runnable on Windows, macOS and Linux. Use `pathlib`, no hard-coded absolute paths.

## Stack
- Ground station: Python 3.12, FastAPI + uvicorn, `websockets`, pydantic v2, OpenCV (later), pytest.
- Frontend: plain HTML/CSS/JS served by FastAPI from `ground_station/app/web/` (no build step).
  Charts with uPlot or Chart.js loaded from a local vendored file (must work offline — the laptop
  is on the rover's WiFi with no internet).
- Firmware: PlatformIO + Arduino framework, in `firmware/rover_main/` and `firmware/rover_cam/`.
  WiFi credentials live in `firmware/*/include/secrets.h` (gitignored); commit `secrets.example.h`.

## Commands
- Setup: `py -3.12 -m venv .venv` then `.venv\Scripts\activate` (Windows) / `source .venv/bin/activate`
- Install: `pip install -r ground_station/requirements.txt`
- Run simulator: `python simulator/fake_rover.py`
- Run ground station: `python -m ground_station.app --rover ws://127.0.0.1:8765` (simulator)
  or `--rover ws://192.168.4.1:81` (real rover)
- Tests: `pytest -q`

## Style
- Small modules, type hints, docstrings on public functions. Units in field names or documented.
- Commit messages: imperative, short. One feature per commit.
- When unsure about hardware behaviour, ask instead of guessing.
