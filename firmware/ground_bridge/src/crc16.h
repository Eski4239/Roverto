// crc16.h — CRC-16/CCITT-FALSE for the USB serial frame trailer (docs/02 §4).
// Byte-for-byte match with ground_station/app/wire.py::_crc16_ccitt_false and
// tools/golden_gen.cpp::crc16_ccitt_false. Self-check: crc16_ccitt_false("123456789") == 0x29B1.
#pragma once
#include <stdint.h>
#include <stddef.h>

static inline uint16_t crc16_ccitt_false(const uint8_t* data, size_t len) {
  uint16_t crc = 0xFFFF;
  for (size_t i = 0; i < len; i++) {
    crc ^= (uint16_t)data[i] << 8;
    for (int k = 0; k < 8; k++) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
  }
  return crc;
}
