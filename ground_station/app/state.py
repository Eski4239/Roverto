"""Latest telemetry values, hardware capabilities, 5-minute history ring
buffers, and the ground-station-only `link` block (docs/02 §3.2). Also
owns `hw.camera` (docs/02 §6.2 — never set by wire.py).
"""
from __future__ import annotations

import logging
import tomllib
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path
from typing import Optional

from ground_station.app import wire
from ground_station.app.protocol import (
    AckMsg,
    EventMsg,
    HelloMsg,
    HwCamera,
    LinkBlock,
    ScanMsg,
    TelemMsg,
)
from ground_station.app.scan_reassembly import ScanReassembler

log = logging.getLogger("state")

LINK_OK_MS = 300
LINK_STALE_MS = 2000
RING_WINDOW_MS = 5 * 60 * 1000
LOSS_WINDOW = 100
RX_HZ_WINDOW_MS = 2000
RTT_PENDING_MAX = 50


def load_config(path: Path) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


class RingBuffer:
    """Fixed-duration (default 5 min) sample buffer of (t_ms, value)."""

    def __init__(self, window_ms: int = RING_WINDOW_MS) -> None:
        self._window_ms = window_ms
        self._samples: deque[tuple[int, float]] = deque()

    def append(self, t_ms: int, value: Optional[float]) -> None:
        if value is None:
            return
        self._samples.append((t_ms, value))
        cutoff = t_ms - self._window_ms
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def values(self) -> list[tuple[int, float]]:
        return list(self._samples)


class LinkTracker:
    """Derives the docs/02 §3.2 `link` block from observed traffic."""

    def __init__(self) -> None:
        self._last_telem_recv_ms: Optional[float] = None
        self._recent_telem_recv_ms: deque[float] = deque(maxlen=LOSS_WINDOW)
        self._highest_rover_seq: Optional[int] = None
        self._recent_rover_seqs: deque[int] = deque(maxlen=LOSS_WINDOW)
        self._rssi_bridge_dbm: Optional[int] = None
        self._rssi_rover_dbm: Optional[int] = None
        self._bridge_tx_fail = 0
        self._pending_cmd_sent_ms: dict[int, float] = {}
        self._rtt_ms: Optional[float] = None

    def on_rover_seq(self, seq: int) -> None:
        """Feed every rover->GS message's seq (docs/02 §1: one counter per
        sender, shared across hello/telem/scan/event/ack) for loss_pct.

        Messages built on different code paths (e.g. an ack built while
        handling an inbound cmd vs. telem built in the main tick) can be
        *sent* with a lower seq than one sent moments before but *arrive*
        later, so arrival order is not strictly ascending even with zero
        loss. loss_pct is instead estimated from how much of the recent
        seq range span was never observed, which tolerates that reordering.
        """
        self._recent_rover_seqs.append(seq)
        if self._highest_rover_seq is None or (
            (seq - self._highest_rover_seq) % 65536 < 32768
        ):
            self._highest_rover_seq = seq

    def on_telem(self, msg: TelemMsg, *, recv_wall_ms: float, rssi: Optional[int]) -> None:
        self._last_telem_recv_ms = recv_wall_ms
        self._recent_telem_recv_ms.append(recv_wall_ms)
        self._rssi_rover_dbm = msg.sys.rssi_dbm
        if rssi is not None:
            self._rssi_bridge_dbm = rssi

    def on_bridge_status(self, status: wire.BridgeStatus) -> None:
        self._bridge_tx_fail = status.tx_fail
        self._rssi_bridge_dbm = status.last_rssi

    def on_cmd_sent(self, seq: int, sent_wall_ms: float) -> None:
        self._pending_cmd_sent_ms[seq] = sent_wall_ms
        if len(self._pending_cmd_sent_ms) > RTT_PENDING_MAX:
            oldest = min(self._pending_cmd_sent_ms)
            del self._pending_cmd_sent_ms[oldest]

    def on_ack(self, msg: AckMsg, *, recv_wall_ms: float) -> None:
        sent_ms = self._pending_cmd_sent_ms.pop(msg.ack_seq, None)
        if sent_ms is not None:
            self._rtt_ms = recv_wall_ms - sent_ms

    def _rx_hz(self, now_wall_ms: float) -> float:
        cutoff = now_wall_ms - RX_HZ_WINDOW_MS
        count = sum(1 for t in self._recent_telem_recv_ms if t >= cutoff)
        return count / (RX_HZ_WINDOW_MS / 1000.0)

    def _loss_pct(self) -> float:
        seqs = self._recent_rover_seqs
        if len(seqs) < 2:
            return 0.0
        span = (max(seqs) - min(seqs)) % 65536 + 1
        expected = max(span, len(seqs))
        missing = expected - len(set(seqs))
        return max(0.0, missing / expected * 100.0)

    def _state(self, now_wall_ms: float, *, connected: bool) -> str:
        if not connected:
            return "NO_BRIDGE"
        if self._last_telem_recv_ms is None:
            return "LOST"
        age_ms = now_wall_ms - self._last_telem_recv_ms
        if age_ms < LINK_OK_MS:
            return "OK"
        if age_ms < LINK_STALE_MS:
            return "STALE"
        return "LOST"

    def to_block(
        self, *, now_wall_ms: float, connected: bool, serial_port: Optional[str],
    ) -> LinkBlock:
        return LinkBlock(
            state=self._state(now_wall_ms, connected=connected),
            rx_hz=round(self._rx_hz(now_wall_ms), 1),
            loss_pct=round(self._loss_pct(), 2),
            rtt_ms=self._rtt_ms,
            rssi_bridge_dbm=self._rssi_bridge_dbm,
            rssi_rover_dbm=self._rssi_rover_dbm,
            bridge_tx_fail=self._bridge_tx_fail,
            serial_port=serial_port,
        )


class GroundState:
    """Aggregates the latest hello/telem/scan, history, and link health."""

    def __init__(self) -> None:
        self.hello: Optional[HelloMsg] = None
        self.telem: Optional[TelemMsg] = None
        self.scan: Optional[ScanMsg] = None
        self.camera: Optional[HwCamera] = None
        self.events: deque[EventMsg] = deque(maxlen=200)

        self.link = LinkTracker()
        self._scan_reassembler = ScanReassembler()

        self.ring_temp_c = RingBuffer()
        self.ring_hum_pct = RingBuffer()
        self.ring_press_hpa = RingBuffer()
        self.ring_lux = RingBuffer()

    def ingest(self, msg, *, rssi: Optional[int], recv_wall_ms: float) -> None:
        if isinstance(msg, HelloMsg):
            self.hello = msg
            self.link.on_rover_seq(msg.seq)
        elif isinstance(msg, TelemMsg):
            self.telem = msg
            self.link.on_rover_seq(msg.seq)
            self.link.on_telem(msg, recv_wall_ms=recv_wall_ms, rssi=rssi)
            self.ring_temp_c.append(msg.t, msg.env.temp_c)
            self.ring_hum_pct.append(msg.t, msg.env.hum_pct)
            self.ring_press_hpa.append(msg.t, msg.env.press_hpa)
            self.ring_lux.append(msg.t, msg.light.lux)
        elif isinstance(msg, EventMsg):
            self.events.append(msg)
            self.link.on_rover_seq(msg.seq)
        elif isinstance(msg, AckMsg):
            self.link.on_rover_seq(msg.seq)
            self.link.on_ack(msg, recv_wall_ms=recv_wall_ms)
        elif isinstance(msg, wire.BridgeStatus):
            self.link.on_bridge_status(msg)

    def ingest_scan_fragment(self, scan: ScanMsg, part: int, parts: int, now_ms: int) -> None:
        self.link.on_rover_seq(scan.seq)
        completed = self._scan_reassembler.add_fragment(scan, part, parts, now_ms)
        if completed is not None:
            self.scan = completed

    def poll_scan_timeouts(self, now_ms: int) -> None:
        completed = self._scan_reassembler.poll_timeouts(now_ms)
        if completed is not None:
            self.scan = completed

    def record_cmd_sent(self, seq: int, sent_wall_ms: float) -> None:
        self.link.on_cmd_sent(seq, sent_wall_ms)

    def probe_camera_once(self, camera_url: str) -> None:
        """Synchronous HTTP probe; call from a thread/executor, not the loop."""
        try:
            with urllib.request.urlopen(f"{camera_url}/status", timeout=2.0) as resp:
                present = resp.status == 200
        except (urllib.error.URLError, OSError):
            present = False
        self.camera = HwCamera(present=present, url=camera_url if present else None)

    def snapshot(
        self, *, now_wall_ms: float, connected: bool, serial_port: Optional[str],
    ) -> dict:
        hello_dump = self.hello.model_dump() if self.hello else None
        if hello_dump is not None and self.camera is not None:
            hello_dump["hw"]["camera"] = self.camera.model_dump()

        return {
            "hello": hello_dump,
            "telem": self.telem.model_dump() if self.telem else None,
            "scan": self.scan.model_dump() if self.scan else None,
            "events": [e.model_dump() for e in self.events],
            "link": self.link.to_block(
                now_wall_ms=now_wall_ms, connected=connected, serial_port=serial_port,
            ).model_dump(),
        }
