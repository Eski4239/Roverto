// messages.cpp — header stamping + send. Every message gets a seq even if the radio refuses it,
// so the ground station counts it as lost (loss % stays honest).
#include "messages.h"
#include <Arduino.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "radio.h"

namespace msg {

static uint16_t seq = 0;

uint16_t nextSeq() { return seq; }

bool send(void* wire_struct, size_t len, MsgType type) {
  MsgHeader* h = (MsgHeader*)wire_struct;
  h->magic = PROTO_MAGIC;
  h->ver = PROTO_VER;
  h->type = type;
  h->flags = 0;
  h->seq = seq++;
  h->t_ms = millis();
  return radio::send(wire_struct, len);
}

bool sendEvent(EvLevel level, EvCode code, const char* fmt, ...) {
  EventMsg e;
  memset(&e, 0, sizeof(e));
  e.level = level;
  e.code = code;
  va_list args;
  va_start(args, fmt);
  vsnprintf(e.msg, sizeof(e.msg), fmt, args);  // truncates silently to 59 chars (docs/02 §6.6)
  va_end(args);
  return send(&e, sizeof(e), MSG_EVENT);
}

bool sendAck(uint16_t ack_seq, bool ok) {
  AckMsg a;
  memset(&a, 0, sizeof(a));
  a.ack_seq = ack_seq;
  a.ok = ok ? 1 : 0;
  return send(&a, sizeof(a), MSG_ACK);
}

bool sendScan(ScanMsg& s) {
  if (s.n > SCAN_MAX_PTS) s.n = SCAN_MAX_PTS;
  return send(&s, SCAN_HEADER_BYTES + 2 * (size_t)s.n, MSG_SCAN);
}

}  // namespace msg
