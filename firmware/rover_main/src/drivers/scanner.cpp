// scanner.cpp — non-blocking HC-SR04 + SG90 (D-005: no pulseIn).
// Ping: 10 us TRIG pulse, then the ECHO edges are timed in a GPIO interrupt; loop() only checks
// whether the echo finished or the 25 ms timeout passed.
// Sweep: 0 -> 180 -> 0 in 10 deg steps. Each step = move servo, wait until it settles, one ping.
// Both ends are pinged in every pass, so each pass has all 19 points; dist_cm[] is indexed by
// angle / 10, so it is always ordered by angle (start_cdeg 0, step_cdeg 1000) whatever the direction.
#include "scanner.h"
#include <Arduino.h>
#include <esp_timer.h>
#include <soc/gpio_reg.h>
#include "config.h"

static const uint16_t NO_ECHO = 0xFFFF;
static_assert(ScannerDriver::PASS_POINTS == 180 / SERVO_STEP_DEG + 1, "PASS_POINTS vs SERVO_STEP_DEG");
static_assert(ScannerDriver::PASS_POINTS <= SCAN_MAX_PTS, "sweep must fit in one ScanMsg");

// ---------------------------------------------------------------- echo ISR ----
static volatile bool echo_armed = false;   // only the ping we triggered counts
static volatile bool echo_done = false;
static volatile int64_t echo_rise_us = 0;
static volatile int64_t echo_fall_us = 0;

static inline bool echoHigh() { return (REG_READ(GPIO_IN_REG) >> PIN_SONAR_ECHO) & 1; }

static void IRAM_ATTR onEchoEdge() {
  if (!echo_armed) return;
  int64_t now = esp_timer_get_time();
  if (echoHigh()) {
    echo_rise_us = now;
  } else if (echo_rise_us != 0) {
    echo_fall_us = now;
    echo_done = true;
    echo_armed = false;
  }
}

// --------------------------------------------------------------- driver ----
bool ScannerDriver::begin() {
  pinMode(PIN_SONAR_TRIG, OUTPUT);
  digitalWrite(PIN_SONAR_TRIG, LOW);
  pinMode(PIN_SONAR_ECHO, INPUT);
  attachInterrupt(digitalPinToInterrupt(PIN_SONAR_ECHO), onEchoEdge, CHANGE);

  // Different freq/resolution from the buzzer -> the LEDC allocator gives the servo its own timer.
  ledcAttach(PIN_SERVO, SERVO_FREQ_HZ, SERVO_RES_BITS);
  startPass(0);  // power-on default = sweep, like the simulator

  // An HC-SR04 can't be detected without an echo; it is part of this build's hardware (docs/04).
  present = true;
  return true;
}

void ScannerDriver::moveServo(uint8_t angle_deg) {
  if (angle_deg > 180) angle_deg = 180;
  uint8_t delta = angle_deg > servo_angle_ ? angle_deg - servo_angle_ : servo_angle_ - angle_deg;
  servo_angle_ = angle_deg;
#if SERVO_MIRROR
  uint32_t phys = 180 - angle_deg;
#else
  uint32_t phys = angle_deg;
#endif
  uint32_t pulse_us = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * phys / 180;
  uint32_t period_us = 1000000 / SERVO_FREQ_HZ;
  ledcWrite(PIN_SERVO, pulse_us * ((1u << SERVO_RES_BITS) - 1) / period_us);
  settle_until_ms_ = millis() + SERVO_SETTLE_BASE_MS + SERVO_SETTLE_PER_DEG_MS * delta;
  state_ = State::Settling;
}

void ScannerDriver::startPass(uint8_t start_angle) {
  dir_ = start_angle == 0 ? 1 : -1;
  for (uint8_t i = 0; i < PASS_POINTS; i++) pass_cm_[i] = NO_ECHO;
  pass_yaw_deg_ = NAN;  // pose at the start of the scan (docs/02 §6.7); no IMU / odometry yet
  pass_x_m_ = NAN;
  pass_y_m_ = NAN;
  pass_active_ = true;
  moveServo(start_angle);
}

void ScannerDriver::setMode(bool fixed, uint8_t angle_deg) {
  if (angle_deg > 180) angle_deg = 180;
  if (fixed) {
    bool changed = !fixed_ || angle_deg != fixed_angle_;
    fixed_ = true;
    fixed_angle_ = angle_deg;
    pass_active_ = false;  // abort the pass in progress, no partial ScanMsg
    if (changed && state_ == State::Settling) moveServo(fixed_angle_);
    // if a ping is in flight, update() moves the servo once it finishes
  } else if (fixed_) {
    fixed_ = false;
    if (state_ == State::Settling) startPass(servo_angle_ <= 90 ? 0 : 180);
    else pass_active_ = false;  // update() starts the pass after the ping in flight
  }
}

void ScannerDriver::trigger() {
  echo_done = false;
  echo_rise_us = 0;
  echo_fall_us = 0;
  echo_armed = true;
  digitalWrite(PIN_SONAR_TRIG, HIGH);
  delayMicroseconds(10);  // datasheet trigger pulse; 10 us is not a loop delay
  digitalWrite(PIN_SONAR_TRIG, LOW);
  trigger_us_ = esp_timer_get_time();
  last_ping_ms_ = millis();
  pings_++;
  state_ = State::Pinging;
}

void ScannerDriver::onPingResult(float dist_cm) {
  last_angle_ = servo_angle_;
  last_dist_cm_ = dist_cm;

  if (fixed_) {
    if (servo_angle_ != fixed_angle_) moveServo(fixed_angle_);
    else state_ = State::Settling;  // settle_until already passed -> next ping after the gap
    return;
  }
  if (!pass_active_) {  // came back from fixed mode while this ping was in flight
    startPass(servo_angle_ <= 90 ? 0 : 180);
    return;
  }

  uint8_t idx = servo_angle_ / SERVO_STEP_DEG;
  if (idx < PASS_POINTS) {
    pass_cm_[idx] = isfinite(dist_cm) ? (uint16_t)lroundf(dist_cm) : NO_ECHO;
  }
  bool at_end = (dir_ > 0 && servo_angle_ >= 180) || (dir_ < 0 && servo_angle_ == 0);
  if (at_end) {
    memcpy(scan_cm_, pass_cm_, sizeof(scan_cm_));
    scan_yaw_deg_ = pass_yaw_deg_;
    scan_x_m_ = pass_x_m_;
    scan_y_m_ = pass_y_m_;
    scan_id_++;
    scan_ready_ = true;
    startPass(servo_angle_);  // reverse: the end point is pinged again as the first of the new pass
  } else {
    moveServo(servo_angle_ + dir_ * SERVO_STEP_DEG);
  }
}

void ScannerDriver::update() {
  uint32_t now_ms = millis();
  if (state_ == State::Pinging) {
    if (echo_done) {
      onPingResult((float)(echo_fall_us - echo_rise_us) / SONAR_US_PER_CM);
    } else if (esp_timer_get_time() - trigger_us_ > (int64_t)SONAR_ECHO_TIMEOUT_US) {
      echo_armed = false;
      timeouts_++;
      onPingResult(NAN);
    }
    return;
  }
  // Settling: ping once the servo is there, the HC-SR04 gap has passed and the
  // previous echo line is low again (no-echo modules keep it high ~38 ms).
  if ((int32_t)(now_ms - settle_until_ms_) < 0) return;
  if (now_ms - last_ping_ms_ < SONAR_PING_MIN_GAP_MS) return;
  if (echoHigh()) return;
  trigger();
}

bool ScannerDriver::takeScan(ScanMsg& s) {
  if (!scan_ready_) return false;
  scan_ready_ = false;
  s.src = SCAN_SONAR;
  s.scan_id = scan_id_;
  s.part = 0;
  s.parts = 1;
  s.yaw_deg = scan_yaw_deg_;
  s.x_m = scan_x_m_;
  s.y_m = scan_y_m_;
  s.start_cdeg = 0;
  s.step_cdeg = SERVO_STEP_DEG * 100;
  s.n = PASS_POINTS;
  memcpy(s.dist_cm, scan_cm_, sizeof(scan_cm_));
  return true;
}

void ScannerDriver::fill(TelemMsg& t) {
  t.sonar_angle_deg = last_angle_;
  t.sonar_dist_cm = last_dist_cm_;
}

void ScannerDriver::fillHello(HelloMsg& h) {
  if (present) h.hw_present |= (1u << HW_SONAR) | (1u << HW_SERVO);
}
