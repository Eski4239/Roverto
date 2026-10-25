// messages.h — stamps the MsgHeader and sends rover -> GS messages (docs/02 §2).
// One seq counter for every message type (D-003), 0 at boot (D-015), t_ms = millis().
#pragma once
#include <stddef.h>
#include "rover_protocol.h"

namespace msg {

// Fills the header of any wire struct (MsgHeader is always its first member) and sends `len` bytes.
bool send(void* wire_struct, size_t len, MsgType type);

bool sendEvent(EvLevel level, EvCode code, const char* fmt, ...) __attribute__((format(printf, 3, 4)));
bool sendAck(uint16_t ack_seq, bool ok);
bool sendScan(ScanMsg& s);  // sends only SCAN_HEADER_BYTES + 2 * n

uint16_t nextSeq();         // seq the next message will carry

}  // namespace msg
