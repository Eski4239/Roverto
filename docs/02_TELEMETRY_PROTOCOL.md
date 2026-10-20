# 02 — Telemetry & Command Protocol (v1)

**Single source of truth.** Three layers:

| Layer | Where | Defined in |
|-------|-------|-----------|
| Logical (JSON) | Python state, logs, UI, tests | §2–3 of this file + `ground_station/app/protocol.py` |
| Wire (binary, ESP-NOW) | rover_main ⇄ ground_bridge | `firmware/common/rover_protocol.h` + `ground_station/app/wire.py` |
| Serial framing (USB) | ground_bridge ⇄ laptop | §4 of this file |

A field change must update **all of**: this file, `rover_protocol.h`, `wire.py`, `protocol.py`,
`simulator/fake_rover.py`, the firmware drivers that fill/read the field, and the golden files
(`tools/golden_gen.cpp` → `tests/golden/`) — in one commit.

## 1. Conventions
- Wire: little-endian, packed, ≤ 250 bytes per message, header `MsgHeader` (magic `0xA7`, ver, type,
  flags, seq u16, t_ms u32).
- `NaN` (wire) ⇔ `null` (JSON) = no data / hardware not installed. **Never send fake 0.**
- Distances in arrays: `0xFFFF` (wire) ⇔ `null` (JSON).
- `seq` per sender, +1 per message, wraps at 65535 → packet loss detection.
- Unknown JSON fields are ignored; unknown wire `type` is logged and dropped.

## 2. Rover → Ground station (logical JSON)

### 2.1 `hello` — on boot, every 5 s, and when requested
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

### 2.2 `telem` — 10 Hz. Wire: `TelemMsg` (129 B)

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

### 2.3 `scan` — one complete sweep / revolution. Wire: `ScanMsg`, fragmented
```json
{"v":1,"type":"scan","t":13000,"seq":95,"src":"sonar","scan_id":12,
 "pose":{"x_m":null,"y_m":null,"yaw_deg":87.5},
 "pts":[[0,120],[10,118],[20,null]]}
```
- `pts` = `[angle_deg, dist_cm]`, rover frame, 0° = front, counter-clockwise positive.
- Wire: up to 100 points per fragment (`part`/`parts`, same `scan_id`). Python reassembles; if a
  fragment is missing after 300 ms the scan is emitted with the missing angles as `null`.
- Sonar sweep (e.g. 0–180° in 10° steps = 19 pts) fits in one fragment; lidar 360 pts → 4 fragments.

### 2.4 `event`. Wire: `EventMsg`
```json
{"v":1,"type":"event","t":14000,"seq":101,"level":"warn","code":"BATT_LOW","msg":"vbat 10.4 V"}
```
Codes: BOOT, BATT_LOW, BATT_CRIT, TILT, WD_STOP, ESTOP, SENSOR_LOST, OBSTACLE, CMD_REJECTED.

### 2.5 `ack`. Wire: `AckMsg` — rules in §6.8
```json
{"v":1,"type":"ack","t":5010,"seq":90,"ack_seq":42,"ok":true}
```

## 3. Ground station → Rover

### 3.1 `cmd` — 10 Hz while the dashboard runs (this IS the heartbeat). Wire: `CmdMsg` (30 B)
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

### 3.2 Ground-station-only data (never on the radio)
The backend adds a `link` block to the UI snapshot:
```json
"link":{"state":"OK","rx_hz":10.0,"loss_pct":0.4,"rtt_ms":23,
        "rssi_bridge_dbm":-58,"rssi_rover_dbm":-61,"bridge_tx_fail":3,"serial_port":"COM5"}
```
`state`: OK (< 300 ms since last telem) · STALE (300 ms–2 s) · LOST (> 2 s) · NO_BRIDGE (serial port missing).

## 4. Serial framing (ground_bridge ⇄ laptop)

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

### Python struct formats (must match `rover_protocol.h`, verified sizes)
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

## 5. Safety rules (enforced in rover_main, mirrored in the simulator)
1. No valid CmdMsg for **500 ms** → motors 0, event WD_STOP, `wd_ok=false`. (Laptop crash, bridge
   unplugged, out of range — all end here.)
2. `estop` latched → motors 0 regardless of drive, until `estop_reset`.
3. |roll| or |pitch| > 35° → motors 0, event TILT.
4. `vbat_v` < 9.9 V → BATT_CRIT, drive limited to 30 %.
5. CmdMsg with wrong magic/version or from an unknown MAC → ignored, CMD_REJECTED event (rate-limited).

## 6. Clarifications (decided after the Phase 0 review, 2026-10-20)

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
