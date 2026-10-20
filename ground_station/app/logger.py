"""Session recording: logs/<YYYYMMDD_HHMMSS>/raw.jsonl (every decoded
message, both directions, with laptop receive time), raw.bin (raw serial
bytes), telem.csv, events.csv.

raw.bin stores one record per read/write chunk:
    <QBH  little-endian: t_us(u64) dir(u8: 0=rx,1=tx) len(u16)  bytes>
Use tools/rawbin_dump.py to inspect it.
"""
from __future__ import annotations

import csv
import json
import struct
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, TextIO

from ground_station.app.protocol import EventMsg, TelemMsg

Direction = Literal["rx", "tx"]

TELEM_CSV_FIELDS = [
    "t", "seq",
    "env.temp_c", "env.hum_pct", "env.press_hpa", "env.alt_m",
    "light.lux",
    "pwr.vbat_v", "pwr.soc_pct", "pwr.ibat_a", "pwr.p_w",
    "mot.pwm_l", "mot.pwm_r", "mot.rpm_l", "mot.rpm_r",
    "odom.x_m", "odom.y_m", "odom.dist_m",
    "imu.roll_deg", "imu.pitch_deg", "imu.yaw_deg",
    "imu.ax_g", "imu.ay_g", "imu.az_g", "imu.gz_dps", "imu.temp_c",
    "sonar.angle_deg", "sonar.dist_cm",
    "state.mode", "state.estop", "state.wd_ok", "state.last_cmd_age_ms",
    "sys.rssi_dbm", "sys.heap_b", "sys.uptime_s", "sys.loop_hz", "sys.chip_temp_c",
]

EVENTS_CSV_FIELDS = ["t", "seq", "level", "code", "msg"]


def _flatten_telem(m: TelemMsg) -> dict:
    d = m.model_dump()
    row: dict = {"t": d["t"], "seq": d["seq"]}
    for field in TELEM_CSV_FIELDS[2:]:
        block, key = field.split(".")
        row[field] = d[block][key]
    return row


class SessionLogger:
    """Writes one session's logs under base_dir/<YYYYMMDD_HHMMSS>/."""

    def __init__(self, base_dir: Path, *, session_name: Optional[str] = None) -> None:
        name = session_name or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_dir = Path(base_dir) / name
        self.session_dir.mkdir(parents=True, exist_ok=True)

        self._raw_jsonl: TextIO = open(self.session_dir / "raw.jsonl", "a", encoding="utf-8")
        self._raw_bin = open(self.session_dir / "raw.bin", "ab")

        self._telem_csv_path = self.session_dir / "telem.csv"
        self._events_csv_path = self.session_dir / "events.csv"
        self._telem_writer: Optional[csv.DictWriter] = None
        self._telem_file: Optional[TextIO] = None
        self._events_writer: Optional[csv.DictWriter] = None
        self._events_file: Optional[TextIO] = None

    def _telem_dict_writer(self) -> csv.DictWriter:
        if self._telem_writer is None:
            is_new = not self._telem_csv_path.exists() or self._telem_csv_path.stat().st_size == 0
            self._telem_file = open(self._telem_csv_path, "a", newline="", encoding="utf-8")
            self._telem_writer = csv.DictWriter(self._telem_file, fieldnames=TELEM_CSV_FIELDS)
            if is_new:
                self._telem_writer.writeheader()
        return self._telem_writer

    def _events_dict_writer(self) -> csv.DictWriter:
        if self._events_writer is None:
            is_new = not self._events_csv_path.exists() or self._events_csv_path.stat().st_size == 0
            self._events_file = open(self._events_csv_path, "a", newline="", encoding="utf-8")
            self._events_writer = csv.DictWriter(self._events_file, fieldnames=EVENTS_CSV_FIELDS)
            if is_new:
                self._events_writer.writeheader()
        return self._events_writer

    def log_message(self, direction: Direction, msg, recv_time: float) -> None:
        record = {"t_laptop": recv_time, "dir": direction, "msg": msg.model_dump()}
        self._raw_jsonl.write(json.dumps(record) + "\n")
        self._raw_jsonl.flush()

        if isinstance(msg, TelemMsg):
            writer = self._telem_dict_writer()
            writer.writerow(_flatten_telem(msg))
            self._telem_file.flush()  # type: ignore[union-attr]
        elif isinstance(msg, EventMsg):
            writer = self._events_dict_writer()
            d = msg.model_dump()
            writer.writerow({k: d[k] for k in EVENTS_CSV_FIELDS})
            self._events_file.flush()  # type: ignore[union-attr]

    def log_raw_bytes(self, direction: Direction, data: bytes) -> None:
        dir_byte = 0 if direction == "rx" else 1
        t_us = time.time_ns() // 1000
        header = struct.pack("<QBH", t_us, dir_byte, len(data))
        self._raw_bin.write(header)
        self._raw_bin.write(data)
        self._raw_bin.flush()

    def close(self) -> None:
        self._raw_jsonl.close()
        self._raw_bin.close()
        if self._telem_file is not None:
            self._telem_file.close()
        if self._events_file is not None:
            self._events_file.close()

    def __enter__(self) -> "SessionLogger":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()
