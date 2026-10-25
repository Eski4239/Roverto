// scanner.h — HC-SR04 on an SG90 servo. Sweep mode builds one ScanMsg per pass; fixed mode just
// pings at the commanded angle. Wire angle = raw servo angle 0..180, 90 = front (Q-6 provisional).
#pragma once
#include "../driver.h"

class ScannerDriver : public Driver {
 public:
  static const uint8_t PASS_POINTS = 180 / 10 + 1;  // 19 (SERVO_STEP_DEG = 10)

  ScannerDriver() : Driver("sonar") {}
  bool begin() override;
  void update() override;
  void fill(TelemMsg& t) override;
  void fillHello(HelloMsg& h) override;

  // From the accepted CmdMsg: servo_mode 0 = sweep, 1 = fixed at angle_deg.
  void setMode(bool fixed, uint8_t angle_deg);
  // True once per completed sweep pass; fills everything after the header.
  bool takeScan(ScanMsg& s);

  bool fixedMode() const { return fixed_; }
  uint8_t servoAngle() const { return servo_angle_; }
  uint8_t lastAngle() const { return last_angle_; }
  float lastDistCm() const { return last_dist_cm_; }
  uint32_t pings() const { return pings_; }
  uint32_t timeouts() const { return timeouts_; }
  uint8_t scanId() const { return scan_id_; }

 private:
  enum class State : uint8_t { Settling, Pinging };

  void moveServo(uint8_t angle_deg);
  void startPass(uint8_t start_angle);
  void trigger();
  void onPingResult(float dist_cm);

  State state_ = State::Settling;
  bool started_ = false;           // servo idle until SERVO_START_DELAY_MS after boot
  uint32_t start_at_ms_ = 0;
  bool fixed_ = false;
  uint8_t fixed_angle_ = 90;
  uint8_t servo_angle_ = 90;       // last angle written to the servo (wire convention)
  uint32_t settle_until_ms_ = 0;
  uint32_t last_ping_ms_ = 0;
  int64_t trigger_us_ = 0;

  // sweep pass in progress
  int8_t dir_ = 1;
  bool pass_active_ = false;
  uint16_t pass_cm_[PASS_POINTS];
  float pass_yaw_deg_ = NAN, pass_x_m_ = NAN, pass_y_m_ = NAN;

  // completed pass waiting to be sent
  bool scan_ready_ = false;
  uint8_t scan_id_ = 0;
  uint16_t scan_cm_[PASS_POINTS];
  float scan_yaw_deg_ = NAN, scan_x_m_ = NAN, scan_y_m_ = NAN;

  uint8_t last_angle_ = 90;
  float last_dist_cm_ = NAN;
  uint32_t pings_ = 0, timeouts_ = 0;
};
