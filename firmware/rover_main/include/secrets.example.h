// secrets.example.h — copy to secrets.h (gitignored) and fill in real values.
// Never commit secrets.h. PEER_MAC is the GROUND_BRIDGE's WiFi STA MAC (read it with tools/mac_reader).
#pragma once

#define PEER_MAC {0x20, 0x50, 0x0D, 0x00, 0x7D, 0xFC}
#define ESPNOW_CHANNEL 11

// Optional ESP-NOW encryption, off by default (docs/01 §2). Must match the bridge's PMK/LMK.
// #define ESPNOW_PMK "16-byte-pmk-here"
// #define ESPNOW_LMK "16-byte-lmk-here"
