"""state.py unit tests — LinkTracker loss/rx_hz/rtt and GroundState.snapshot."""
from __future__ import annotations

from ground_station.app import wire
from ground_station.app.protocol import AckMsg, TelemEnv, TelemImu, TelemLight, TelemMot
from ground_station.app.protocol import TelemMsg, TelemOdom, TelemPwr, TelemSonar, TelemState, TelemSys
from ground_station.app.state import GroundState, LinkTracker


def _telem(seq: int, t: int = 0) -> TelemMsg:
    return TelemMsg(
        t=t, seq=seq,
        env=TelemEnv(), light=TelemLight(), pwr=TelemPwr(),
        mot=TelemMot(pwm_l=0, pwm_r=0), odom=TelemOdom(),
        imu=TelemImu(), sonar=TelemSonar(),
        state=TelemState(mode="idle", estop=False, wd_ok=True, last_cmd_age_ms=0),
        sys=TelemSys(rssi_dbm=-60, heap_b=1000, uptime_s=1, loop_hz=100),
    )


def test_loss_pct_no_gaps():
    tracker = LinkTracker()
    for seq in range(5):
        tracker.on_rover_seq(seq)
        tracker.on_telem(_telem(seq), recv_wall_ms=1000.0 + seq, rssi=-50)
    block = tracker.to_block(now_wall_ms=1010.0, connected=True, serial_port="COM5")
    assert block.loss_pct == 0.0


def test_loss_pct_with_gap():
    tracker = LinkTracker()
    tracker.on_rover_seq(0, recv_wall_ms=1000.0)
    tracker.on_telem(_telem(0), recv_wall_ms=1000.0, rssi=-50)
    tracker.on_rover_seq(5, recv_wall_ms=1001.0)  # 4 missing
    tracker.on_telem(_telem(5), recv_wall_ms=1001.0, rssi=-50)
    block = tracker.to_block(now_wall_ms=1002.0, connected=True, serial_port="COM5")
    assert block.loss_pct > 0.0


def test_loss_pct_tolerates_reordering():
    """docs/02 §1: seq is one counter per sender shared across message
    types; messages built on different code paths (e.g. an ack vs. the
    next telem) can arrive slightly out of seq order with zero real loss."""
    tracker = LinkTracker()
    for seq in [10, 12, 11, 14, 13, 16, 15]:
        tracker.on_rover_seq(seq, recv_wall_ms=1000.0)
    block = tracker.to_block(now_wall_ms=1000.0, connected=True, serial_port="COM5")
    assert block.loss_pct == 0.0


def test_loss_pct_resets_on_rover_restart():
    """Bug repro: rover reboots, seq restarts from 0. A backwards jump this
    large must be recognised as a restart (not ~60k lost frames) and the
    loss window must recover to ~0 well within LOSS_WINDOW_MS."""
    tracker = LinkTracker()
    tracker.on_rover_seq(30000, recv_wall_ms=1000.0)
    tracker.on_rover_seq(0, recv_wall_ms=1001.0)  # rover restart
    for i, seq in enumerate(range(1, 10)):
        tracker.on_rover_seq(seq, recv_wall_ms=1002.0 + i)
    block = tracker.to_block(now_wall_ms=1011.0, connected=True, serial_port="COM5")
    assert block.loss_pct < 5.0


def test_seq_wrap_65535_to_0_counts_as_no_loss():
    tracker = LinkTracker()
    tracker.on_rover_seq(65533, recv_wall_ms=1000.0)
    tracker.on_rover_seq(65534, recv_wall_ms=1001.0)
    tracker.on_rover_seq(65535, recv_wall_ms=1002.0)
    tracker.on_rover_seq(0, recv_wall_ms=1003.0)
    tracker.on_rover_seq(1, recv_wall_ms=1004.0)
    block = tracker.to_block(now_wall_ms=1005.0, connected=True, serial_port="COM5")
    assert block.loss_pct == 0.0


def test_loss_pct_windowed_to_10s():
    """An old gap must age out of the 10 s window rather than depress
    loss_pct for the rest of the session."""
    tracker = LinkTracker()
    tracker.on_rover_seq(0, recv_wall_ms=0.0)
    tracker.on_rover_seq(100, recv_wall_ms=1.0)  # big gap, long ago
    for i, seq in enumerate(range(200, 210)):
        tracker.on_rover_seq(seq, recv_wall_ms=20_000.0 + i)
    block = tracker.to_block(now_wall_ms=20_010.0, connected=True, serial_port="COM5")
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
