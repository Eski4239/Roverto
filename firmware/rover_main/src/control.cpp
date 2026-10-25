// control.cpp — mirrors simulator/fake_rover.py apply_cmd() where docs/02 is silent (D-012).
// Battery rules (docs/02 §5 rule 4) and TILT (rule 3) need the battery / IMU drivers: with vbat and
// roll/pitch NaN they can't trigger, so they are added in R4 / R5 together with their drivers.
#include "control.h"
#include <Arduino.h>
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "config.h"
#include "drivers/buzzer.h"
#include "drivers/scanner.h"
#include "messages.h"

void Control::begin(ScannerDriver* scanner, BuzzerDriver* buzzer) {
  scanner_ = scanner;
  buzzer_ = buzzer;
  boot_ms_ = millis();  // the watchdog runs from boot: no command in 500 ms -> WD_STOP (boot transient)
}

bool Control::rejectEventAllowed() {
  uint32_t now = millis();
  if (reject_event_sent_ && now - last_reject_event_ms_ < EVENT_RATE_LIMIT_MS) return false;
  reject_event_sent_ = true;
  last_reject_event_ms_ = now;
  return true;
}

void Control::reject(const char* fmt, ...) {
  rx_rejected_++;
  if (!rejectEventAllowed()) return;
  char text[60];
  va_list args;
  va_start(args, fmt);
  vsnprintf(text, sizeof(text), fmt, args);
  va_end(args);
  msg::sendEvent(EV_WARN, EV_CMD_REJECTED, "%s", text);
}

void Control::handle(const radio::RxFrame& f) {
  // ---- validation (D-010): only a valid CmdMsg feeds the watchdog ----
  const uint8_t* peer = radio::peerMac();
  if (memcmp(f.src_mac, peer, 6) != 0) {
    reject("unknown mac %02X:%02X:%02X:%02X:%02X:%02X", f.src_mac[0], f.src_mac[1], f.src_mac[2],
           f.src_mac[3], f.src_mac[4], f.src_mac[5]);
    return;
  }
  if (f.len != sizeof(CmdMsg)) {
    reject("bad len %u", f.len);
    return;
  }
  CmdMsg c;
  memcpy(&c, f.data, sizeof(c));
  if (c.h.magic != PROTO_MAGIC || c.h.ver != PROTO_VER) {
    reject("bad magic/ver %02X/%u", c.h.magic, c.h.ver);
    return;
  }
  if (c.h.type != MSG_CMD) {
    reject("bad type %02X", c.h.type);
    return;
  }
  if (!isfinite(c.drive_l) || !isfinite(c.drive_r)) {
    reject("drive not finite");
    return;
  }
  if (c.mode > MODE_AUTO) {
    reject("bad mode %u", c.mode);
    return;
  }

  // ---- valid: feeds the watchdog ----
  rx_valid_++;
  have_cmd_ = true;
  last_cmd_ms_ = millis();
  rssi_dbm_ = f.rssi_dbm;
  if (!wd_ok_) {
    wd_ok_ = true;
    wd_stop_sent_ = false;
    if (buzzer_) buzzer_->playLinkUp();
  }

  // E-STOP latch: if one CmdMsg carries both, reset wins (D-012)
  if (c.cmd_flags & CMD_ESTOP) estop_ = true;
  if (c.cmd_flags & CMD_ESTOP_RESET) estop_ = false;
  if (c.cmd_flags & CMD_REQUEST_HELLO) hello_requested_ = true;

  // auto: rejected until navigation exists (docs/02 §5 rule 4b); the rest of the cmd is ignored
  if (c.mode == MODE_AUTO) {
    if (rejectEventAllowed()) msg::sendEvent(EV_WARN, EV_CMD_REJECTED, "auto mode not implemented");
    rx_rejected_++;
    msg::sendAck(c.h.seq, false);
    return;
  }

  // mode and servo apply even while E-STOP is latched; drive does not (D-012)
  mode_ = c.mode;
  if (scanner_) scanner_->setMode(c.servo_mode == 1, c.servo_angle_deg);
  buzzer_cmd_ = (c.cmd_flags & CMD_BUZZER) != 0;
  if (!estop_) {
    drive_l_ = constrain(c.drive_l, -1.0f, 1.0f);
    drive_r_ = constrain(c.drive_r, -1.0f, 1.0f);
  } else {
    drive_l_ = drive_r_ = 0;
  }

  // ack rules (docs/02 §6.8): (a) mode/flags changed vs previous accepted, (b) every 10th seq
  bool rule_a = have_prev_ && (c.mode != prev_mode_ || c.cmd_flags != prev_flags_);
  bool rule_b = c.h.seq % 10 == 0;
  have_prev_ = true;
  prev_mode_ = c.mode;
  prev_flags_ = c.cmd_flags;
  if (rule_a || rule_b) msg::sendAck(c.h.seq, true);
}

void Control::tick() {
  uint32_t now = millis();
  uint32_t since = have_cmd_ ? last_cmd_ms_ : boot_ms_;
  if (now - since <= WATCHDOG_MS) {
    if (buzzer_) buzzer_->setSiren(buzzer_cmd_ && wd_ok_);
    return;
  }
  // docs/02 §5 rule 1: no valid CmdMsg for 500 ms -> stop (motors in R2), silence the buzzer
  bool was_ok = wd_ok_;
  wd_ok_ = false;
  drive_l_ = drive_r_ = 0;
  buzzer_cmd_ = false;
  if (!wd_stop_sent_) {
    wd_stop_sent_ = true;
    msg::sendEvent(EV_WARN, EV_WD_STOP, "no cmd for %u ms", (unsigned)WATCHDOG_MS);
    if (buzzer_) {
      if (was_ok) buzzer_->playWdStop();  // link lost; no sound for the boot transient
      else buzzer_->setSiren(false);
    }
  }
}

uint32_t Control::lastCmdAgeMs() const {
  if (!have_cmd_) return 0xFFFFFFFFu;
  return millis() - last_cmd_ms_;
}

void Control::fill(TelemMsg& t) const {
  t.mode = mode_;
  t.state_flags = (estop_ ? ST_ESTOP : 0) | (wd_ok_ ? ST_WD_OK : 0);
  uint32_t age = lastCmdAgeMs();
  t.last_cmd_age_ms = age > 0xFFFF ? 0xFFFF : (uint16_t)age;  // 65535 = never / very old
  t.rssi_dbm = rssi_dbm_;
}

bool Control::takeHelloRequest() {
  bool r = hello_requested_;
  hello_requested_ = false;
  return r;
}
