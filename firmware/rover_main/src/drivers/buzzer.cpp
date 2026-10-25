// buzzer.cpp — queued cues play first; the siren runs only while the queue is empty.
#include "buzzer.h"
#include <Arduino.h>
#include "config.h"

static const uint16_t SIREN_LOW_HZ = 650;
static const uint16_t SIREN_HIGH_HZ = 950;
static const uint16_t SIREN_HALF_MS = 250;

bool BuzzerDriver::begin() {
  // Different freq/resolution from the servo -> own LEDC timer, so ledcWriteTone() (which
  // reprograms this channel's timer) can never change the servo's 50 Hz.
  present = ledcAttach(PIN_BUZZER, BUZZER_ATTACH_FREQ_HZ, BUZZER_RES_BITS);
  tone(0);
  return present;
}

void BuzzerDriver::fillHello(HelloMsg& h) {
  if (present) h.hw_present |= (1u << HW_BUZZER);
}

void BuzzerDriver::tone(uint16_t freq_hz) {
  if (!present || freq_hz == current_hz_) return;
  current_hz_ = freq_hz;
  ledcWriteTone(PIN_BUZZER, freq_hz);  // 0 = silent
}

void BuzzerDriver::enqueue(uint16_t freq_hz, uint16_t dur_ms) {
  if (count_ >= QUEUE_LEN) return;
  queue_[(head_ + count_) % QUEUE_LEN] = {freq_hz, dur_ms};
  count_++;
}

void BuzzerDriver::clearQueue() {
  count_ = 0;
  playing_ = false;
  siren_note_ = false;
}

void BuzzerDriver::playBoot() {
  enqueue(1047, 90);   // C6
  enqueue(1319, 90);   // E6
  enqueue(1568, 90);   // G6
  enqueue(2093, 160);  // C7
  enqueue(0, 60);
}

void BuzzerDriver::playLinkUp() {
  enqueue(2637, 60);   // E7
  enqueue(0, 40);
}

void BuzzerDriver::playWdStop() {
  siren_ = false;
  clearQueue();
  enqueue(1568, 150);  // G6
  enqueue(1047, 250);  // C6
  enqueue(0, 60);
}

void BuzzerDriver::setSiren(bool on) {
  siren_ = on;
  if (!on && siren_note_) playing_ = false;  // stop now, don't finish the half-period
}

void BuzzerDriver::update() {
  if (!present) return;
  uint32_t now = millis();
  if (playing_ && (int32_t)(now - note_end_ms_) < 0) return;
  playing_ = false;

  if (count_ > 0) {
    Note n = queue_[head_];
    head_ = (head_ + 1) % QUEUE_LEN;
    count_--;
    tone(n.freq_hz);
    note_end_ms_ = now + n.dur_ms;
    playing_ = true;
    siren_note_ = false;
    return;
  }
  if (siren_) {
    siren_high_ = !siren_high_;
    tone(siren_high_ ? SIREN_HIGH_HZ : SIREN_LOW_HZ);
    note_end_ms_ = now + SIREN_HALF_MS;
    playing_ = true;
    siren_note_ = true;
    return;
  }
  siren_note_ = false;
  tone(0);
}
