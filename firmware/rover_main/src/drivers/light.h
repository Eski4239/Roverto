// light.h — BH1750 ambient light, own I2C code (no library). Absent -> lux NaN.
#pragma once
#include "../driver.h"

class LightDriver : public Driver {
 public:
  LightDriver() : Driver("light") {}
  bool begin() override;
  void update() override;
  void fill(TelemMsg& t) override;
  void fillHello(HelloMsg& h) override;

  uint8_t address() const { return addr_; }
  float lux() const { return lux_; }

 private:
  uint8_t addr_ = 0;
  uint32_t last_read_ms_ = 0;
  float lux_ = NAN;
};
