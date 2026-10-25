// buzzer.h — passive buzzer (D-017) driven with ledcWriteTone, non-blocking note queue.
// Firmware-only cues (no protocol change) + a two-tone siren while CMD_BUZZER is set.
#pragma once
#include "../driver.h"

class BuzzerDriver : public Driver {
 public:
  BuzzerDriver() : Driver("buzzer") {}
  bool begin() override;
  void update() override;
  void fill(TelemMsg&) override {}
  void fillHello(HelloMsg& h) override;

  void playBoot();      // rising jingle at power-on
  void playLinkUp();    // short chirp when commands start arriving
  void playWdStop();    // two falling notes; also cuts the siren and anything queued
  void setSiren(bool on);
  bool sirenOn() const { return siren_; }

 private:
  struct Note { uint16_t freq_hz; uint16_t dur_ms; };  // freq 0 = rest
  static const uint8_t QUEUE_LEN = 16;

  void enqueue(uint16_t freq_hz, uint16_t dur_ms);
  void clearQueue();
  void tone(uint16_t freq_hz);

  Note queue_[QUEUE_LEN];
  uint8_t head_ = 0, count_ = 0;
  bool playing_ = false;
  uint32_t note_end_ms_ = 0;
  bool siren_ = false;
  bool siren_high_ = false;
  bool siren_note_ = false;   // the note playing now belongs to the siren
  uint16_t current_hz_ = 0;
};
