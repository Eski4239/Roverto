// secrets.example.h — copy to secrets.h (gitignored) and fill in real values.
// Never commit secrets.h. PEER_MAC is the ROVER's WiFi STA MAC (read it with tools/mac_reader).
#pragma once

#define PEER_MAC {0x20, 0x50, 0x0D, 0x07, 0x83, 0x14}
#define ESPNOW_CHANNEL 11

// Optional ESP-NOW encryption, off by default (docs/01 §2). Enabling requires
// setting peerInfo.encrypt = true in main.cpp and matching PMK/LMK on both boards.
// #define ESPNOW_PMK "16-byte-pmk-here"
// #define ESPNOW_LMK "16-byte-lmk-here"
