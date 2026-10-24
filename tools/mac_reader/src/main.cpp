// mac_reader — prints the board's WiFi STA MAC once per second, plus a line ready to paste
// as PEER_MAC into the *other* board's include/secrets.h. Works on any ESP32 (no wiring needed).
#include <Arduino.h>
#include <WiFi.h>
#include <esp_mac.h>

static uint8_t mac[6];
static uint32_t last_print_ms = 0;

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);                 // same mode as rover_main / ground_bridge
  esp_read_mac(mac, ESP_MAC_WIFI_STA); // the MAC ESP-NOW peers must use
}

void loop() {
  if (millis() - last_print_ms < 1000) return;
  last_print_ms = millis();

  Serial.printf("\nchip %s rev %d, %d MB flash\n", ESP.getChipModel(), ESP.getChipRevision(),
                (int)(ESP.getFlashChipSize() / (1024 * 1024)));
  Serial.printf("STA MAC : %02X:%02X:%02X:%02X:%02X:%02X\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  Serial.printf("secrets.h of the OTHER board: #define PEER_MAC {0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X}\n",
                mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}
