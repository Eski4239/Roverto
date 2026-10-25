// golden.cpp — values copied from tools/golden_gen.cpp; keep both in sync.
#include "golden.h"
#include <math.h>
#include <string.h>
#include "rover_protocol.h"

static MsgHeader hdr(uint8_t type, uint16_t seq, uint32_t t) {
  MsgHeader h;
  memset(&h, 0, sizeof(h));
  h.magic = PROTO_MAGIC;
  h.ver = PROTO_VER;
  h.type = type;
  h.flags = 0;
  h.seq = seq;
  h.t_ms = t;
  return h;
}

static void printHex(Print& out, const char* name, const void* p, size_t n) {
  static const char HEX_DIGITS[] = "0123456789abcdef";
  const uint8_t* b = (const uint8_t*)p;
  out.print(name);
  out.print(' ');
  for (size_t i = 0; i < n; i++) {
    out.write(HEX_DIGITS[b[i] >> 4]);
    out.write(HEX_DIGITS[b[i] & 0x0F]);
  }
  out.println();
}

void dumpGolden(Print& out) {
  const float N = NAN;

  TelemMsg t;
  memset(&t, 0, sizeof(t));
  t.h = hdr(MSG_TELEM, 88, 12345);
  t.temp_c = 22.4f; t.hum_pct = 41.0f; t.press_hpa = 1012.3f; t.alt_m = 0.4f; t.lux = 340.0f;
  t.vbat_v = 11.42f; t.soc_pct = 71.0f; t.ibat_a = N; t.p_w = N;
  t.pwm_l = 180; t.pwm_r = 175; t.rpm_l = N; t.rpm_r = N; t.x_m = N; t.y_m = N; t.dist_m = N;
  t.roll_deg = 1.2f; t.pitch_deg = -0.4f; t.yaw_deg = 87.5f; t.ax_g = 0.01f; t.ay_g = -0.02f; t.az_g = 1.0f;
  t.gz_dps = 0.3f; t.imu_temp_c = 31.2f; t.sonar_angle_deg = 45.0f; t.sonar_dist_cm = 63.0f;
  t.mode = MODE_MANUAL; t.state_flags = ST_WD_OK; t.last_cmd_age_ms = 40; t.rssi_dbm = -61;
  t.heap_b = 182000; t.uptime_s = 340; t.loop_hz = 98; t.chip_temp_c = 48.0f;

  CmdMsg c;
  memset(&c, 0, sizeof(c));
  c.h = hdr(MSG_CMD, 42, 5000);
  c.drive_l = 0.6f; c.drive_r = 0.6f; c.mode = MODE_MANUAL;
  c.servo_mode = 0; c.servo_angle_deg = 90; c.cmd_flags = 0; c.goto_x_m = N; c.goto_y_m = N;

  printHex(out, "telem", &t, sizeof(t));
  printHex(out, "cmd", &c, sizeof(c));
}
