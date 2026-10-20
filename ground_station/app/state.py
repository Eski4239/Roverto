"""Latest telemetry values, hardware capabilities, 5-minute history ring
buffers, and the ground-station-only `link` block (docs/02 §3.2). Also
owns `hw.camera` (docs/02 §6.2 — never set by wire.py).
"""
from __future__ import annotations

import logging
import time
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
RX_HZ_WINDOW_MS = 2000
RTT_PENDING_MAX = 50
LOSS_WINDOW_MS = 10_000
LOSS_STALE_PCT = 50.0
# A message this recently received may still have siblings in flight (e.g.
# the TELEM for this seq arrived but its ack, sent moments later on a
# different code path, hasn't yet) -- counting it as "missing" right now
# would be premature, not loss.
LOSS_IN_FLIGHT_MS = 200
# Below this many samples in the window, "missing" is noise (one in-flight
# message can look like several percent) rather than a meaningful rate --
# report loss_pct as unknown (null/"--" in the UI) instead of a number.
LOSS_MIN_SAMPLES = 20
# A seq jump this large and backwards can't be normal reordering (docs/02 §1
# tolerates small out-of-order arrivals) or the 65535->0 wrap (which is a
# *forward* step under modulo arithmetic) -- it means the rover rebooted and
# restarted its counter from 0.
RESTART_BACKWARD_JUMP = 1000
# docs/02 §6.10 (GS-2): a rover message's t_ms this far behind the last one
# seen means the rover rebooted (millis() restarted at 0), not reordering.
RESTART_T_MS_TOLERANCE = 500
# millis() wraps at 2**32 after ~49.7 days; a t_ms this close to the wrap
# followed by a small t_ms is the wrap, not a restart.
T_MS_WRAP_GUARD = 60_000
# Immediately after a detected restart, a message whose t_ms is still this
# far ahead of the newest post-restart t_ms *and* whose seq is still this
# far ahead of the newest post-restart seq is a pre-reboot straggler
# (built/queued on the rover before it rebooted, delivered late) -- it must
# not feed loss/restart tracking, or its stale high seq re-poisons
# _highest_rover_seq right after the reset that was supposed to fix exactly
# that. Both conditions (t_ms AND seq) must hold, not just one: a resumed
# link after being silent for several seconds also has a t_ms (and often a
# seq) far ahead of the last thing the GS saw, but that's normal catch-up
# traffic, not a straggler -- it must be accepted.
STRAGGLER_T_MS_AHEAD = 1000
STRAGGLER_SEQ_AHEAD = 50
# The straggler rule above only makes sense for a few seconds right after a
# restart was detected (the rover's in-flight send/serial/ESP-NOW buffers
# drain quickly) -- applied permanently it would reject perfectly normal
# traffic after any long link gap, which is a much more common event than
# an actual reboot.
STRAGGLER_WINDOW_MS = 2000


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
        self._recent_telem_recv_ms: deque[float] = deque(maxlen=RX_HZ_WINDOW_MS // 10 + 10)
        self._highest_rover_seq: Optional[int] = None
        # (recv_wall_ms, seq) pairs, windowed to LOSS_WINDOW_MS -- loss_pct
        # must recover once a rover restart ages out of the window, not stay
        # wrong for the rest of the session.
        self._recent_rover_seqs: deque[tuple[float, int]] = deque()
        self._rssi_bridge_dbm: Optional[int] = None
        self._rssi_rover_dbm: Optional[int] = None
        self._bridge_tx_fail = 0
        self._pending_cmd_sent_ms: dict[int, float] = {}
        self._rtt_ms: Optional[float] = None

    def _reset_seq_tracking(self) -> None:
        self._highest_rover_seq = None
        self._recent_rover_seqs.clear()

    def reset(self) -> None:
        """A rover restart invalidates loss/seq tracking and in-flight RTTs
        (docs/02 §6.10): drop pending cmd->ack timestamps too, since they were
        sent to the pre-restart rover and will never be acked by seq."""
        self._reset_seq_tracking()
        self._pending_cmd_sent_ms.clear()
        self._rtt_ms = None

    def on_rover_seq(self, seq: int, *, recv_wall_ms: Optional[float] = None) -> None:
        """Feed every rover->GS message's seq (docs/02 §1: one counter per
        sender, shared across hello/telem/scan/event/ack) for loss_pct.

        Messages built on different code paths (e.g. an ack built while
        handling an inbound cmd vs. telem built in the main tick) can be
        *sent* with a lower seq than one sent moments before but *arrive*
        later, so arrival order is not strictly ascending even with zero
        loss. loss_pct is instead estimated from how much of the recent
        seq range span (within the last LOSS_WINDOW_MS) was never observed,
        which tolerates that reordering.

        A rover reboot restarts its seq counter from (near) 0. That looks
        like a huge backward jump that is *not* the normal 65535->0 wrap
        (which is a forward step under modulo arithmetic, handled below) --
        detected via RESTART_BACKWARD_JUMP, it resets loss tracking instead
        of being counted as ~64k lost frames.

        The same signed 16-bit distance used by _loss_pct (relative to the
        highest seq seen so far, not a plain forward/backward %) decides
        both "is this a forward wrap" and "is this a restart", so the two
        checks can't disagree with each other.
        """
        if recv_wall_ms is None:
            recv_wall_ms = time.time() * 1000.0

        if self._highest_rover_seq is not None:
            rel = ((seq - self._highest_rover_seq + 32768) % 65536) - 32768
            if rel < 0 and -rel >= RESTART_BACKWARD_JUMP:
                log.warning(
                    "ROVER_RESTART: seq jumped from %d to %d, resetting loss tracking",
                    self._highest_rover_seq, seq,
                )
                self._reset_seq_tracking()

        self._recent_rover_seqs.append((recv_wall_ms, seq))
        cutoff = recv_wall_ms - LOSS_WINDOW_MS
        while self._recent_rover_seqs and self._recent_rover_seqs[0][0] < cutoff:
            self._recent_rover_seqs.popleft()

        if self._highest_rover_seq is None:
            self._highest_rover_seq = seq
        else:
            rel = ((seq - self._highest_rover_seq + 32768) % 65536) - 32768
            if rel > 0:
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

    def _loss_pct(self, now_wall_ms: float) -> Optional[float]:
        cutoff = now_wall_ms - LOSS_WINDOW_MS
        all_recent = [(t, seq) for (t, seq) in self._recent_rover_seqs if t >= cutoff]
        if len(all_recent) < LOSS_MIN_SAMPLES:
            # Too few samples for "missing" to mean anything yet (e.g. right
            # after a restart reset the window) -- unknown, not zero.
            return None

        all_seqs = [seq for (_t, seq) in all_recent]
        # Unwrap relative to the most recently *received* seq (not the first
        # seq in arrival order): an EVENT/ACK built on a different code path
        # can arrive slightly out of seq order (D-003), e.g. seq 18 after
        # seq 20. Unwrapping against seqs[0]=20 would put 18 at (18-20)%65536
        # = 65534 -- a bogus ~65536-wide span. A signed 16-bit distance from
        # the latest seq keeps "slightly behind" messages close to 0 instead.
        ref = all_seqs[-1]
        unwrap = lambda s: ((s - ref + 32768) % 65536) - 32768  # noqa: E731
        unwrapped_all = {unwrap(s) for s in all_seqs}

        # A seq received in the last LOSS_IN_FLIGHT_MS may still have
        # siblings in flight (its ack/the next telem hasn't landed yet) --
        # don't count the *window bounds* or the *missing* tally against
        # messages that haven't had time to be a real gap yet. Excluding
        # them from "settled" still leaves them in unwrapped_all, so a
        # sibling that *has* landed isn't double-counted as both present
        # and missing.
        in_flight_cutoff = now_wall_ms - LOSS_IN_FLIGHT_MS
        settled = [unwrap(seq) for (t, seq) in all_recent if t < in_flight_cutoff]
        if len(settled) < 2:
            return 0.0

        # Span/expected come only from settled seqs (an in-flight message
        # hasn't been waiting long enough to define "how wide the gap is"
        # yet); but a slot within that span counts as present if *any*
        # message landed there, settled or still in flight, so an in-flight
        # sibling that fills a settled gap isn't double-counted as missing.
        span = max(settled) - min(settled) + 1
        expected = max(span, len(settled))
        present_in_span = sum(
            1 for u in unwrapped_all if min(settled) <= u <= max(settled)
        )
        missing = expected - present_in_span
        return max(0.0, missing / expected * 100.0)

    def _state(self, now_wall_ms: float, *, connected: bool, loss_pct: Optional[float]) -> str:
        if not connected:
            return "NO_BRIDGE"
        if self._last_telem_recv_ms is None:
            return "LOST"
        age_ms = now_wall_ms - self._last_telem_recv_ms
        if age_ms >= LINK_STALE_MS:
            return "LOST"
        # Frames are still arriving (OK/STALE by age) but more than half are
        # being lost -- show STALE rather than a falsely-healthy OK. Unknown
        # loss_pct (too few samples yet) can't fail this check -- fall
        # through to the age-based OK/STALE call below instead.
        if loss_pct is not None and loss_pct > LOSS_STALE_PCT:
            return "STALE"
        if age_ms < LINK_OK_MS:
            return "OK"
        return "STALE"

    def to_block(
        self, *, now_wall_ms: float, connected: bool, serial_port: Optional[str],
    ) -> LinkBlock:
        loss_pct = self._loss_pct(now_wall_ms)
        return LinkBlock(
            state=self._state(now_wall_ms, connected=connected, loss_pct=loss_pct),
            rx_hz=round(self._rx_hz(now_wall_ms), 1),
            loss_pct=round(loss_pct, 2) if loss_pct is not None else None,
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
        self.ring_soc_pct = RingBuffer()

        # Session min/max (docs/03 §2 "min/max of session") -- unlike the
        # ring buffers above, these never trim: they must survive past the
        # 5-minute window for as long as this GroundState lives.
        self._session_minmax: dict[str, tuple[float, float]] = {}

        self._last_t_ms: Optional[int] = None
        self._newest_post_restart_t_ms: Optional[int] = None
        self._newest_post_restart_seq: Optional[int] = None
        self._restart_detected_wall_ms: Optional[float] = None
        self._hello_seen_since_restart = False
        self._awaiting_hello_request = False
        self.straggler_count = 0  # debug counter: pre-reboot stragglers dropped

        # Mission clock is backend-owned (set once, at the first TELEM after
        # this process started) so a page refresh or a rover reboot doesn't
        # reset it -- only restarting the ground station itself does.
        self.mission_start_wall_ms: Optional[float] = None

    def _check_restart(
        self, t_ms: int, seq: int, recv_wall_ms: float,
        *, is_hello: bool, hello_seq: Optional[int],
    ) -> bool:
        """docs/02 §6.10 (GS-2): detect a rover reboot from its own t_ms/seq
        clock, not wall-clock/link state (a USB reconnect is not a restart).

        Runs for every rover message (HELLO/TELEM/EVENT/ACK/SCAN fragment) on
        one shared path, so a message type that skipped this check can't
        slip a pre-reboot seq past the restart reset. Returns False for a
        message that must be dropped entirely (built/queued on the rover
        before it rebooted, delivered late after the restart) -- the caller
        must not feed it to on_rover_seq/loss tracking or use it to update
        state.
        """
        if (
            self._restart_detected_wall_ms is not None
            and recv_wall_ms - self._restart_detected_wall_ms < STRAGGLER_WINDOW_MS
            and self._newest_post_restart_t_ms is not None
            and t_ms > self._newest_post_restart_t_ms + STRAGGLER_T_MS_AHEAD
            and self._newest_post_restart_seq is not None
            and ((seq - self._newest_post_restart_seq) % 65536) > STRAGGLER_SEQ_AHEAD
        ):
            self.straggler_count += 1
            return False

        restarted = False
        if self._last_t_ms is not None:
            is_wrap = (
                self._last_t_ms > 2**32 - T_MS_WRAP_GUARD
                and t_ms < T_MS_WRAP_GUARD
            )
            if not is_wrap and t_ms < self._last_t_ms - RESTART_T_MS_TOLERANCE:
                restarted = True
            if is_hello and hello_seq == 0 and t_ms < self._last_t_ms:
                restarted = True

        if restarted:
            self.link.reset()
            self._scan_reassembler.reset()
            reason = self.hello.reset_reason if (is_hello and self.hello) else "pending"
            self.events.append(EventMsg(
                t=t_ms, seq=0, level="warn", code="ROVER_RESTART",
                msg=f"rover restart detected (reset_reason={reason})",
            ))
            self._hello_seen_since_restart = is_hello
            self._awaiting_hello_request = not is_hello
            self._newest_post_restart_t_ms = t_ms
            self._newest_post_restart_seq = seq
            self._restart_detected_wall_ms = recv_wall_ms
        elif is_hello:
            self._hello_seen_since_restart = True
            self._awaiting_hello_request = False
        elif not self._hello_seen_since_restart:
            # TELEM arrived but no HELLO seen since the last restart (GS-2
            # "GS also" clause) -- keep requesting one.
            self._awaiting_hello_request = True

        self._last_t_ms = t_ms
        if self._newest_post_restart_t_ms is None or t_ms > self._newest_post_restart_t_ms:
            self._newest_post_restart_t_ms = t_ms
        if self._newest_post_restart_seq is None or (
            (seq - self._newest_post_restart_seq) % 65536 < 32768
        ):
            self._newest_post_restart_seq = seq
        return True

    def _update_session_minmax(self, field: str, value: Optional[float]) -> None:
        if value is None:
            return
        lo, hi = self._session_minmax.get(field, (value, value))
        self._session_minmax[field] = (min(lo, value), max(hi, value))

    def needs_hello_request(self) -> bool:
        return self._awaiting_hello_request

    def ingest(self, msg, *, rssi: Optional[int], recv_wall_ms: float) -> None:
        if isinstance(msg, HelloMsg):
            if not self._check_restart(
                msg.t, msg.seq, recv_wall_ms, is_hello=True, hello_seq=msg.seq,
            ):
                return
            self.hello = msg
            self.link.on_rover_seq(msg.seq, recv_wall_ms=recv_wall_ms)
        elif isinstance(msg, TelemMsg):
            if not self._check_restart(
                msg.t, msg.seq, recv_wall_ms, is_hello=False, hello_seq=None,
            ):
                return
            if self.mission_start_wall_ms is None:
                self.mission_start_wall_ms = recv_wall_ms
            self.telem = msg
            self.link.on_rover_seq(msg.seq, recv_wall_ms=recv_wall_ms)
            self.link.on_telem(msg, recv_wall_ms=recv_wall_ms, rssi=rssi)
            self.ring_temp_c.append(msg.t, msg.env.temp_c)
            self.ring_hum_pct.append(msg.t, msg.env.hum_pct)
            self.ring_press_hpa.append(msg.t, msg.env.press_hpa)
            self.ring_lux.append(msg.t, msg.light.lux)
            self.ring_soc_pct.append(msg.t, msg.pwr.soc_pct)
            self._update_session_minmax("temp_c", msg.env.temp_c)
            self._update_session_minmax("hum_pct", msg.env.hum_pct)
            self._update_session_minmax("press_hpa", msg.env.press_hpa)
            self._update_session_minmax("lux", msg.light.lux)
        elif isinstance(msg, EventMsg):
            if not self._check_restart(
                msg.t, msg.seq, recv_wall_ms, is_hello=False, hello_seq=None,
            ):
                return
            self.events.append(msg)
            self.link.on_rover_seq(msg.seq, recv_wall_ms=recv_wall_ms)
        elif isinstance(msg, AckMsg):
            if not self._check_restart(
                msg.t, msg.seq, recv_wall_ms, is_hello=False, hello_seq=None,
            ):
                return
            self.link.on_rover_seq(msg.seq, recv_wall_ms=recv_wall_ms)
            self.link.on_ack(msg, recv_wall_ms=recv_wall_ms)
        elif isinstance(msg, wire.BridgeStatus):
            self.link.on_bridge_status(msg)

    def ingest_scan_fragment(self, scan: ScanMsg, part: int, parts: int, now_ms: int) -> None:
        if not self._check_restart(
            scan.t, scan.seq, float(now_ms), is_hello=False, hello_seq=None,
        ):
            return
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

        recent_events = list(self.events)[-10:][::-1]  # newest first
        return {
            "hello": hello_dump,
            "telem": self.telem.model_dump() if self.telem else None,
            "scan": self.scan.model_dump() if self.scan else None,
            "events": [e.model_dump() for e in self.events],
            "recent_events": [
                {"t": e.t, "level": e.level, "code": e.code, "msg": e.msg}
                for e in recent_events
            ],
            "mission_start_wall_ms": self.mission_start_wall_ms,
            "history": {
                "temp_c": self.ring_temp_c.values(),
                "hum_pct": self.ring_hum_pct.values(),
                "press_hpa": self.ring_press_hpa.values(),
                "lux": self.ring_lux.values(),
                "soc_pct": self.ring_soc_pct.values(),
            },
            "session_minmax": {
                field: list(bounds) for field, bounds in self._session_minmax.items()
            },
            "link": self.link.to_block(
                now_wall_ms=now_wall_ms, connected=connected, serial_port=serial_port,
            ).model_dump(),
        }
