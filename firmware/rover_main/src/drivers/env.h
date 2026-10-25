// env.h — BME280 / BMP280 temperature, humidity, pressure (D-009, GS-4).
#pragma once
#include <Adafruit_BME280.h>
#include <Adafruit_BMP280.h>
#include "../driver.h"

class EnvDriver : public Driver {
 public:
  EnvDriver() : Driver("env") {}
  bool begin() override;
  void update() override;
  void fill(TelemMsg& t) override;
  void fillHello(HelloMsg& h) override;

  uint8_t model() const { return model_; }      // EnvModel
  uint8_t address() const { return addr_; }
  uint8_t chipId() const { return chip_id_; }   // raw reg 0xD0, 0 if nothing answered

 private:
  bool readRaw(float& temp_c, float& press_hpa, float& hum_pct);

  Adafruit_BME280 bme_;
  Adafruit_BMP280 bmp_;
  uint8_t model_ = ENV_NONE;
  uint8_t addr_ = 0;
  uint8_t chip_id_ = 0;
  float p0_hpa_ = NAN;        // pressure at boot = alt_m reference
  uint32_t last_read_ms_ = 0;
  float temp_c_ = NAN, hum_pct_ = NAN, press_hpa_ = NAN, alt_m_ = NAN;
};
