# Rover Ground Station

Telemetry dashboard + firmware for our Space Vehicles & Missiles rover (ESP32).

**Start here**
1. `docs/05_VSCODE_SETUP.md` — install VS Code, Claude Code, Python, create the repo
2. `docs/06_CLAUDE_CODE_PROMPTS.md` — build the project phase by phase with Claude Code
3. `CLAUDE.md` — rules Claude Code follows in this repo

**Sharing with a teammate's Claude:** give them `docs/TEAM_BRIEF.md` (everything in one file).
Regenerate it after editing any doc: `python tools/build_brief.py`.

**Design docs**
- `docs/01_ARCHITECTURE.md` — system, network, folder layout
- `docs/02_TELEMETRY_PROTOCOL.md` — message formats (source of truth)
- `docs/03_DASHBOARD_SPEC.md` — panels and behaviour
- `docs/04_FUTURE_HARDWARE.md` — hardware roadmap, pin plan, shopping list

## Run instructions

```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r ground_station/requirements.txt
pytest -q
```

(macOS/Linux: `source .venv/bin/activate` instead of the `.venv\Scripts\activate` line.)

Once the simulator and backend exist (Phase 2–3):
```
python simulator/fake_rover.py [--encoders --ina219 --lidar --camera --bmp280 --lossy 5]
python -m ground_station.app --link socket://127.0.0.1:8765
```
With real hardware: `python -m ground_station.app --link COM5` (Windows) / `--link /dev/ttyUSB0`.

MAC addresses (see docs/PROGRESS_ROVER_MAIN.md §0):
- Rover (rover_main): 20:50:0D:07:83:14
- Ground station (ground_bridge): 20:50:0D:00:7D:FC
