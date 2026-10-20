# 03 — Dashboard Specification

Browser UI served by the backend at `http://localhost:8000`. Dark theme by default (readable in a
dim demo room), works at 1366×768 laptop resolution, no internet required.

## 1. Layout

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

## 2. Panel behaviour

| Panel        | Data                        | Update | Notes |
|--------------|-----------------------------|--------|-------|
| Top bar      | `link` (docs/02 §3.2), `sys`, `pwr`, `state` | 10 Hz | Link state: OK / STALE / LOST / NO_BRIDGE (USB bridge unplugged → show "Plug in ground bridge" and a serial-port picker). RSSI both directions: rover's view of our commands (↑) and bridge's view of the rover (↓). Loss % from `seq` gaps, RTT from cmd→ack, bridge TX failures. |
| Video        | MJPEG via backend proxy `/video` from `camera_url` (ESP32-CAM AP) | stream | Overlay: heading, sonar distance, "STALE" if no frame for 1 s. If the laptop isn't on the ROVER-CAM WiFi, say so. |
| Map          | `scan`                       | per scan | Phase 1: polar plot of the last sweep. Mapping later. |
| Environment  | `env`, `light`               | 1 Hz shown | Value + unit + sparkline (last 5 min) + min/max of session |
| Rover health | `mot`, `imu`, `sonar`, `pwr`, `sys` | 10 Hz | Colour thresholds below |
| Control      | sends `cmd`                  | 10 Hz  | Keys only active when page focused; releasing keys → 0 |
| Event log    | `event` + backend events     | on event | Newest on top, warn/error highlighted |

### Hardware-absent behaviour (key requirement)
When `hello.hw.<item>.present == false`, the related widgets render a greyed card with
**"NOT INSTALLED — see docs/04_FUTURE_HARDWARE.md"**. When a value is `null` but the hardware is
present, show **"—"** and a "no data" tooltip. When the link is LOST, all values freeze, turn grey
and show their age ("12 s ago").

### Thresholds (configurable in `ground_station/app/config.toml`)
| Value            | Green     | Amber          | Red        |
|------------------|-----------|----------------|------------|
| vbat_v (3S)      | > 11.1    | 10.5–11.1      | < 10.5     |
| roll/pitch       | < 20°     | 20–30°         | > 30°      |
| rssi_dbm         | > −67     | −67…−80        | < −80      |
| sonar dist_cm    | > 50      | 20–50          | < 20       |
| last_cmd_age_ms  | < 200     | 200–500        | > 500      |
| chip_temp_c      | < 60      | 60–75          | > 75       |

## 3. Controls & safety in the UI
- **E-STOP**: always visible, also bound to `Space`. Sends `estop:true` immediately (3 times, 50 ms
  apart). Reset needs a confirm click → `estop_reset:true`.
- Drive: `W/S` forward/back, `A/D` turn, `Shift` = boost to speed limit. Gamepad via the browser
  Gamepad API (optional, later).
- If the browser tab loses focus or closes → backend stops sending drive values (sends zeros) →
  rover watchdog is the final backstop.

## 4. Recording & replay
- Every session writes `logs/<timestamp>/raw.jsonl` (every message, both directions, with laptop
  receive time) plus convenience CSVs (`telem.csv`, `events.csv`).
- `python -m ground_station.app --replay logs/<timestamp>/raw.jsonl` feeds the UI from the log —
  essential for the report/demo and for developing mapping later from real data.
- Export button: download the current session's CSVs.

## 5. Out of scope for now
- Mapping/SLAM, path planning, autonomy (map panel is a stub).
- Multi-user / remote access over the internet.
