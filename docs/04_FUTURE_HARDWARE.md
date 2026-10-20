# 04 — Hardware Roadmap: now, next, future

The software is built so every item below can be plugged in later **without changing the protocol
or the dashboard** — only a firmware driver gets enabled and `hello.hw.<item>.present` becomes `true`.
Prices are rough estimates (Oct 2026), check before buying.

## 0. Status overview

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

## 1. Pin reservation (ESP32 DevKit V1, `rover_main`)
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

## 2. Implementation steps

### A. BME280 (now)
1. Buy a module **explicitly marked BME280** (BMP280 has no humidity). Wire to I2C, 3.3 V.
2. Firmware: driver reads chip ID → `hw.env.model` = `bme280` / `bmp280`. Read at 1 Hz.
3. Set pressure reference at boot → `alt_m` relative altitude.
4. Keep the DHT11 as a fallback driver (`hw.env.model:"dht11"`, `press_hpa:null`).
5. ✔ Test: breathe on it → humidity rises; lift 1 m → `alt_m` changes ~ +1 m (noisy, ±0.5 m).

### B. Battery voltage divider (now)
1. 100 kΩ (top) / 22 kΩ (bottom) (D-002: keeps 12.6 V at 2.27 V, inside the accurate ADC range) from battery + to GND, mid-point → GPIO34. 100 nF cap mid-point → GND.
2. Firmware: average 16 samples, `analogReadMilliVolts()`, multiply by (122/22), then a 2-point
   calibration against a multimeter (9.5 V and 12.4 V).
3. SoC from a 3S Li-ion lookup table (not linear). Low-pass filter so it doesn't jump when motors start.
4. ✔ Test: dashboard reading within ±0.1 V of the multimeter across the range.

### C. ESP32-CAM (future)
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

### D. Wheel encoders (future)
Option 1 (cheap, keeps TT motors): LM393 slotted optical sensor + 20-slot disc per wheel.
Option 2 (better): TT/N20/JGA25 motors with built-in Hall encoders (more counts, direction-aware).
1. Mount, wire signal → GPIO36/39, 3.3 V supply.
2. Firmware: interrupt counter with debounce (ignore pulses < 1 ms apart), RPM over a 100 ms window.
   Optical sensors don't know direction → take sign from the commanded `pwm_l/pwm_r`.
3. `odom`: differential-drive equations using wheel radius + track width (measure them, put in config),
   heading from IMU yaw fused with encoder difference.
4. Unlocks: closed-loop speed (PID per wheel) so the rover drives straight.
5. ✔ Test: drive 2.00 m measured with tape → `odom.dist_m` within 5 %.

### E. INA219 (future)
1. Insert in series with battery + after the BMS (max 3.2 A with the stock 0.1 Ω shunt — check your
   peak motor current; use a 0.01 Ω shunt module if higher).
2. Firmware: I2C 0x40, read bus V, current, power at 10 Hz. It also gives a better `vbat_v` than the divider.
3. Ground station: integrate current → mAh used; estimate remaining runtime.
4. ✔ Test: wheels free vs. wheels blocked → current clearly rises; matches multimeter ±10 %.

### F. LiDAR (future — mapping is on the back burner)
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

### G. Second 5 V regulator (future, with C or F)
One MP1584EN for ESP32 + logic, a second one for camera + lidar + servo. Prevents brownouts and
servo noise resetting the ESP32. Add 470 µF on each 5 V rail.

## 3. Future shopping list (copy into LISTA)
- [ ] BME280 module (verify it's BME, not BMP) — **buy now**
- [ ] ESP32-CAM AI-Thinker + ESP32-CAM-MB programmer
- [ ] 2× LM393 slotted speed sensor + 20-slot encoder discs (or encoder motors)
- [ ] INA219 module
- [ ] LDROBOT LD06 or LD19 LiDAR
- [ ] 1× MP1584EN extra + 2× 470 µF capacitors
- [ ] Resistors for dividers: 100 k, 22 k, 1 k, 2 k (probably on hand)
