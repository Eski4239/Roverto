// console.cpp — reads whatever bytes are waiting, never blocks.
#include "console.h"
#include <Arduino.h>

namespace console {

static char buf[64];
static uint8_t len = 0;
static bool overflow = false;

const char* poll() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r' || ch == '\n') {
      if (len == 0 && !overflow) continue;  // CRLF / empty line
      buf[len] = '\0';
      bool bad = overflow;
      len = 0;
      overflow = false;
      if (bad) continue;  // line too long: drop it
      return buf;
    }
    if (len < sizeof(buf) - 1) buf[len++] = ch;
    else overflow = true;
  }
  return nullptr;
}

}  // namespace console
