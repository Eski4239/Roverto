// golden_gen.cpp — writes tests/golden/*.hex from the REAL C structs in rover_protocol.h.
// Build & run on a PC:  g++ -std=c++17 -I firmware/common tools/golden_gen.cpp -o golden_gen && ./golden_gen tests/golden
// These bytes are the independent reference for ground_station/app/wire.py.
#include "rover_protocol.h"
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

static std::string dir;
static void dump(const char* name, const void* p, size_t n) {
  std::string path = dir + "/" + name + ".hex";
  FILE* f = fopen(path.c_str(), "w");
  const uint8_t* b = (const uint8_t*)p;
  for (size_t i = 0; i < n; i++) fprintf(f, "%02x", b[i]);
  fprintf(f, "\n");
  fclose(f);
  printf("%-16s %3zu bytes\n", name, n);
}
static MsgHeader hdr(uint8_t type, uint16_t seq, uint32_t t) {
  MsgHeader h{}; h.magic = PROTO_MAGIC; h.ver = PROTO_VER; h.type = type; h.flags = 0; h.seq = seq; h.t_ms = t; return h;
}
static uint16_t crc16_ccitt_false(const uint8_t* d, size_t n) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < n; i++) { crc ^= (uint16_t)d[i] << 8;
    for (int k = 0; k < 8; k++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1; }
  return crc;
}
static std::vector<uint8_t> cobs(const std::vector<uint8_t>& in) {
  std::vector<uint8_t> out; out.push_back(0); size_t code_i = 0; uint8_t code = 1;
  for (uint8_t c : in) {
    if (c == 0) { out[code_i] = code; code_i = out.size(); out.push_back(0); code = 1; }
    else { out.push_back(c); if (++code == 0xFF) { out[code_i] = code; code_i = out.size(); out.push_back(0); code = 1; } }
  }
  out[code_i] = code; return out;
}

int main(int argc, char** argv) {
  dir = argc > 1 ? argv[1] : ".";
  const float N = NAN;

  HelloMsg he{}; he.h = hdr(MSG_HELLO, 0, 120);
  strncpy(he.fw, "rover_main 0.1.0", sizeof(he.fw));
  he.hw_present = (1<<HW_IMU)|(1<<HW_ENV)|(1<<HW_LIGHT)|(1<<HW_SONAR)|(1<<HW_BATTERY)|(1<<HW_BUZZER)|(1<<HW_SERVO);
  he.env_model = ENV_BME280; he.lidar_model = LIDAR_NONE; he.cells = 3; he.reset_reason = 1; he.encoder_cpr = 0;
  dump("hello", &he, sizeof he);

  TelemMsg t{}; t.h = hdr(MSG_TELEM, 88, 12345);
  t.temp_c = 22.4f; t.hum_pct = 41.0f; t.press_hpa = 1012.3f; t.alt_m = 0.4f; t.lux = 340.0f;
  t.vbat_v = 11.42f; t.soc_pct = 71.0f; t.ibat_a = N; t.p_w = N;
  t.pwm_l = 180; t.pwm_r = 175; t.rpm_l = N; t.rpm_r = N; t.x_m = N; t.y_m = N; t.dist_m = N;
  t.roll_deg = 1.2f; t.pitch_deg = -0.4f; t.yaw_deg = 87.5f; t.ax_g = 0.01f; t.ay_g = -0.02f; t.az_g = 1.0f;
  t.gz_dps = 0.3f; t.imu_temp_c = 31.2f; t.sonar_angle_deg = 45.0f; t.sonar_dist_cm = 63.0f;
  t.mode = MODE_MANUAL; t.state_flags = ST_WD_OK; t.last_cmd_age_ms = 40; t.rssi_dbm = -61;
  t.heap_b = 182000; t.uptime_s = 340; t.loop_hz = 98; t.chip_temp_c = 48.0f;
  dump("telem", &t, sizeof t);

  ScanMsg s{}; s.h = hdr(MSG_SCAN, 95, 13000);
  s.src = SCAN_SONAR; s.scan_id = 12; s.part = 0; s.parts = 1; s.yaw_deg = 87.5f; s.x_m = N; s.y_m = N;
  s.start_cdeg = 0; s.step_cdeg = 1000; s.n = 3; s.dist_cm[0] = 120; s.dist_cm[1] = 118; s.dist_cm[2] = 0xFFFF;
  dump("scan_sonar", &s, SCAN_HEADER_BYTES + 2 * s.n);

  EventMsg e{}; e.h = hdr(MSG_EVENT, 101, 14000); e.level = EV_WARN; e.code = EV_BATT_LOW;
  strncpy(e.msg, "vbat 10.4 V", sizeof(e.msg) - 1);
  dump("event", &e, sizeof e);

  AckMsg a{}; a.h = hdr(MSG_ACK, 90, 5010); a.ack_seq = 42; a.ok = 1;
  dump("ack", &a, sizeof a);

  CmdMsg c{}; c.h = hdr(MSG_CMD, 42, 5000); c.drive_l = 0.6f; c.drive_r = 0.6f; c.mode = MODE_MANUAL;
  c.servo_mode = 0; c.servo_angle_deg = 90; c.cmd_flags = 0; c.goto_x_m = N; c.goto_y_m = N;
  dump("cmd", &c, sizeof c);

  BridgeStatus b{}; b.uptime_ms = 60000; b.rx_count = 600; b.tx_ok = 598; b.tx_fail = 2; b.channel = 11; b.last_rssi = -58; b.rover_paired = 1;
  dump("bridge_status", &b, sizeof b);

  // Full serial frame: telem as received by the bridge with RSSI -58
  std::vector<uint8_t> raw = {SK_RX_FROM_ROVER, (uint8_t)(int8_t)-58};
  const uint8_t* tp = (const uint8_t*)&t; raw.insert(raw.end(), tp, tp + sizeof t);
  uint16_t crc = crc16_ccitt_false(raw.data(), raw.size());
  raw.push_back(crc & 0xFF); raw.push_back(crc >> 8);
  std::vector<uint8_t> fr = cobs(raw); fr.push_back(0x00);
  dump("serial_frame_telem", fr.data(), fr.size());

  const char* chk = "123456789";
  printf("crc16 check(\"123456789\") = 0x%04X (expect 0x29B1)\n", crc16_ccitt_false((const uint8_t*)chk, 9));
  return 0;
}
