#!/usr/bin/env python3
"""Print a logs/<ts>/raw.bin file as a readable hex timeline.

Record format (ground_station/app/logger.py): <QBH t_us dir len> + bytes,
little-endian, dir 0=rx 1=tx.

Usage: python tools/rawbin_dump.py logs/20261020_1530/raw.bin
"""
from __future__ import annotations

import argparse
import struct
import sys

HEADER_FMT = "<QBH"
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_HEX_BYTES = 64


def dump(path: str) -> None:
    with open(path, "rb") as f:
        data = f.read()

    offset = 0
    n = len(data)
    while offset + HEADER_SIZE <= n:
        t_us, dir_byte, length = struct.unpack_from(HEADER_FMT, data, offset)
        offset += HEADER_SIZE
        payload = data[offset:offset + length]
        offset += length

        direction = "RX" if dir_byte == 0 else "TX"
        hex_str = payload[:MAX_HEX_BYTES].hex()
        if length > MAX_HEX_BYTES:
            hex_str += "..."
        print(f"{t_us:>18d}  {direction}  {length:>5d}  {hex_str}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="path to raw.bin")
    args = parser.parse_args(argv)
    dump(args.path)


if __name__ == "__main__":
    main(sys.argv[1:])
