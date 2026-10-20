"""TCP server on 127.0.0.1:8765 emitting the exact serial byte stream the
ground_bridge would (docs/02 §4): SK_RX_FROM_ROVER frames with a fake RSSI,
plus SK_BRIDGE_STATUS at 1 Hz; accepts SK_TX_TO_ROVER frames carrying
CmdMsg. Implemented in Phase 2 (docs/06).
"""
