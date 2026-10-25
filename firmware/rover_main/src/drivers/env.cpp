// env.cpp — chip-ID detection first (reg 0xD0 at 0x76 / 0x77), then the matching Adafruit driver:
// 0x60 = BME280 (has humidity), 0x58 = BMP280 (hum_pct NaN). Nothing -> not present.
// DHT11 fallback (D-009) is not built: no pin is reserved for it in docs/04 §1.
#include "env.h"
#include <Wire.h>
#include "config.h"

static const uint8_t CHIP_ID_BME280 = 0x60;
static const uint8_t CHIP_ID_BMP280 = 0x58;
static const uint8_t REG_CHIP_ID = 0xD0;

static uint8_t readChipId(uint8_t addr) {
  Wire.beginTransmission(addr);
  Wire.write(REG_CHIP_ID);
  if (Wire.endTransmission(false) != 0) return 0;
  if (Wire.requestFrom(addr, (uint8_t)1) != 1) return 0;
  return Wire.read();
}

bool EnvDriver::begin() {
  const uint8_t candidates[] = {0x76, 0x77};
  for (uint8_t a : candidates) {
    uint8_t id = readChipId(a);
    if (id == 0) continue;
    addr_ = a;
    chip_id_ = id;
    if (id == CHIP_ID_BME280 && bme_.begin(a, &Wire)) model_ = ENV_BME280;
    else if (id == CHIP_ID_BMP280 && bmp_.begin(a, CHIP_ID_BMP280)) model_ = ENV_BMP280;
    break;
  }
  present = model_ != ENV_NONE;
  if (!present) return false;

  // alt_m reference before the first TELEM (GS-4). setup() only, so waiting here is fine:
  // the first normal-mode conversion with the default x16 oversampling takes ~110 ms.
  delay(150);
  float sum = 0;
  uint8_t n = 0;
  for (uint8_t i = 0; i < ENV_ALT_REF_SAMPLES; i++) {
    float t, p, h;
    if (readRaw(t, p, h) && isfinite(p)) {
      sum += p;
      n++;
    }
    delay(40);
  }
  if (n > 0) p0_hpa_ = sum / n;
  update();
  return true;
}

bool EnvDriver::readRaw(float& temp_c, float& press_hpa, float& hum_pct) {
  if (model_ == ENV_BME280) {
    temp_c = bme_.readTemperature();
    press_hpa = bme_.readPressure() / 100.0f;
    hum_pct = bme_.readHumidity();
  } else if (model_ == ENV_BMP280) {
    temp_c = bmp_.readTemperature();
    press_hpa = bmp_.readPressure() / 100.0f;
    hum_pct = NAN;
  } else {
    return false;
  }
  return true;
}

void EnvDriver::update() {
  if (!present) return;
  uint32_t now = millis();
  if (last_read_ms_ != 0 && now - last_read_ms_ < SLOW_PERIOD_MS) return;
  last_read_ms_ = now;

  float t, p, h;
  readRaw(t, p, h);
  temp_c_ = t;
  press_hpa_ = (isfinite(p) && p > 0) ? p : NAN;
  hum_pct_ = h;
  // Same formula as Adafruit readAltitude(), with the boot pressure as "sea level".
  alt_m_ = (isfinite(press_hpa_) && isfinite(p0_hpa_))
               ? 44330.0f * (1.0f - powf(press_hpa_ / p0_hpa_, 0.1903f))
               : NAN;
}

void EnvDriver::fill(TelemMsg& t) {
  t.temp_c = present ? temp_c_ : NAN;
  t.hum_pct = present ? hum_pct_ : NAN;
  t.press_hpa = present ? press_hpa_ : NAN;
  t.alt_m = present ? alt_m_ : NAN;
}

void EnvDriver::fillHello(HelloMsg& h) {
  h.env_model = model_;
  if (present) h.hw_present |= (1u << HW_ENV);
}
