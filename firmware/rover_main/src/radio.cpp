// radio.cpp — arduino-esp32 3.3.12 = ESP-IDF 5.5: send callback gets esp_now_send_info_t (GS-5).
// Both callbacks run in the WiFi task (not an ISR) -> plain xQueueSend with 0 timeout.
#include "radio.h"
#include <Arduino.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include <string.h>
#include "secrets.h"

namespace radio {

static uint8_t peer_mac[6] = PEER_MAC;
static QueueHandle_t rx_queue = nullptr;
static volatile uint32_t tx_ok = 0, tx_fail = 0, rx_dropped = 0;
static uint32_t send_err = 0;

static void onDataSent(const esp_now_send_info_t* info, esp_now_send_status_t status) {
  (void)info;
  if (status == ESP_NOW_SEND_SUCCESS) tx_ok = tx_ok + 1;
  else tx_fail = tx_fail + 1;
}

static void onDataRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len <= 0) return;
  RxFrame f;
  memcpy(f.src_mac, info->src_addr, 6);
  f.len = len > 255 ? 255 : (uint8_t)len;
  memcpy(f.data, data, len < RX_MAX_LEN ? len : RX_MAX_LEN);
  f.rssi_dbm = info->rx_ctrl ? (int8_t)info->rx_ctrl->rssi : 0;
  if (xQueueSend(rx_queue, &f, 0) != pdTRUE) rx_dropped = rx_dropped + 1;
}

bool begin() {
  rx_queue = xQueueCreate(8, sizeof(RxFrame));
  WiFi.mode(WIFI_STA);  // not connected to any AP: ESP-NOW only, fixed channel
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) return false;

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, peer_mac, 6);
  peer.channel = ESPNOW_CHANNEL;
#ifdef ESPNOW_PMK
  peer.encrypt = true;
  memcpy(peer.lmk, ESPNOW_LMK, 16);
  esp_now_set_pmk((const uint8_t*)ESPNOW_PMK);
#else
  peer.encrypt = false;
#endif
  if (esp_now_add_peer(&peer) != ESP_OK) return false;
  esp_now_register_send_cb(onDataSent);
  esp_now_register_recv_cb(onDataRecv);
  return true;
}

bool send(const void* payload, size_t len) {
  if (esp_now_send(peer_mac, (const uint8_t*)payload, len) != ESP_OK) {
    send_err++;
    return false;
  }
  return true;
}

bool receive(RxFrame& out) { return rx_queue && xQueueReceive(rx_queue, &out, 0) == pdTRUE; }

const uint8_t* peerMac() { return peer_mac; }
void ownMac(uint8_t out[6]) { esp_wifi_get_mac(WIFI_IF_STA, out); }

uint32_t txOk() { return tx_ok; }
uint32_t txFail() { return tx_fail; }
uint32_t sendErr() { return send_err; }
uint32_t rxDropped() { return rx_dropped; }

}  // namespace radio
