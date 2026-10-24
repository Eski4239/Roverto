# espnow_beacon (temporary)

Stands in for `firmware/rover_main` so `ground_bridge` can be tested over the air before the real
rover firmware exists. Sends golden `HelloMsg`/`TelemMsg` bytes to the bridge's MAC and prints any
`CmdMsg` it receives, replying with `AckMsg` per the ack rule (docs/02 §6).

**Flash it, test the bridge, then reflash rover_main once R3 is ready — do not leave this running
on real hardware.**

## Build

```powershell
python tools/espnow_beacon/gen_golden_arrays.py   # regenerate golden_payloads.h from tests/golden/
cd tools/espnow_beacon
pio run -t upload --upload-port COM4
pio device monitor -b 115200 -p COM4
```

Regenerate `golden_payloads.h` whenever `tests/golden/hello.hex` or `telem.hex` change — it's
generated, gitignored, and must never be hand-edited.
