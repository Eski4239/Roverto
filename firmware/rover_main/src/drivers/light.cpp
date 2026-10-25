// light.cpp — BH1750 at 0x23 (ADDR low) or 0x5C (ADDR high), continuous high-resolution mode
// (1 lx, 120 ms per conversion), read at 1 Hz. lux = raw / 1.2 (datasheet).
#include "light.h"
#include <Wire.h>
#include "config.h"

static const uint8_t BH1750_POWER_ON = 0x01;
static const uint8_t BH1750_CONT_HRES = 0x10;

static bool sendCmd(uint8_t addr, uint8_t cmd) {
  Wire.beginTransmission(addr);
  Wire.write(cmd);
  return Wire.endTransmission() == 0;
}

bool LightDriver::begin() {
  const uint8_t candidates[] = {0x23, 0x5C};
  for (uint8_t a : candidates) {
    if (sendCmd(a, BH1750_POWER_ON) && sendCmd(a, BH1750_CONT_HRES)) {
      addr_ = a;
      break;
    }
  }
  present = addr_ != 0;
  // first conversion is ready after ~180 ms; the first update() comes 1 s later
  last_read_ms_ = millis();
  return present;
}

void LightDriver::update() {
  if (!present) return;
  uint32_t now = millis();
  if (now - last_read_ms_ < SLOW_PERIOD_MS) return;
  last_read_ms_ = now;

  if (Wire.requestFrom(addr_, (uint8_t)2) != 2) {
    lux_ = NAN;
    return;
  }
  uint16_t raw = (uint16_t)(Wire.read() << 8);
  raw |= (uint16_t)Wire.read();
  lux_ = raw / 1.2f;
}

void LightDriver::fill(TelemMsg& t) { t.lux = present ? lux_ : NAN; }

void LightDriver::fillHello(HelloMsg& h) {
  if (present) h.hw_present |= (1u << HW_LIGHT);
}
