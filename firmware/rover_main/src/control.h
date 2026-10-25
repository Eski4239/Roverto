// control.h — CmdMsg validation + safety core (docs/02 §5, §6.8; D-010, D-012).
// Motors are not fitted yet: drive is validated and stored but never applied (pwm stays 0).
#pragma once
#include "radio.h"
#include "rover_protocol.h"

class ScannerDriver;
class BuzzerDriver;

class Control {
 public:
  void begin(ScannerDriver* scanner, BuzzerDriver* buzzer);
  void handle(const radio::RxFrame& f);   // one received radio frame
  void tick();                            // 100 Hz: watchdog
  void fill(TelemMsg& t) const;           // state block + rssi_dbm
  bool takeHelloRequest();                // CMD_REQUEST_HELLO seen since last call

  uint8_t mode() const { return mode_; }
  bool estopLatched() const { return estop_; }
  bool wdOk() const { return wd_ok_; }
  bool everReceived() const { return have_cmd_; }
  uint32_t lastCmdAgeMs() const;
  uint32_t rxValid() const { return rx_valid_; }
  uint32_t rxRejected() const { return rx_rejected_; }
  float driveL() const { return drive_l_; }
  float driveR() const { return drive_r_; }
  int8_t rssiDbm() const { return rssi_dbm_; }

 private:
  void reject(const char* fmt, ...) __attribute__((format(printf, 2, 3)));
  bool rejectEventAllowed();

  ScannerDriver* scanner_ = nullptr;
  BuzzerDriver* buzzer_ = nullptr;

  uint8_t mode_ = MODE_IDLE;
  bool estop_ = false;
  bool wd_ok_ = false;            // true only once a valid CmdMsg has arrived (like the simulator)
  bool wd_stop_sent_ = false;     // WD_STOP once per transition
  bool have_cmd_ = false;
  bool buzzer_cmd_ = false;
  bool hello_requested_ = false;
  float drive_l_ = 0, drive_r_ = 0;
  int8_t rssi_dbm_ = 0;
  uint32_t boot_ms_ = 0;
  uint32_t last_cmd_ms_ = 0;

  bool have_prev_ = false;        // ack rule (a) is not evaluated on the first CmdMsg (D-012)
  uint8_t prev_mode_ = 0, prev_flags_ = 0;

  bool reject_event_sent_ = false;
  uint32_t last_reject_event_ms_ = 0;
  uint32_t rx_valid_ = 0, rx_rejected_ = 0;
};
