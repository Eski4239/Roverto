# 02 — Telemetry & Command Protocol (v1)

**Single source of truth.** Firmware, simulator and ground station must match this file.
Change it here first, then bump `v` if the change breaks compatibility.

## 1. Envelope

Every message is one JSON object (UTF-8, one per WebSocket text frame):

| Field  | Type   | Meaning                                                    |
|--------|--------|------------------------------------------------------------|
| `v`    | int    | protocol version, currently `1`                            |
| `type` | string | `hello` · `telem` · `scan` · `event` · `cmd` · `ack`       |
| `t`    | int    | sender's time in ms since boot (rover) or since start (GS) |
| `seq`  | int    | per-sender counter, +1 every message (detects packet loss) |

Unknown fields must be **ignored**, not rejected (forward compatibility).
Missing hardware → its block is omitted or its values are `null`. Never send fake `0`.

## 2. Rover → Ground station

### 2.1 `hello` — sent once on every new connection, and every 5 s
Tells the dashboard **which hardware exists**. The UI uses `hw` to decide which panels show data
and which show "NOT INSTALLED".

```json
{"v":1,"type":"hello","t":120,"seq":0,
 "fw":"rover_main 0.1.0","board":"esp32-devkit-v1","reset_reason":"POWERON",
 "hw":{
   "imu":      {"present":true,  "model":"mpu6050"},
   "env":      {"present":true,  "model":"bme280"},
   "light":    {"present":true,  "model":"bh1750"},
   "sonar":    {"present":true,  "model":"hc-sr04", "servo":true},
   "battery":  {"present":true,  "cells":3},
   "current":  {"present":false, "model":"ina219"},
   "encoders": {"present":false, "cpr":20},
   "camera":   {"present":false, "url":"http://192.168.4.2/stream"},
   "lidar":    {"present":false, "model":"ld06"},
   "buzzer":   {"present":true}
 }}
```

`env.model` is detected from the chip ID: `0x60` = `bme280` (has humidity), `0x58` = `bmp280`
(**no humidity** — many cheap boards sold as BME280 are actually BMP280). If it is a BMP280,
`env.hum` is always `null` and the UI shows "humidity: sensor has none".

### 2.2 `telem` — 10 Hz

```json
{"v":1,"type":"telem","t":12345,"seq":88,
 "env":   {"temp_c":22.4, "hum_pct":41.0, "press_hpa":1012.3, "alt_m":21.5},
 "light": {"lux":340},
 "pwr":   {"vbat_v":11.42, "soc_pct":71, "ibat_a":null, "p_w":null},
 "mot":   {"pwm_l":180, "pwm_r":175, "rpm_l":null, "rpm_r":null, "dir_l":1, "dir_r":1},
 "odom":  {"x_m":null, "y_m":null, "dist_m":null},
 "imu":   {"roll_deg":1.2, "pitch_deg":-0.4, "yaw_deg":87.5,
           "ax_g":0.01, "ay_g":-0.02, "az_g":1.00, "gz_dps":0.3, "temp_c":31.2},
 "sonar": {"angle_deg":45, "dist_cm":63},
 "state": {"mode":"manual", "estop":false, "wd_ok":true, "last_cmd_age_ms":40},
 "sys":   {"rssi_dbm":-61, "heap_b":182000, "uptime_s":340, "loop_hz":98, "chip_temp_c":48}}
```

| Block   | Source                         | Notes |
|---------|--------------------------------|-------|
| `env`   | BME280 (now)                   | `alt_m` from pressure, relative to reference set at boot |
| `light` | BH1750                         | lux |
| `pwr`   | divider (now), INA219 (future) | `ibat_a`, `p_w` null until INA219 fitted |
| `mot`   | TB6612 commands (now), encoders (future) | `pwm` −255…255 commanded; `rpm` null until encoders |
| `odom`  | encoders + IMU yaw (future)    | null until encoders |
| `imu`   | MPU-6050                       | yaw drifts (no magnetometer) — expected |
| `sonar` | HC-SR04 on servo               | latest single ping; full sweep goes in `scan` |
| `state` | firmware                       | `mode`: `manual` · `assisted` · `auto` · `idle` |
| `sys`   | ESP32                          | |

### 2.3 `scan` — one complete sweep (sonar now, lidar future)
```json
{"v":1,"type":"scan","t":13000,"seq":95,
 "src":"sonar",                  
 "pose":{"x_m":null,"y_m":null,"yaw_deg":87.5},
 "pts":[[0,120],[10,118],[20,95]]}
```
`src` = `sonar` | `lidar`. `pts` = list of `[angle_deg, dist_cm]` relative to rover front,
`dist_cm = null` for no echo. Lidar (~450 points/rev) may be decimated to 1° steps (360 points,
≈ 4 KB/scan, fine at 10 Hz). Mapping consumes this message later — it is logged from day one.

### 2.4 `event` — whenever something happens
```json
{"v":1,"type":"event","t":14000,"seq":101,"level":"warn","code":"BATT_LOW","msg":"vbat 10.4 V"}
```
`level`: `info` · `warn` · `error`. Codes: `BOOT`, `BATT_LOW`, `BATT_CRIT`, `TILT`, `WD_STOP`,
`ESTOP`, `SENSOR_LOST`, `OBSTACLE`, `CMD_REJECTED`.

## 3. Ground station → Rover

### 3.1 `cmd`
Sent at **10 Hz while the dashboard is connected** (doubles as heartbeat) and immediately on change.

```json
{"v":1,"type":"cmd","t":5000,"seq":42,
 "drive":{"l":0.6,"r":0.6},
 "servo":{"mode":"sweep"},
 "mode":"manual",
 "estop":false,
 "buzzer":null}
```
- `drive.l`, `drive.r`: −1.0…1.0 (fraction of max PWM). Rover clamps.
- `servo.mode`: `sweep` or `fixed` with `"angle_deg":90`.
- `estop: true` latches on the rover; only a cmd with `"estop_reset":true` clears it.
- Future: `"goto":{"x_m":1.0,"y_m":0.5}` for waypoints (mapping phase).

### 3.2 `ack` (rover → GS) for non-drive commands (mode change, estop, estop_reset)
```json
{"v":1,"type":"ack","t":5010,"seq":90,"ack_seq":42,"ok":true}
```

## 4. Safety rules (enforced in firmware, verified in simulator)
1. If `last_cmd_age_ms > 500` → motors to 0, `event WD_STOP`, `state.wd_ok=false`.
2. `estop` latched → motors 0 regardless of `drive`.
3. `pitch` or `roll` > 35° → motors 0, `event TILT`.
4. `vbat_v < 9.9` → `BATT_CRIT`, drive limited to 30 %.

## 5. Rates & bandwidth
| Message | Rate      | Size     | Bandwidth  |
|---------|-----------|----------|------------|
| telem   | 10 Hz     | ~600 B   | 6 KB/s     |
| scan    | 0.5–10 Hz | 0.3–4 KB | ≤ 40 KB/s  |
| cmd     | 10 Hz     | ~150 B   | 1.5 KB/s   |
| video   | 10–15 fps | 8–15 KB  | ≤ 200 KB/s |
All well within ESP32 WiFi capacity; video is the only heavy channel, which is why it runs on a
separate board.
