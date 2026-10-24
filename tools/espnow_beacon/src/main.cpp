// espnow_beacon — TEMPORARY stand-in for rover_main, used to test ground_bridge before R3 exists.
// Sends golden HelloMsg (5s) / TelemMsg (10Hz) to the bridge's MAC, prints received CmdMsg, and
// replies with AckMsg per the ack rule (docs/02 §6: ack when mode/cmd_flags changed, or seq%10==0).
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#include "rover_protocol.h"
#include "golden_payloads.h"

static const uint8_t BRIDGE_MAC[6] = {0x20, 0x50, 0x0D, 0x00, 0x7D, 0xFC};
static const uint8_t ESPNOW_CHANNEL = 11;

static const unsigned long HELLO_PERIOD_MS = 5000;
static const unsigned long TELEM_PERIOD_MS = 100; // 10 Hz

static uint16_t hello_seq = 0;
static uint16_t telem_seq = 0;
static uint8_t prev_mode = 0xFF;
static uint8_t prev_cmd_flags = 0xFF;

static void patchHeader(uint8_t* buf, uint16_t seq, uint32_t t_ms) {
  // MsgHeader: magic, ver, type, flags, seq(u16 @4), t_ms(u32 @6)
  memcpy(buf + 4, &seq, sizeof(seq));
  memcpy(buf + 6, &t_ms, sizeof(t_ms));
}

void onDataRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len != sizeof(CmdMsg)) return;
  CmdMsg cmd;
  memcpy(&cmd, data, sizeof(cmd));
  if (cmd.h.magic != PROTO_MAGIC || cmd.h.type != MSG_CMD) return;

  Serial.printf("CMD seq=%u drive_l=%.2f drive_r=%.2f cmd_flags=0x%02X\n",
                cmd.h.seq, cmd.drive_l, cmd.drive_r, cmd.cmd_flags);

  bool changed = (cmd.mode != prev_mode) || (cmd.cmd_flags != prev_cmd_flags);
  bool periodic = (cmd.h.seq % 10 == 0);
  if (changed || periodic) {
    AckMsg ack;
    ack.h.magic = PROTO_MAGIC;
    ack.h.ver = PROTO_VER;
    ack.h.type = MSG_ACK;
    ack.h.flags = 0;
    ack.h.seq = 0; // this beacon doesn't track its own ack sequence
    ack.h.t_ms = millis();
    ack.ack_seq = cmd.h.seq;
    ack.ok = 1;
    esp_now_send(BRIDGE_MAC, (const uint8_t*)&ack, sizeof(ack));
  }
  prev_mode = cmd.mode;
  prev_cmd_flags = cmd.cmd_flags;
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_now_init();

  esp_now_peer_info_t peerInfo = {};
  memcpy(peerInfo.peer_addr, BRIDGE_MAC, 6);
  peerInfo.channel = ESPNOW_CHANNEL;
  peerInfo.encrypt = false;
  esp_now_add_peer(&peerInfo);
  esp_now_register_recv_cb(onDataRecv);

  Serial.println("espnow_beacon up -- sending golden HELLO/TELEM to bridge");
}

void loop() {
  static unsigned long last_hello_ms = 0;
  static unsigned long last_telem_ms = 0;
  unsigned long now = millis();

  if (now - last_hello_ms >= HELLO_PERIOD_MS) {
    last_hello_ms = now;
    uint8_t buf[HELLO_GOLDEN_LEN];
    memcpy(buf, HELLO_GOLDEN, HELLO_GOLDEN_LEN);
    patchHeader(buf, hello_seq++, now);
    esp_now_send(BRIDGE_MAC, buf, HELLO_GOLDEN_LEN);
  }

  if (now - last_telem_ms >= TELEM_PERIOD_MS) {
    last_telem_ms = now;
    uint8_t buf[TELEM_GOLDEN_LEN];
    memcpy(buf, TELEM_GOLDEN, TELEM_GOLDEN_LEN);
    patchHeader(buf, telem_seq++, now);
    esp_now_send(BRIDGE_MAC, buf, TELEM_GOLDEN_LEN);
  }
}
