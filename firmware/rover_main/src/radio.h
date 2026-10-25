// radio.h — ESP-NOW to the ground_bridge (docs/01 §2.1). Callbacks only count / copy;
// all decoding and logic happens in loop() (CLAUDE.md firmware style).
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace radio {

static const uint8_t RX_MAX_LEN = 32;  // CmdMsg is 30 B; anything longer is rejected by length anyway

struct RxFrame {
  uint8_t src_mac[6];
  uint8_t len;          // real received length (may be > RX_MAX_LEN, payload then truncated)
  uint8_t data[RX_MAX_LEN];
  int8_t rssi_dbm;
};

bool begin();                                   // WiFi STA + fixed channel + peer
bool send(const void* payload, size_t len);     // false (and send_err++) if not queued
bool receive(RxFrame& out);                     // pops one received frame, non-blocking
const uint8_t* peerMac();
void ownMac(uint8_t out[6]);

uint32_t txOk();       // MAC-level ACK from the bridge
uint32_t txFail();     // sent but not acknowledged
uint32_t sendErr();    // esp_now_send() refused (queue full, not initialised...)
uint32_t rxDropped();  // RX queue full

}  // namespace radio
