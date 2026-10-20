"""Scan fragment reassembly — docs/02 §2.3.

Up to 100 points per ScanMsg fragment; multiple fragments share a scan_id.
If a fragment is still missing 300 ms after the first one for that scan_id
arrived, the scan is emitted with the missing angles as null (docs/02 §6.7:
every fragment carries the same pose — the pose at the start of the scan).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ground_station.app.protocol import ScanMsg, ScanPose

DEFAULT_TIMEOUT_MS = 300


@dataclass
class _PendingScan:
    scan_id: int
    parts: int
    pose: ScanPose
    src: str
    seq: int
    t_ms: int
    first_seen_ms: int
    pts_per_fragment: int = 0
    fragments: dict[int, list[list[Optional[float]]]] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return len(self.fragments) == self.parts

    def merged_pts(self) -> list[list[Optional[float]]]:
        pts: list[list[Optional[float]]] = []
        for part in range(self.parts):
            frag = self.fragments.get(part)
            if frag is None:
                pts.extend([None, None] for _ in range(self.pts_per_fragment))
            else:
                pts.extend(frag)
        return pts

    def to_scan(self) -> ScanMsg:
        return ScanMsg(
            t=self.t_ms, seq=self.seq, src=self.src, scan_id=self.scan_id,
            pose=self.pose, pts=self.merged_pts(),
        )


class ScanReassembler:
    """Reassembles ScanMsg fragments by scan_id. One sweep in flight at a time
    per src is the common case; keyed by (src, scan_id) to be safe."""

    def __init__(self, timeout_ms: int = DEFAULT_TIMEOUT_MS):
        self._timeout_ms = timeout_ms
        self._pending: dict[tuple[str, int], _PendingScan] = {}

    def add_fragment(
        self, scan: ScanMsg, part: int, parts: int, now_ms: int,
    ) -> Optional[ScanMsg]:
        """Feed one decoded fragment. Returns the completed ScanMsg once all
        fragments have arrived, else None."""
        key = (scan.src, scan.scan_id)
        pending = self._pending.get(key)
        if pending is None:
            pending = _PendingScan(
                scan_id=scan.scan_id, parts=parts, pose=scan.pose, src=scan.src,
                seq=scan.seq, t_ms=scan.t, first_seen_ms=now_ms,
            )
            self._pending[key] = pending

        pending.fragments[part] = scan.pts
        if pending.pts_per_fragment == 0:
            pending.pts_per_fragment = len(scan.pts)
        if pending.is_complete():
            del self._pending[key]
            return pending.to_scan()
        return None

    def poll_timeouts(self, now_ms: int) -> Optional[ScanMsg]:
        """Call periodically; emits the oldest timed-out scan with missing
        angles as null, or None if nothing has timed out yet."""
        for key, pending in list(self._pending.items()):
            if now_ms - pending.first_seen_ms >= self._timeout_ms:
                del self._pending[key]
                return pending.to_scan()
        return None

    def reset(self) -> None:
        """Drop all partial fragments — a rover restart invalidates them."""
        self._pending.clear()
