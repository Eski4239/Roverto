// stubs.h — hardware not fitted yet (docs/04). present=false, fields NaN (CLAUDE.md rule 2).
// Each one gets replaced by a real driver in its R-step (docs/PROGRESS_ROVER_MAIN.md §2).
#pragma once
#include <math.h>
#include "../driver.h"

struct ImuStub : Driver {          // MPU-6050, R4
  ImuStub() : Driver("imu") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg& t) override {
    t.roll_deg = t.pitch_deg = t.yaw_deg = NAN;
    t.ax_g = t.ay_g = t.az_g = t.gz_dps = t.imu_temp_c = NAN;
  }
};

struct BatteryStub : Driver {      // voltage divider on GPIO34, R5
  BatteryStub() : Driver("battery") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg& t) override { t.vbat_v = t.soc_pct = NAN; }
};

struct MotorsStub : Driver {       // TB6612, R2. Integer PWM: 0 = not driving (nothing is).
  MotorsStub() : Driver("motors") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg& t) override { t.pwm_l = t.pwm_r = 0; }
};

struct EncodersStub : Driver {     // docs/04 §D
  EncodersStub() : Driver("encoders") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg& t) override { t.rpm_l = t.rpm_r = t.x_m = t.y_m = t.dist_m = NAN; }
};

struct CurrentStub : Driver {      // INA219, docs/04 §E
  CurrentStub() : Driver("current") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg& t) override { t.ibat_a = t.p_w = NAN; }
};

struct LidarStub : Driver {        // LD06/LD19, docs/04 §F. No TELEM fields; lidar_model stays NONE.
  LidarStub() : Driver("lidar") {}
  bool begin() override { return present = false; }
  void fill(TelemMsg&) override {}
};
