// rover_protocol.h — binary wire protocol v1 (radio link, ESP-NOW)
// Single C definition shared by firmware/rover_main and firmware/ground_bridge.
// Mirror in Python: ground_station/app/wire.py (struct format strings + golden-bytes tests).
// Logical meaning of every field: docs/02_TELEMETRY_PROTOCOL.md
//
// Rules:
//  - Little-endian, packed, every message <= 250 bytes (ESP-NOW v1 payload limit).
//  - float NaN  = "no data / hardware not installed"  (becomes JSON null on the laptop)
//  - uint16 0xFFFF in distance arrays = no echo / no return
//  - Never reorder or resize fields without bumping PROTO_VER.
#pragma once
#include <stdint.h>

#define PROTO_MAGIC 0xA7
#define PROTO_VER   1
#define ESPNOW_MAX_PAYLOAD 250

enum MsgType : uint8_t {
  MSG_HELLO = 0x01,   // rover -> GS, on boot, every 5 s, and on CMD_REQUEST_HELLO
  MSG_TELEM = 0x02,   // rover -> GS, 10 Hz
  MSG_SCAN  = 0x03,   // rover -> GS, per sweep / revolution (fragmented)
  MSG_EVENT = 0x04,   // rover -> GS, on event
  MSG_ACK   = 0x05,   // rover -> GS, reply to non-drive commands
  MSG_CMD   = 0x10,   // GS -> rover, 10 Hz (also the heartbeat)
};

enum HwBit : uint16_t {           // HelloMsg.hw_present bit positions
  HW_IMU = 0, HW_ENV = 1, HW_LIGHT = 2, HW_SONAR = 3, HW_BATTERY = 4,
  HW_CURRENT = 5, HW_ENCODERS = 6,
  HW_CAMERA = 7,   // RESERVED: always 0 from the rover; camera presence is probed by the ground station
  HW_LIDAR = 8, HW_BUZZER = 9,
  HW_SERVO = 10,   // maps to JSON hw.sonar.servo
};

enum EnvModel   : uint8_t { ENV_NONE = 0, ENV_BME280 = 1, ENV_BMP280 = 2, ENV_DHT11 = 3 };
enum LidarModel : uint8_t { LIDAR_NONE = 0, LIDAR_LD06 = 1, LIDAR_LD19 = 2, LIDAR_RPLIDAR_C1 = 3 };
enum Mode       : uint8_t { MODE_IDLE = 0, MODE_MANUAL = 1, MODE_ASSISTED = 2, MODE_AUTO = 3 };
enum ScanSrc    : uint8_t { SCAN_SONAR = 1, SCAN_LIDAR = 2 };
enum EvLevel    : uint8_t { EV_INFO = 0, EV_WARN = 1, EV_ERROR = 2 };
enum EvCode     : uint8_t {
  EV_BOOT = 1, EV_BATT_LOW = 2, EV_BATT_CRIT = 3, EV_TILT = 4, EV_WD_STOP = 5,
  EV_ESTOP = 6, EV_SENSOR_LOST = 7, EV_OBSTACLE = 8, EV_CMD_REJECTED = 9,
};

// TelemMsg.state_flags
#define ST_ESTOP  (1u << 0)
#define ST_WD_OK  (1u << 1)
// CmdMsg.cmd_flags
#define CMD_ESTOP         (1u << 0)
#define CMD_ESTOP_RESET   (1u << 1)
#define CMD_BUZZER        (1u << 2)
#define CMD_REQUEST_HELLO (1u << 3)

#pragma pack(push, 1)

struct MsgHeader {          // 10 bytes
  uint8_t  magic;           // PROTO_MAGIC
  uint8_t  ver;             // PROTO_VER
  uint8_t  type;            // MsgType
  uint8_t  flags;           // reserved, 0
  uint16_t seq;             // per-sender counter, wraps
  uint32_t t_ms;            // sender millis()
};

struct HelloMsg {           // 38 bytes
  MsgHeader h;
  char     fw[20];          // "rover_main 0.1.0", NUL-padded
  uint16_t hw_present;      // bitmask of HwBit
  uint8_t  env_model;       // EnvModel (from chip ID: 0x60 BME280, 0x58 BMP280)
  uint8_t  lidar_model;     // LidarModel
  uint8_t  cells;           // battery series cells (3)
  uint8_t  reset_reason;    // esp_reset_reason()
  uint8_t  encoder_cpr;     // counts per wheel rev, 0 if none
  uint8_t  reserved;
};

struct TelemMsg {           // 129 bytes
  MsgHeader h;
  // env (BME280 / BMP280 / DHT11)
  float temp_c, hum_pct, press_hpa, alt_m;
  float lux;                                  // BH1750
  // power
  float vbat_v, soc_pct, ibat_a, p_w;         // ibat/p_w NaN until INA219
  // motors
  int16_t pwm_l, pwm_r;                       // commanded, -255..255 (sign = direction)
  float rpm_l, rpm_r;                         // NaN until encoders
  // odometry (NaN until encoders)
  float x_m, y_m, dist_m;
  // imu (MPU-6050)
  float roll_deg, pitch_deg, yaw_deg, ax_g, ay_g, az_g, gz_dps, imu_temp_c;
  // sonar (latest single ping)
  float sonar_angle_deg, sonar_dist_cm;       // dist NaN = no echo
  // state
  uint8_t  mode;                              // Mode
  uint8_t  state_flags;                       // ST_*
  uint16_t last_cmd_age_ms;
  int8_t   rssi_dbm;                          // RSSI of last CMD as seen by the rover
  // sys
  uint32_t heap_b;
  uint32_t uptime_s;
  uint16_t loop_hz;
  float    chip_temp_c;
};

#define SCAN_MAX_PTS 100
struct ScanMsg {            // 231 bytes when n = 100 (send only 31 + 2*n bytes)
  MsgHeader h;
  uint8_t  src;             // ScanSrc
  uint8_t  scan_id;         // increments per complete sweep / revolution
  uint8_t  part;            // fragment index 0..parts-1
  uint8_t  parts;           // total fragments (lidar 360 pts -> 4)
  float    yaw_deg;         // pose at start of scan
  float    x_m, y_m;        // NaN without odometry
  uint16_t start_cdeg;      // angle of dist_cm[0], centi-degrees, rover frame (0 = front, CCW+)
  uint16_t step_cdeg;       // angle step between points, centi-degrees
  uint8_t  n;               // valid points in this fragment
  uint16_t dist_cm[SCAN_MAX_PTS]; // 0xFFFF = no return
};
#define SCAN_HEADER_BYTES 31

struct EventMsg {           // 72 bytes
  MsgHeader h;
  uint8_t level;            // EvLevel
  uint8_t code;             // EvCode
  char    msg[60];          // ASCII, NUL-terminated; snprintf truncates silently to 59 chars
};

struct AckMsg {             // 13 bytes
  MsgHeader h;
  uint16_t ack_seq;         // seq of the CmdMsg being acknowledged
  uint8_t  ok;              // 1 accepted, 0 rejected
};

struct CmdMsg {             // 30 bytes
  MsgHeader h;
  float   drive_l, drive_r; // -1.0..1.0 fraction of max PWM (rover clamps)
  uint8_t mode;             // Mode
  uint8_t servo_mode;       // 0 sweep, 1 fixed
  uint8_t servo_angle_deg;  // used when servo_mode = 1
  uint8_t cmd_flags;        // CMD_*
  float   goto_x_m, goto_y_m; // NaN = none (future waypoint navigation)
};

#pragma pack(pop)

// ---------- Serial framing between ground_bridge and laptop (USB, 921600 baud) ----------
// Each frame:  COBS( kind[1] | rssi[1] | payload[N] | crc16[2] ) followed by 0x00 delimiter
// crc16 = CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) over kind|rssi|payload, little-endian.
enum SerialKind : uint8_t {
  SK_RX_FROM_ROVER = 0x01,  // bridge -> laptop: payload = one radio message, rssi = RX RSSI
  SK_TX_TO_ROVER   = 0x02,  // laptop -> bridge: payload = one radio message to send, rssi = 0
  SK_BRIDGE_STATUS = 0x03,  // bridge -> laptop, 1 Hz: payload = BridgeStatus
  SK_BRIDGE_LOG    = 0x04,  // bridge -> laptop: payload = ASCII text
};

#pragma pack(push, 1)
struct BridgeStatus {       // 19 bytes
  uint32_t uptime_ms;
  uint32_t rx_count;        // radio frames received from rover
  uint32_t tx_ok;           // esp_now_send callbacks with success
  uint32_t tx_fail;
  uint8_t  channel;         // WiFi channel used for ESP-NOW
  int8_t   last_rssi;
  uint8_t  rover_paired;    // 1 if rover peer added
};
#pragma pack(pop)

#ifdef __cplusplus
static_assert(sizeof(MsgHeader)    == 10,  "MsgHeader size");
static_assert(sizeof(HelloMsg)     == 38,  "HelloMsg size");
static_assert(sizeof(TelemMsg)     == 129, "TelemMsg size");
static_assert(sizeof(ScanMsg)      == 231, "ScanMsg size");
static_assert(sizeof(EventMsg)     == 72,  "EventMsg size");
static_assert(sizeof(AckMsg)       == 13,  "AckMsg size");
static_assert(sizeof(CmdMsg)       == 30,  "CmdMsg size");
static_assert(sizeof(BridgeStatus) == 19,  "BridgeStatus size");
static_assert(sizeof(ScanMsg) <= ESPNOW_MAX_PAYLOAD, "ScanMsg too big for ESP-NOW");
#endif
