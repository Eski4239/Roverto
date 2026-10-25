// rover_main — ESP32 #1 on the rover. docs/01 §5.1 (drivers + non-blocking loop), docs/02 (protocol,
// §5 safety, §6 clarifications), docs/PROGRESS_ROVER_MAIN.md (decisions D-xxx).
// Bench test T1 build: BME280, BH1750 (if fitted), HC-SR04 on SG90, passive buzzer. Motors, IMU,
// battery, encoders, INA219 and LiDAR are stubs (present=false, NaN).
#include <Arduino.h>
#include <Wire.h>
#include <esp_system.h>
#include <string.h>

#include "config.h"
#include "console.h"
#include "control.h"
#include "drivers/buzzer.h"
#include "drivers/env.h"
#include "drivers/light.h"
#include "drivers/scanner.h"
#include "drivers/stubs.h"
#include "golden.h"
#include "messages.h"
#include "radio.h"
#include "rover_protocol.h"
#include "secrets.h"

// ---------------------------------------------------------------- drivers ----
static EnvDriver env;
static LightDriver light;
static ScannerDriver scanner;
static BuzzerDriver buzzer;
static ImuStub imu;
static BatteryStub battery;
static MotorsStub motors;
static EncodersStub encoders;
static CurrentStub current;
static LidarStub lidar;
static Driver* const drivers[] = {&env, &light, &scanner, &buzzer, &imu,
                                  &battery, &motors, &encoders, &current, &lidar};

static Control control;
static bool radio_ok = false;
static uint8_t reset_reason = 0;

// -------------------------------------------------------------- scheduler ----
static uint32_t last_control_ms = 0, last_telem_ms = 0, last_slow_ms = 0, last_hello_ms = 0;
static uint32_t control_ticks = 0, loop_iters = 0;
static uint16_t loop_hz = 0;          // 100 Hz control ticks really executed in the last second
static uint32_t loop_iters_per_s = 0; // free-running loop() passes per second (console only)
static float chip_temp_c = NAN;

// docs/02 §6.5: same numbering as esp_reset_reason_t
static const char* const RESET_NAMES[] = {"UNKNOWN", "POWERON", "EXT", "SW", "PANIC", "INT_WDT",
                                          "TASK_WDT", "WDT", "DEEPSLEEP", "BROWNOUT", "SDIO", "USB",
                                          "JTAG", "EFUSE", "PWR_GLITCH", "CPU_LOCKUP"};
static const char* resetName(uint8_t r) {
  return r < sizeof(RESET_NAMES) / sizeof(RESET_NAMES[0]) ? RESET_NAMES[r] : "UNKNOWN_N";
}

// --------------------------------------------------------------- messages ----
static void sendHello() {
  HelloMsg h;
  memset(&h, 0, sizeof(h));
  strncpy(h.fw, FW_VERSION, sizeof(h.fw) - 1);
  h.lidar_model = LIDAR_NONE;
  h.cells = 0;         // no battery sensing fitted yet (R5)
  h.encoder_cpr = 0;
  h.reset_reason = reset_reason;
  for (Driver* d : drivers) d->fillHello(h);
  msg::send(&h, sizeof(h), MSG_HELLO);
  last_hello_ms = millis();
}

static void sendTelem() {
  TelemMsg t;
  memset(&t, 0, sizeof(t));
  for (Driver* d : drivers) d->fill(t);
  control.fill(t);
  t.heap_b = ESP.getFreeHeap();
  t.uptime_s = millis() / 1000;
  t.loop_hz = loop_hz;
  t.chip_temp_c = chip_temp_c;  // indicative only (D-011)
  msg::send(&t, sizeof(t), MSG_TELEM);
}

// ---------------------------------------------------------------- console ----
static void printMac(const char* label, const uint8_t* m) {
  Serial.printf("%s %02X:%02X:%02X:%02X:%02X:%02X\n", label, m[0], m[1], m[2], m[3], m[4], m[5]);
}

static void printHardware() {
  Serial.printf("env    : %s (chip id 0x%02X at 0x%02X)\n",
                env.model() == ENV_BME280 ? "BME280" : env.model() == ENV_BMP280 ? "BMP280" : "not found",
                env.chipId(), env.address());
  Serial.printf("light  : %s", light.present ? "BH1750" : "not found");
  if (light.present) Serial.printf(" at 0x%02X", light.address());
  Serial.println();
  Serial.printf("sonar  : HC-SR04 + SG90 (assumed fitted)\nbuzzer : %s\n",
                buzzer.present ? "passive, LEDC" : "LEDC attach FAILED");
  Serial.println("stubs  : imu battery motors encoders current lidar (present=false)");
}

static void printStatus() {
  TelemMsg t;
  memset(&t, 0, sizeof(t));
  for (Driver* d : drivers) d->fill(t);
  uint32_t age = control.lastCmdAgeMs();

  Serial.println("---- status ----");
  Serial.printf("uptime %lu s  heap %lu B  loop_hz %u  loop passes/s %lu  chip %.1f C\n",
                (unsigned long)(millis() / 1000), (unsigned long)ESP.getFreeHeap(), loop_hz,
                (unsigned long)loop_iters_per_s, chip_temp_c);
  Serial.printf("env    : T %.2f C  H %.1f %%  P %.2f hPa  alt %.2f m\n", t.temp_c, t.hum_pct,
                t.press_hpa, t.alt_m);
  Serial.printf("light  : %.1f lx\n", t.lux);
  Serial.printf("sonar  : %s servo %u deg | last ping %u deg -> %.1f cm | pings %lu timeouts %lu scans %u\n",
                scanner.fixedMode() ? "FIXED" : "SWEEP", scanner.servoAngle(), scanner.lastAngle(),
                scanner.lastDistCm(), (unsigned long)scanner.pings(), (unsigned long)scanner.timeouts(),
                scanner.scanId());
  Serial.printf("state  : mode %u  estop %s  wd_ok %s  buzzer %s  drive %.2f/%.2f (not applied: no motors)\n",
                control.mode(), control.estopLatched() ? "LATCHED" : "no", control.wdOk() ? "yes" : "NO",
                buzzer.sirenOn() ? "ON" : "off", control.driveL(), control.driveR());
  if (control.everReceived())
    Serial.printf("cmd    : last %lu ms ago  rssi %d dBm  valid %lu  rejected %lu\n", (unsigned long)age,
                  control.rssiDbm(), (unsigned long)control.rxValid(), (unsigned long)control.rxRejected());
  else
    Serial.printf("cmd    : none received yet  rejected %lu\n", (unsigned long)control.rxRejected());
  Serial.printf("radio  : %s  next seq %u  tx ok %lu  tx fail %lu  send err %lu  rx dropped %lu\n",
                radio_ok ? "up" : "INIT FAILED", msg::nextSeq(), (unsigned long)radio::txOk(),
                (unsigned long)radio::txFail(), (unsigned long)radio::sendErr(),
                (unsigned long)radio::rxDropped());
}

static void handleConsole() {
  const char* line = console::poll();
  if (!line) return;
  if (strcmp(line, "status") == 0) printStatus();
  else if (strcmp(line, "dump_golden") == 0) dumpGolden(Serial);
  else if (strcmp(line, "hw") == 0) printHardware();
  else Serial.println("commands: status | dump_golden | hw");
}

// ------------------------------------------------------------------ setup ----
void setup() {
  Serial.begin(115200);
  reset_reason = (uint8_t)esp_reset_reason();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL, 400000);
  Wire.setTimeOut(20);  // a stuck I2C bus must not hang the loop

  for (Driver* d : drivers) d->begin();
  control.begin(&scanner, &buzzer);
  radio_ok = radio::begin();
  buzzer.playBoot();

  Serial.printf("\n%s  reset %s\n", FW_VERSION, resetName(reset_reason));
  uint8_t mac[6];
  radio::ownMac(mac);
  printMac("own MAC (rover) :", mac);
  printMac("peer (bridge)   :", radio::peerMac());
  Serial.printf("ESP-NOW channel %d: %s\n", ESPNOW_CHANNEL, radio_ok ? "ok" : "INIT FAILED");
  printHardware();
  Serial.println("type: status | dump_golden | hw");

  // D-015: the very first message after boot is a HELLO with seq 0, before any TELEM
  sendHello();
  msg::sendEvent(EV_INFO, EV_BOOT, "%s reset=%s", FW_VERSION, resetName(reset_reason));

  uint32_t now = millis();
  last_control_ms = last_telem_ms = last_slow_ms = now;
  chip_temp_c = temperatureRead();
}

// ------------------------------------------------------------------- loop ----
void loop() {
  loop_iters++;

  radio::RxFrame f;
  while (radio::receive(f)) control.handle(f);

  uint32_t now = millis();
  if (now - last_control_ms >= CONTROL_PERIOD_MS) {
    last_control_ms += CONTROL_PERIOD_MS;
    if (now - last_control_ms >= CONTROL_PERIOD_MS) last_control_ms = now;  // fell behind: resync, don't burst
    control.tick();
    control_ticks++;
  }

  for (Driver* d : drivers) d->update();

  ScanMsg scan;
  if (scanner.takeScan(scan)) msg::sendScan(scan);

  if (control.takeHelloRequest() && now - last_hello_ms >= HELLO_REQUEST_MIN_GAP_MS) sendHello();
  if (now - last_hello_ms >= HELLO_PERIOD_MS) sendHello();

  if (now - last_telem_ms >= TELEM_PERIOD_MS) {
    last_telem_ms += TELEM_PERIOD_MS;
    if (now - last_telem_ms >= TELEM_PERIOD_MS) last_telem_ms = now;
    sendTelem();
  }

  if (now - last_slow_ms >= SLOW_PERIOD_MS) {
    last_slow_ms = now;
    loop_hz = control_ticks > 0xFFFF ? 0xFFFF : (uint16_t)control_ticks;
    loop_iters_per_s = loop_iters;
    control_ticks = 0;
    loop_iters = 0;
    chip_temp_c = temperatureRead();
  }

  handleConsole();
}
