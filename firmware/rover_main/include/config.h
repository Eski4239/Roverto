// config.h — pins, periods and thresholds of rover_main. Pin plan: docs/04 §1.
// Safety values come from docs/02 §5; change them there first.
#pragma once
#include <stdint.h>

#define FW_VERSION "rover_main 0.1.0"   // HelloMsg.fw, max 19 chars

// ------------------------------------------------------------------ pins ----
static const int PIN_I2C_SDA = 21;
static const int PIN_I2C_SCL = 22;
static const int PIN_SONAR_TRIG = 5;
static const int PIN_SONAR_ECHO = 19;   // 5 V echo -> 1k/2k divider -> 3.3 V
static const int PIN_SERVO = 18;
static const int PIN_BUZZER = 13;       // passive buzzer (D-017)
// Reserved for later steps (docs/04 §1): TB6612 25/26/27, 32/33/4, STBY 23; battery 34;
// encoders 36/39; LiDAR RX 16.

// ------------------------------------------------------------- scheduler ----
static const uint32_t CONTROL_PERIOD_MS = 10;    // 100 Hz: watchdog (motors later)
static const uint32_t TELEM_PERIOD_MS = 100;     // 10 Hz
static const uint32_t SLOW_PERIOD_MS = 1000;     // 1 Hz: env, light, sys, loop_hz
static const uint32_t HELLO_PERIOD_MS = 5000;
static const uint32_t HELLO_REQUEST_MIN_GAP_MS = 200;  // CMD_REQUEST_HELLO arrives at 10 Hz

// ---------------------------------------------------------------- safety ----
static const uint32_t WATCHDOG_MS = 500;               // docs/02 §5 rule 1
static const uint32_t EVENT_RATE_LIMIT_MS = 1000;      // CMD_REJECTED at most 1/s (D-010)
static const float TILT_LIMIT_DEG = 35.0f;             // docs/02 §5 rule 3 (needs IMU, R4)
static const float TILT_RESUME_DEG = 30.0f;
static const float BATT_LOW_V = 10.5f;                 // docs/02 §5 rule 4 (needs battery, R5)
static const float BATT_CRIT_V = 9.9f;
static const int16_t PWM_MAX = 120;                    // D-013 (needs motors, R2)

// ----------------------------------------------------------------- sonar ----
static const uint32_t SONAR_PING_MIN_GAP_MS = 60;      // HC-SR04 needs ~60 ms between pings
static const uint32_t SONAR_ECHO_TIMEOUT_US = 25000;   // D-005: no echo in 25 ms -> NaN / 0xFFFF
static const float SONAR_US_PER_CM = 58.0f;            // round trip at ~343 m/s

// ----------------------------------------------------------------- servo ----
static const uint32_t SERVO_FREQ_HZ = 50;
static const uint8_t SERVO_RES_BITS = 14;              // must differ from the buzzer (own LEDC timer)
static const uint32_t SERVO_MIN_US = 500;              // pulse at 0 deg
static const uint32_t SERVO_MAX_US = 2400;             // pulse at 180 deg
static const uint8_t SERVO_STEP_DEG = 10;              // sweep 0..180 -> 19 points per pass
static const uint32_t SERVO_SETTLE_BASE_MS = 50;       // settle = base + per_deg * |move|
static const uint32_t SERVO_SETTLE_PER_DEG_MS = 2;
static const uint8_t SERVO_DEFAULT_ANGLE = 90;         // 90 = front (Q-6 provisional)
// 1 if the servo is mounted reversed: the wire angle stays 0 = left, 90 = front, 180 = right;
// only the pulse sent to the servo is mirrored.
#define SERVO_MIRROR 0

// ---------------------------------------------------------------- buzzer ----
static const uint32_t BUZZER_ATTACH_FREQ_HZ = 2000;
static const uint8_t BUZZER_RES_BITS = 10;             // ledcWriteTone uses 10 bits

// ----------------------------------------------------------------- env ----
static const uint8_t ENV_ALT_REF_SAMPLES = 8;          // boot pressure reference for alt_m
