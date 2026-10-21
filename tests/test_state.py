"""state.py unit tests — LinkTracker loss/rx_hz/rtt and GroundState.snapshot."""
from __future__ import annotations

from typing import Optional

from ground_station.app import wire
from ground_station.app.protocol import (
    AckMsg, HelloMsg, Hw, HwBattery, HwBuzzer, HwCurrent, HwEncoders, HwEnv,
    HwImu, HwLidar, HwLight, HwSonar, TelemEnv, TelemImu, TelemLight, TelemMot,
)
from ground_station.app.protocol import TelemMsg, TelemOdom, TelemPwr, TelemSonar, TelemState, TelemSys
from ground_station.app.state import RING_WINDOW_MS, GroundState, LinkTracker


def _telem(seq: int, t: int = 0) -> TelemMsg:
    return TelemMsg(
        t=t, seq=seq,
        env=TelemEnv(), light=TelemLight(), pwr=TelemPwr(),
        mot=TelemMot(pwm_l=0, pwm_r=0), odom=TelemOdom(),
        imu=TelemImu(), sonar=TelemSonar(),
        state=TelemState(mode="idle", estop=False, wd_ok=True, last_cmd_age_ms=0),
        sys=TelemSys(rssi_dbm=-60, heap_b=1000, uptime_s=1, loop_hz=100),
    )


def _telem_env(
    seq: int, t: int, *,
    temp_c: Optional[float] = None, soc_pct: Optional[float] = None,
    alt_m: Optional[float] = None, vbat_v: Optional[float] = None,
) -> TelemMsg:
    msg = _telem(seq, t)
    msg.env.temp_c = temp_c
    msg.env.alt_m = alt_m
    msg.pwr.soc_pct = soc_pct
    msg.pwr.vbat_v = vbat_v
    return msg


def _feed_seqs(tracker: LinkTracker, seqs: list[int], *, step_ms: float = 100.0, start_ms: float = 1000.0) -> Optional[float]:
    """Feed seqs spaced step_ms apart (default 100ms, well past the 200ms
    in-flight window by the time we snapshot) and return loss_pct at the end."""
    t = start_ms
    for seq in seqs:
        tracker.on_rover_seq(seq, recv_wall_ms=t)
        t += step_ms
    block = tracker.to_block(now_wall_ms=t + 300.0, connected=True, serial_port="COM5")
    return block.loss_pct


def test_loss_pct_below_min_samples_is_none():
    """Fewer than LOSS_MIN_SAMPLES in the window -> unknown, not 0% -- one
    in-flight message can look like several percent of a tiny window."""
    tracker = LinkTracker()
    loss = _feed_seqs(tracker, list(range(5)))
    assert loss is None


def test_loss_pct_no_gaps():
    tracker = LinkTracker()
    loss = _feed_seqs(tracker, list(range(25)))
    assert loss == 0.0


def test_loss_pct_with_gap():
    tracker = LinkTracker()
    seqs = list(range(25)) + [29]  # seqs 25-28 missing, well past in-flight
    loss = _feed_seqs(tracker, seqs)
    assert loss > 0.0


def test_loss_pct_tolerates_reordering():
    """docs/02 §1: seq is one counter per sender shared across message
    types; messages built on different code paths (e.g. an ack vs. the
    next telem) can arrive slightly out of seq order with zero real loss."""
    tracker = LinkTracker()
    seqs = list(range(10, 20)) + [21, 20, 22, 24, 23, 26, 25, 28, 27, 29]
    loss = _feed_seqs(tracker, seqs)
    assert loss == 0.0


def test_loss_pct_resets_on_rover_restart():
    """Bug repro: rover reboots, seq restarts from 0. A backwards jump this
    large must be recognised as a restart (not ~60k lost frames) and the
    loss window must recover to ~0 well within LOSS_WINDOW_MS, once there
    are enough post-restart samples to report a number at all."""
    tracker = LinkTracker()
    tracker.on_rover_seq(30000, recv_wall_ms=1000.0)
    tracker.on_rover_seq(0, recv_wall_ms=1001.0)  # rover restart
    t = 1002.0
    for seq in range(1, 25):
        tracker.on_rover_seq(seq, recv_wall_ms=t)
        t += 100.0
    block = tracker.to_block(now_wall_ms=t + 300.0, connected=True, serial_port="COM5")
    assert block.loss_pct is not None
    assert block.loss_pct < 5.0


def test_seq_wrap_65535_to_0_counts_as_no_loss():
    tracker = LinkTracker()
    seqs = list(range(65515, 65536)) + list(range(0, 10))
    loss = _feed_seqs(tracker, seqs)
    assert loss == 0.0


def test_loss_pct_one_message_slightly_out_of_order_is_zero():
    """Bug repro (D-003): an EVENT/ACK built on a different code path can
    arrive one seq behind the latest TELEM with zero real loss. Unwrapping
    against the first-arrived seq instead of the latest put an
    out-of-order seq at a huge negative offset -- a bogus ~65536-wide span."""
    tracker = LinkTracker()
    contiguous = list(range(1, 26))  # 1..25, no gaps
    # Swap 18 and 20's arrival order so 18 lands one message *after* 20.
    seqs = [s for s in contiguous if s not in (18, 20)]
    i = seqs.index(19)
    seqs = seqs[:i] + [20, 18, 19] + seqs[i + 1:]
    assert sorted(seqs) == contiguous  # same set, just reordered
    loss = _feed_seqs(tracker, seqs)
    assert loss == 0.0


def test_loss_pct_with_one_real_gap_among_reordering():
    tracker = LinkTracker()
    seqs = list(range(1, 21)) + [21, 22, 23, 25, 26, 27, 29, 30]
    loss = _feed_seqs(tracker, seqs)
    assert 0.0 < loss < 20.0


def test_loss_pct_wrap_with_reordering_is_zero():
    tracker = LinkTracker()
    seqs = list(range(65510, 65534)) + [65535, 65534, 0, 1, 2, 3]
    loss = _feed_seqs(tracker, seqs)
    assert loss == 0.0


def test_loss_pct_windowed_to_10s():
    """An old gap must age out of the 10 s window rather than depress
    loss_pct for the rest of the session."""
    tracker = LinkTracker()
    tracker.on_rover_seq(0, recv_wall_ms=0.0)
    tracker.on_rover_seq(100, recv_wall_ms=1.0)  # big gap, long ago
    t = 20_000.0
    for seq in range(200, 225):
        tracker.on_rover_seq(seq, recv_wall_ms=t)
        t += 100.0
    block = tracker.to_block(now_wall_ms=t + 300.0, connected=True, serial_port="COM5")
    assert block.loss_pct == 0.0


def test_loss_pct_ignores_in_flight_sample():
    """A seq received in the last LOSS_IN_FLIGHT_MS (200ms) may just not
    have had time to be joined by a sibling message yet (e.g. its ack) --
    it must not be counted as a gap purely for being the newest arrival."""
    tracker = LinkTracker()
    t = 1000.0
    for seq in range(25):
        tracker.on_rover_seq(seq, recv_wall_ms=t)
        t += 100.0
    # Snapshot immediately after the last seq (within the in-flight window)
    # rather than waiting -- the newest arrival alone must not read as loss.
    block = tracker.to_block(now_wall_ms=t, connected=True, serial_port="COM5")
    assert block.loss_pct == 0.0


def test_link_state_transitions():
    tracker = LinkTracker()
    tracker.on_rover_seq(0)
    tracker.on_telem(_telem(0), recv_wall_ms=1000.0, rssi=-50)
    ok = tracker.to_block(now_wall_ms=1100.0, connected=True, serial_port="COM5")
    assert ok.state == "OK"
    stale = tracker.to_block(now_wall_ms=1500.0, connected=True, serial_port="COM5")
    assert stale.state == "STALE"
    lost = tracker.to_block(now_wall_ms=3500.0, connected=True, serial_port="COM5")
    assert lost.state == "LOST"
    no_bridge = tracker.to_block(now_wall_ms=1100.0, connected=False, serial_port=None)
    assert no_bridge.state == "NO_BRIDGE"


def test_rtt_from_ack():
    tracker = LinkTracker()
    tracker.on_cmd_sent(seq=42, sent_wall_ms=1000.0)
    tracker.on_ack(AckMsg(t=0, seq=1, ack_seq=42, ok=True), recv_wall_ms=1023.0)
    block = tracker.to_block(now_wall_ms=1024.0, connected=True, serial_port="COM5")
    assert block.rtt_ms == 23.0


def test_ground_state_snapshot_empty():
    state = GroundState()
    snap = state.snapshot(now_wall_ms=1000.0, connected=False, serial_port=None)
    assert snap["hello"] is None
    assert snap["telem"] is None
    assert snap["link"]["state"] == "NO_BRIDGE"


def test_ground_state_ingest_telem_updates_snapshot():
    state = GroundState()
    state.ingest(_telem(1, t=500), rssi=-55, recv_wall_ms=1000.0)
    snap = state.snapshot(now_wall_ms=1010.0, connected=True, serial_port="COM5")
    assert snap["telem"]["seq"] == 1
    assert snap["link"]["state"] == "OK"
    assert snap["link"]["rssi_rover_dbm"] == -60
    assert snap["telem"]["state"]["mode"] == "idle"


def test_snapshot_history_and_session_minmax_track_env_values():
    state = GroundState()
    state.ingest(
        _telem_env(1, t=500, temp_c=20.0, soc_pct=80.0, alt_m=1.0, vbat_v=12.0),
        rssi=-55, recv_wall_ms=1000.0,
    )
    state.ingest(
        _telem_env(2, t=600, temp_c=25.0, soc_pct=79.0, alt_m=1.5, vbat_v=11.9),
        rssi=-55, recv_wall_ms=1100.0,
    )
    state.ingest(
        _telem_env(3, t=700, temp_c=18.0, soc_pct=81.0, alt_m=0.8, vbat_v=12.1),
        rssi=-55, recv_wall_ms=1200.0,
    )
    snap = state.snapshot(now_wall_ms=1300.0, connected=True, serial_port="COM5")

    assert snap["history"]["temp_c"] == [(500, 20.0), (600, 25.0), (700, 18.0)]
    assert snap["history"]["soc_pct"] == [(500, 80.0), (600, 79.0), (700, 81.0)]
    assert snap["history"]["alt_m"] == [(500, 1.0), (600, 1.5), (700, 0.8)]
    assert snap["history"]["vbat_v"] == [(500, 12.0), (600, 11.9), (700, 12.1)]
    assert snap["session_minmax"]["temp_c"] == [18.0, 25.0, (20.0 + 25.0 + 18.0) / 3]
    assert snap["session_minmax"]["alt_m"] == [0.8, 1.5, (1.0 + 1.5 + 0.8) / 3]


def test_session_minmax_survives_past_ring_window_while_ring_trims():
    """docs/03 §2: Environment shows 'min/max of session', distinct from the
    5-min sparkline window -- an old extreme value must stay in min/max even
    after the ring buffer has trimmed it out."""
    state = GroundState()
    state.ingest(_telem_env(1, t=0, temp_c=5.0), rssi=-55, recv_wall_ms=0.0)
    far_future_t_ms = RING_WINDOW_MS + 60_000
    state.ingest(_telem_env(2, t=far_future_t_ms, temp_c=22.0), rssi=-55, recv_wall_ms=far_future_t_ms)
    snap = state.snapshot(now_wall_ms=far_future_t_ms + 10.0, connected=True, serial_port="COM5")

    assert snap["history"]["temp_c"] == [(far_future_t_ms, 22.0)]
    assert snap["session_minmax"]["temp_c"] == [5.0, 22.0, (5.0 + 22.0) / 2]


def test_chart_history_survives_rover_restart_without_gap_or_zigzag():
    """Phase 5b expandable-tile charts (GET /api/history) are keyed by the
    GS's own receive wall-clock, not the rover's t_ms -- t_ms resets to 0 on
    every rover reboot (D-015), which would otherwise gap or zig-zag the
    ring. Fill a ring pre-restart, simulate a restart (t_ms back to 0), keep
    filling post-restart, and check the combined series is still in strictly
    increasing time order covering the full window with no gap."""
    state = GroundState()
    recv_ms = 0.0
    t_ms = 0
    seq = 0
    # Pre-restart: 10 s of samples 1 s apart, well past HISTORY_SAMPLE_PERIOD_MS.
    for _ in range(10):
        state.ingest(_telem(seq, t=t_ms), rssi=-55, recv_wall_ms=recv_ms)
        recv_ms += 1000.0
        t_ms += 1000
        seq += 1

    # Rover reboots: t_ms drops back near 0, seq resets too, but the GS's
    # own receive clock keeps climbing -- this is what must keep the ring sane.
    t_ms = 0
    seq = 0
    for _ in range(10):
        state.ingest(_telem(seq, t=t_ms), rssi=-55, recv_wall_ms=recv_ms)
        recv_ms += 1000.0
        t_ms += 1000
        seq += 1

    series = state.chart_history("sys.loop_hz")
    assert len(series) >= 15  # both halves present, nothing collapsed to one sample
    times = [t for t, _ in series]
    assert times == sorted(times)  # strictly increasing -- no zig-zag
    assert all(b - a > 0 for a, b in zip(times, times[1:]))  # no duplicate/zero-gap entries

    resp_t = [t for t, _ in series]
    cutoff_ms = resp_t[-1] - 300 * 1000
    windowed = [t for t in resp_t if t >= cutoff_ms]
    assert windowed == sorted(windowed)
    assert windowed[-1] - windowed[0] <= 300 * 1000 + 1000  # /api/history's own window slice stays sane


def test_restart_detected_from_backward_t_ms_at_30s_uptime():
    """GS-2: a reboot early in uptime (here: 30 s in) must be caught even
    though the seq delta is far too small to trip RESTART_BACKWARD_JUMP."""
    state = GroundState()
    state.ingest(_telem(300, t=30_000), rssi=-55, recv_wall_ms=1000.0)
    state.ingest(_telem(301, t=500), rssi=-55, recv_wall_ms=1001.0)
    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" in codes


def test_t_ms_wrap_at_2_32_is_not_a_restart():
    state = GroundState()
    state.ingest(_telem(1, t=2**32 - 1000), rssi=-55, recv_wall_ms=1000.0)
    state.ingest(_telem(2, t=500), rssi=-55, recv_wall_ms=1001.0)
    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" not in codes


def test_link_reconnect_is_not_a_restart():
    """Restart detection is driven only by t_ms/seq/HELLO, never by the
    connected/link-state flag -- a USB bridge replug must not be flagged."""
    state = GroundState()
    state.ingest(_telem(1, t=500), rssi=-55, recv_wall_ms=1000.0)
    state.snapshot(now_wall_ms=1010.0, connected=False, serial_port=None)
    state.snapshot(now_wall_ms=1020.0, connected=True, serial_port="COM5")
    state.ingest(_telem(2, t=600), rssi=-55, recv_wall_ms=1030.0)
    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" not in codes


def test_no_prior_restart_link_gap_traffic_is_accepted():
    """Baseline (no restart ever detected): a 5s silent link gap followed
    by traffic 5000ms ahead must be accepted outright. The straggler rule
    is gated on a restart having been detected at all
    (_restart_detected_wall_ms is None here) -- it must never trigger from
    ordinary link silence alone, with or without a prior restart."""
    state = GroundState()
    state.ingest(_telem(1, t=1000), rssi=-55, recv_wall_ms=1000.0)
    state.ingest(_telem(2, t=1100), rssi=-55, recv_wall_ms=1100.0)
    # link silent for 5s; rover keeps running, so t_ms/seq jump far ahead
    # on resume purely from elapsed time, not a reboot.
    state.ingest(_telem(52, t=6100), rssi=-55, recv_wall_ms=6100.0)

    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" not in codes
    assert state.straggler_count == 0
    assert state.telem is not None and state.telem.seq == 52
    block = state.link.to_block(now_wall_ms=6200.0, connected=True, serial_port="COM5")
    assert block.state == "OK"


def test_straggler_rule_expires_after_link_gap_not_a_restart():
    """GS-2 edge case: the straggler rule exists to drop pre-reboot messages
    delivered late right after a *detected restart*, not to reject normal
    catch-up traffic after any ordinary link gap (silence, not a reboot).
    Scenario: a restart is detected, then the link goes silent for 5s (out
    of ESP-NOW range, say) while the rover keeps running -- it is NOT the
    rover rebooting again. When traffic resumes with t_ms/seq far ahead of
    what the GS last saw, that message must be ACCEPTED (no second
    ROVER_RESTART, no straggler drop) because 5s is well past
    STRAGGLER_WINDOW_MS (2s): the straggler rule must have already expired.
    """
    state = GroundState()
    # Establish a restart so the straggler reference point exists at all.
    state.ingest(_telem(300, t=30_000), rssi=-55, recv_wall_ms=1000.0)
    state.ingest(_telem(301, t=500), rssi=-55, recv_wall_ms=1001.0)  # triggers restart
    restart_events_before = sum(1 for e in state.events if e.code == "ROVER_RESTART")
    assert restart_events_before == 1

    # Link silent for 5s (no ingest calls at all); rover's own clock/seq
    # keep advancing meanwhile. On resume, t_ms is >1000ms and seq is >50
    # ahead of what the GS saw right after the restart -- the straggler
    # condition's t_ms/seq checks alone would match, but 5s have passed.
    state.ingest(_telem(361, t=5600), rssi=-55, recv_wall_ms=6001.0)

    codes_after = [e for e in state.events if e.code == "ROVER_RESTART"]
    assert len(codes_after) == 1  # no second (spurious) restart detected
    assert state.straggler_count == 0
    assert state.telem is not None and state.telem.seq == 361
    block = state.link.to_block(now_wall_ms=6101.0, connected=True, serial_port="COM5")
    assert block.state == "OK"


def test_straggler_rule_would_reject_link_gap_traffic_if_permanent():
    """Proves the previous test actually exercises the time-box: with
    STRAGGLER_WINDOW_MS's expiry check removed (see the TEMP line this test
    asserts against directly), the exact same resumed-after-gap message
    would be wrongly dropped as a straggler -- straggler_count would go to
    1 instead of staying 0, exactly the false rejection the task warned
    about. This test calls the real _check_restart with the real module
    constants so it fails if someone widens/removes the window again."""
    state = GroundState()
    state.ingest(_telem(300, t=30_000), rssi=-55, recv_wall_ms=1000.0)
    state.ingest(_telem(301, t=500), rssi=-55, recv_wall_ms=1001.0)  # triggers restart

    newest_t_ms = state._newest_post_restart_t_ms
    newest_seq = state._newest_post_restart_seq
    resume_t_ms = 5600
    resume_seq = 361
    resume_wall_ms = 6001.0

    # Sanity: this scenario really does satisfy the t_ms/seq thresholds in
    # isolation -- otherwise a permanent rule wouldn't reject it either, and
    # this test would prove nothing.
    from ground_station.app.state import STRAGGLER_SEQ_AHEAD, STRAGGLER_T_MS_AHEAD, STRAGGLER_WINDOW_MS
    assert resume_t_ms > newest_t_ms + STRAGGLER_T_MS_AHEAD
    assert ((resume_seq - newest_seq) % 65536) > STRAGGLER_SEQ_AHEAD
    # And the wall-clock gap is indeed past the time-box, which is exactly
    # why the real (time-boxed) implementation accepts it:
    assert resume_wall_ms - state._restart_detected_wall_ms > STRAGGLER_WINDOW_MS

    accepted = state._check_restart(
        resume_t_ms, resume_seq, resume_wall_ms, is_hello=False, hello_seq=None,
    )
    assert accepted is True
    assert state.straggler_count == 0


def test_hello_seq_zero_first_message_ever_is_not_a_restart():
    """The very first message of a session can't be a restart -- there is
    no prior t_ms to have gone backward from."""
    state = GroundState()
    hello = HelloMsg(
        t=0, seq=0, fw="rover_main 0.1.0", reset_reason="POWERON",
        hw=Hw(
            imu=HwImu(present=True), env=HwEnv(present=True, model="bme280"),
            light=HwLight(present=True), sonar=HwSonar(present=True),
            battery=HwBattery(present=True, cells=3), current=HwCurrent(present=False),
            encoders=HwEncoders(present=False), lidar=HwLidar(present=False),
            buzzer=HwBuzzer(present=True),
        ),
    )
    state.ingest(hello, rssi=-55, recv_wall_ms=1000.0)
    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" not in codes
    assert state.needs_hello_request() is False


def test_f4_seq_jump_fallback_alone_still_runs_restart_side_effects():
    """F4: LinkTracker.on_rover_seq's own seq-jump fallback (independent of
    _check_restart's t_ms/HELLO-seq-0 detection) could fire by itself
    when t_ms stays within RESTART_T_MS_TOLERANCE but seq jumps backward
    by >= RESTART_BACKWARD_JUMP -- previously this reset LinkTracker's
    loss/seq tracking silently, without GroundState ever logging
    ROVER_RESTART, resetting the scan reassembler, or updating
    hello-tracking. Craft exactly that: t_ms advances normally (no t_ms-
    based restart), seq jumps back by 1200 (>= RESTART_BACKWARD_JUMP)."""
    state = GroundState()
    state.ingest(_telem(5000, t=10_000), rssi=-55, recv_wall_ms=1000.0)
    assert [e.code for e in state.events] == []  # sanity: no restart yet

    # t_ms advances normally (well within tolerance of the prior message),
    # but seq jumps backward by 1200 -- only the fallback can catch this.
    state.ingest(_telem(3800, t=10_100), rssi=-55, recv_wall_ms=1100.0)

    codes = [e.code for e in state.events]
    assert "ROVER_RESTART" in codes, (
        "seq-jump-only restart must still be reported by GroundState, not "
        "just silently absorbed by LinkTracker's own reset"
    )


def test_f5_scan_fragment_passes_real_recv_wall_ms_to_on_rover_seq():
    """F5: ingest_scan_fragment's on_rover_seq call previously omitted
    recv_wall_ms, defaulting to time.time() instead of the caller-supplied
    now_ms -- inconsistent with every other ingest() call site. Confirm
    the scan fragment's seq is recorded under the now_ms-derived
    timestamp, not a wall-clock one that could diverge from it: feed a
    seq via a scan fragment at a now_ms far in the "past" relative to
    real wall-clock, then check loss_pct's window (keyed off recv_wall_ms)
    reflects that supplied time, not time.time()."""
    from ground_station.app.protocol import ScanMsg, ScanPose

    state = GroundState()
    scan = ScanMsg(
        t=500, seq=42, src="sonar", scan_id=1, pose=ScanPose(), pts=[[0.0, 100.0]],
    )
    # now_ms is in GS-monotonic-ish space, deliberately not close to
    # time.time()*1000 -- if on_rover_seq silently used time.time()
    # instead, the recorded sample's recv_wall_ms would land far outside
    # this now_ms-based window check below.
    now_ms = 2_000_000_000  # an arbitrary, real-world-wall-clock-distinct value
    state.ingest_scan_fragment(scan, 1, 1, now_ms)

    assert len(state.link._recent_rover_seqs) == 1
    recorded_wall_ms, recorded_seq = state.link._recent_rover_seqs[0]
    assert recorded_seq == 42
    assert recorded_wall_ms == float(now_ms), (
        f"expected on_rover_seq to receive now_ms={now_ms} as recv_wall_ms, "
        f"got {recorded_wall_ms} (likely defaulted to time.time() instead)"
    )
