"""Connect to the simulator (or anything speaking the bridge byte stream) for 3 s and count what it sends.

Usage:  python tools/sim_peek.py [host] [port]      default 127.0.0.1 8765
"""
import collections
import socket
import sys
import time

from cobs import cobs

KIND = {1: "RX_FROM_ROVER", 3: "BRIDGE_STATUS", 4: "BRIDGE_LOG"}
TYPE = {1: "HELLO", 2: "TELEM", 3: "SCAN", 4: "EVENT", 5: "ACK"}

host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

s = socket.create_connection((host, port), timeout=2)
buf, counts, bad, t0 = b"", collections.Counter(), 0, time.time()
while time.time() - t0 < 3:
    buf += s.recv(4096)
    *frames, buf = buf.split(b"\x00")
    for f in frames:
        if not f:
            continue
        try:
            d = cobs.decode(f)
        except cobs.DecodeError:
            bad += 1
            continue
        name = KIND.get(d[0], hex(d[0]))
        if d[0] == 1 and len(d) > 4:  # d[2] = magic, d[4] = message type
            name += "/" + TYPE.get(d[4], hex(d[4]))
        counts[name] += 1
s.close()
for k, v in sorted(counts.items()):
    print(f"{k:28s} {v:4d}  ({v / 3:.1f}/s)")
if bad:
    print(f"bad COBS frames: {bad}")
