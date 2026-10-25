// golden.h — the fixed TelemMsg / CmdMsg of tools/golden_gen.cpp, built by the target compiler.
// "dump_golden" prints them; they must equal tests/golden/telem.hex and cmd.hex byte for byte,
// which proves struct packing on the ESP32 matches the PC (docs/02 §4).
#pragma once
#include <Print.h>

void dumpGolden(Print& out);
