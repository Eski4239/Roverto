"""Regenerate docs/TEAM_BRIEF.md from the repo docs.  Usage: python tools/build_brief.py"""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PREAMBLE = r'''# Rover Project — Team Brief (all-in-one context for Claude)

> **What this is:** every design decision, the protocol, the pin plan, the hardware roadmap and the build
> prompts for our Space Vehicles & Missiles rover, in one file. Give it to Claude so it has full
> context before writing any Arduino (ESP32) or Python code.
> Generated from the repo files on __DATE__ by `tools/build_brief.py`. If you change a doc in the repo, regenerate this
> file (or just tell Claude which section changed).

## How to use this with Claude Pro

**Option A — Claude chat (claude.ai / desktop app)**
1. Create a new **Project** called "Rover firmware + ground station".
2. Upload this file (`TEAM_BRIEF.md`) to the project's **knowledge**. Also upload
   `firmware/common/rover_protocol.h` (it's also copied in §6 below).
3. Paste this into the project's **custom instructions**:
   ```
   You are helping build the firmware (ESP32, Arduino framework via PlatformIO) and the Python ground
   station for our university rover. TEAM_BRIEF.md is the source of truth: follow its "Hard rules",
   protocol and pin plan exactly. Never invent protocol fields; if something is missing or
   contradictory, ask first. Give complete files with their repo path, not fragments. Keep all
   safety rules (500 ms watchdog, E-STOP latch, tilt and battery limits).
   ```
4. Start each phase in a new chat using the prompts in §8 (Phase 0 first).
   Chat Claude can't run code: paste its files into the repo, run the check, paste errors back.

**Option B — Claude Code in VS Code (recommended for writing code)**
Clone the repo; Claude Code reads `CLAUDE.md` automatically, and the prompts in §8 work as-is. Setup in §7.

## Current status & decisions (2026-10-20)
| Topic | Decision |
|-------|----------|
| Rover controller | ESP32 DevKit V1 #1 ("rover_main") |
| Telemetry link | **ESP-NOW** between rover_main and ESP32 DevKit V1 #2 ("ground_bridge") plugged into the laptop via USB serial |
| Data format | Logical JSON (agreed) on the laptop; compact binary structs on the radio (ESP-NOW frames ≤ 250 B) |
| Env sensor | BME280 being fitted now (verify it isn't a BMP280); DHT11 kept as fallback |
| Video | Future ESP32-CAM, own WiFi AP; not through the bridge |
| Encoders, INA219, LiDAR | Future — software must already support them (fields exist, UI shows "NOT INSTALLED") |
| Mapping / navigation | Back burner. LiDAR is the likely sensor. Keep SCAN message + map stub only |
| Language | Python 3.12 ground station; C++ (Arduino) firmware |

## Contents
1. CLAUDE.md — hard rules, stack, commands
2. Architecture (docs/01)
3. Protocol (docs/02)
4. Dashboard spec (docs/03)
5. Hardware roadmap + pin plan (docs/04)
6. firmware/common/rover_protocol.h
7. VS Code + Claude Code setup (docs/05)
8. Build prompts (docs/06)
9. rover_main progress log & agreed decisions (docs/PROGRESS_ROVER_MAIN.md)

---

'''

PARTS = [
    ("1. CLAUDE.md", "CLAUDE.md", None),
    ("2. Architecture", "docs/01_ARCHITECTURE.md", None),
    ("3. Protocol", "docs/02_TELEMETRY_PROTOCOL.md", None),
    ("4. Dashboard spec", "docs/03_DASHBOARD_SPEC.md", None),
    ("5. Hardware roadmap", "docs/04_FUTURE_HARDWARE.md", None),
    ("6. rover_protocol.h", "firmware/common/rover_protocol.h", "cpp"),
    ("7. VS Code setup", "docs/05_VSCODE_SETUP.md", None),
    ("8. Build prompts", "docs/06_CLAUDE_CODE_PROMPTS.md", None),
    ("9. rover_main progress & decisions", "docs/PROGRESS_ROVER_MAIN.md", None),
]


def demote(md: str) -> str:
    """Add one '#' to every heading outside code fences."""
    out, fence = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            fence = not fence
            out.append(line)
        elif not fence and line.startswith("#"):
            out.append("#" + line)
        else:
            out.append(line)
    return "\n".join(out)


def main() -> None:
    chunks = [PREAMBLE.replace("__DATE__", date.today().isoformat())]
    for title, rel, lang in PARTS:
        body = (ROOT / rel).read_text(encoding="utf-8").strip()
        chunks.append(f"\n\n# §{title}  (`{rel}`)\n\n")
        chunks.append(f"```{lang}\n{body}\n```\n" if lang else demote(body) + "\n")
        chunks.append("\n---\n")
    dst = ROOT / "docs" / "TEAM_BRIEF.md"
    dst.write_text("".join(chunks), encoding="utf-8")
    print(f"wrote {dst}")


if __name__ == "__main__":
    main()
