// ground_bridge — ESP-NOW <-> USB serial bridge. docs/01 §2/§5.2, docs/02 §4/§6, docs/04 §1b.
// CLAUDE.md rule 4: the bridge stays dumb. It never decodes telemetry (radio payload is an
// opaque byte blob) and never generates a CmdMsg -- the joystick is reported raw, never converted
// to drive values.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <PacketSerial.h>

#include "rover_protocol.h"
#include "crc16.h"
#include "secrets.h"

// ---------------------------------------------------------------- pins ----
static const int PIN_VRY_L = 34;
static const int PIN_VRY_R = 35;
static const int PIN_VRX_L = 32;
static const int PIN_VRX_R = 33;
static const int PIN_SW_L = 25;
static const int PIN_SW_R = 26;
static const int PIN_LED = 2;
static const unsigned long LED_BLINK_MS = 30;

// ------------------------------------------------------------- scheduler ----
static const unsigned long STATUS_PERIOD_MS = 1000;
static const unsigned long JOYSTICK_PERIOD_MS = 20; // 50 Hz

static uint32_t rx_count = 0, tx_ok = 0, tx_fail = 0;
static int8_t last_rssi = 0;
static uint8_t joy_seq = 0;
static unsigned long last_status_ms = 0;
static unsigned long last_joy_ms = 0;
static unsigned long led_off_at_ms = 0;

static uint8_t peer_mac[6] = PEER_MAC;

PacketSerial_<COBS, 0> packetSerial;

// -------------------------------------------------------- ESP-NOW RX queue ----
struct EspNowRxItem {
  uint8_t len;
  uint8_t data[ESPNOW_MAX_PAYLOAD];
  int8_t rssi;
};
static QueueHandle_t espnowRxQueue;

// ---------------------------------------------------------------- framing ----
// Builds kind|rssi|payload|crc16 and hands it to PacketSerial (COBS-encodes + trailing 0x00).
static void sendFrame(uint8_t kind, int8_t rssi, const void* payload, size_t len) {
  static uint8_t buf[2 + ESPNOW_MAX_PAYLOAD + 2];
  if (len > ESPNOW_MAX_PAYLOAD) return; // never happens: every message type is <=250B
  buf[0] = kind;
  buf[1] = (uint8_t)rssi;
  memcpy(buf + 2, payload, len);
  uint16_t crc = crc16_ccitt_false(buf, 2 + len);
  buf[2 + len] = (uint8_t)(crc & 0xFF);
  buf[2 + len + 1] = (uint8_t)(crc >> 8);
  packetSerial.send(buf, 2 + len + 2);
}

static void sendLog(const char* msg) {
  sendFrame(SK_BRIDGE_LOG, 0, msg, strlen(msg));
}

// --------------------------------------------------------------- ESP-NOW ----

// Minimal work only (CLAUDE.md: no heavy work in ESP-NOW callbacks): filter by MAC,
// copy into the queue, return. All serial I/O and framing happens in loop().
void onDataRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len <= 0 || len > ESPNOW_MAX_PAYLOAD) return;
  if (memcmp(info->src_addr, peer_mac, 6) != 0) return; // not the rover -- drop

  EspNowRxItem item;
  item.len = (uint8_t)len;
  memcpy(item.data, data, len);
  item.rssi = info->rx_ctrl ? info->rx_ctrl->rssi : 0;
  xQueueSend(espnowRxQueue, &item, 0); // WiFi task, not an ISR; never block (full -> drop)
}

// ESP-IDF 5.5 (arduino-esp32 3.3.x) signature: the peer MAC is info->des_addr.
void onDataSent(const esp_now_send_info_t* info, esp_now_send_status_t status) {
  (void)info;
  if (status == ESP_NOW_SEND_SUCCESS) tx_ok++;
  else tx_fail++;
}

// -------------------------------------------------------------- serial RX ----

// Fires once per decoded COBS frame from the laptop. Only SK_TX_TO_ROVER is ever
// acted on; the bridge never decodes the radio payload, only forwards it.
void onSerialPacket(const uint8_t* buffer, size_t size) {
  if (size < 4) return; // kind + rssi + crc16, minimum

  uint16_t expected_crc = (uint16_t)buffer[size - 2] | ((uint16_t)buffer[size - 1] << 8);
  uint16_t actual_crc = crc16_ccitt_false(buffer, size - 2);
  if (actual_crc != expected_crc) {
    static uint8_t crc_err_logged = 0;
    if (crc_err_logged < 5) {
      sendLog("bad serial frame CRC");
      crc_err_logged++;
    }
    return;
  }

  uint8_t kind = buffer[0];
  if (kind != SK_TX_TO_ROVER) return; // unexpected kind from the laptop -- drop

  const uint8_t* payload = buffer + 2;
  size_t payload_len = size - 4;
  esp_now_send(peer_mac, payload, payload_len);
}

// -------------------------------------------------------------- joystick ----

static uint16_t readAdcAveraged(int pin) {
  uint32_t sum = 0;
  for (int i = 0; i < 4; i++) sum += analogRead(pin);
  return (uint16_t)(sum / 4);
}

static void readJoystick(JoystickState& out) {
  out.lx = readAdcAveraged(PIN_VRX_L);
  out.ly = readAdcAveraged(PIN_VRY_L);
  out.rx = readAdcAveraged(PIN_VRX_R);
  out.ry = readAdcAveraged(PIN_VRY_R);
  out.buttons = (digitalRead(PIN_SW_L) == LOW ? 0x01 : 0) | (digitalRead(PIN_SW_R) == LOW ? 0x02 : 0);
  out.seq = joy_seq;
}

// ------------------------------------------------------------------ setup ----

void setup() {
  Serial.setRxBufferSize(1024); // must be set before begin(); default 256B risks overflow at 921600 baud
  Serial.begin(921600);

  pinMode(PIN_LED, OUTPUT);
  digitalWrite(PIN_LED, LOW);
  pinMode(PIN_SW_L, INPUT_PULLUP);
  pinMode(PIN_SW_R, INPUT_PULLUP);
  analogSetAttenuation(ADC_11db);

  WiFi.mode(WIFI_STA); // not connected to any AP -- ESP-NOW only, fixed channel
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    sendLog("esp_now_init failed");
  }

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, peer_mac, 6);
  peerInfo.channel = ESPNOW_CHANNEL;
#ifdef ESPNOW_PMK
  peerInfo.encrypt = true;
  memcpy(peerInfo.lmk, ESPNOW_LMK, 16);
  esp_now_set_pmk((const uint8_t*)ESPNOW_PMK);
#else
  peerInfo.encrypt = false;
#endif
  esp_now_add_peer(&peerInfo);

  esp_now_register_send_cb(onDataSent);
  esp_now_register_recv_cb(onDataRecv);

  espnowRxQueue = xQueueCreate(8, sizeof(EspNowRxItem));

  packetSerial.setStream(&Serial);
  packetSerial.setPacketHandler(&onSerialPacket);

  uint8_t mac[6];
  WiFi.macAddress(mac);
  char msg[48];
  snprintf(msg, sizeof(msg), "ground_bridge MAC %02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  sendLog(msg);
}

// ------------------------------------------------------------------- loop ----

void loop() {
  packetSerial.update();

  EspNowRxItem item;
  while (xQueueReceive(espnowRxQueue, &item, 0) == pdTRUE) {
    rx_count++;
    last_rssi = item.rssi;
    sendFrame(SK_RX_FROM_ROVER, item.rssi, item.data, item.len);
    digitalWrite(PIN_LED, HIGH);
    led_off_at_ms = millis() + LED_BLINK_MS;
  }
  if (led_off_at_ms != 0 && millis() >= led_off_at_ms) {
    digitalWrite(PIN_LED, LOW);
    led_off_at_ms = 0;
  }

  unsigned long now = millis();
  if (now - last_status_ms >= STATUS_PERIOD_MS) {
    last_status_ms = now;
    BridgeStatus status;
    status.uptime_ms = now;
    status.rx_count = rx_count;
    status.tx_ok = tx_ok;
    status.tx_fail = tx_fail;
    status.channel = ESPNOW_CHANNEL;
    status.last_rssi = last_rssi;
    status.rover_paired = esp_now_is_peer_exist(peer_mac) ? 1 : 0;
    sendFrame(SK_BRIDGE_STATUS, 0, &status, sizeof(status));
  }

  if (now - last_joy_ms >= JOYSTICK_PERIOD_MS) {
    last_joy_ms = now;
    JoystickState js;
    readJoystick(js);
    sendFrame(SK_JOYSTICK, 0, &js, sizeof(js));
    joy_seq++;
  }
}
