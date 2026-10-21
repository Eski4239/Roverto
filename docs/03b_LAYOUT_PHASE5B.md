# 03b — Phase 5b: layout & readability spec

Supersedes the layout in docs/03 §1. Panel *behaviour* (thresholds, hardware-absent rules, LOST
rules, safety) in docs/03 §2–5 still applies.

Reference mockups (approved 2026-10-21): `docs/design/phase5b_live_presets.dc.html` and
`docs/design/phase5b_link_lost.dc.html`. They are design files in a custom format (`<x-dc>`,
`{{holes}}`, `<sc-for>`); read them for structure, colours, spacing and copy — do NOT copy the
format, rebuild in the existing plain HTML/CSS/JS of `ground_station/app/web/`.

## 1. Hard requirements
1. **No inner scrollbars.** At 1366×768 (and wider) every preset fits without any panel scrolling.
   Only the whole page may scroll, and only below 1366×768.
2. **Space follows hardware.** Camera and Map render as slim 38 px dashed strips while
   `hw.camera.present == false` / mapping not built ("Camera · not installed — grows into a panel
   when fitted"; "Map · not built yet (mapping on hold) — sweep shown in Sonar"). When camera is
   present it becomes a full panel (Drive preset: main area; other presets: a medium card).
3. **Readable numbers.** Values in JetBrains Mono (fallback ui-monospace), `font-variant-numeric:
   tabular-nums`, 28 px in tiles (40 px in Science), unit 14–16 px muted, label 11 px uppercase
   letter-spaced muted. One status dot per value (green/amber/red from config.toml thresholds;
   grey when stale). Fonts vendored locally (offline!) — no Google Fonts link at runtime.
4. **Presets** in the top bar as a segmented control: **Drive · Science · Systems** (default
   Systems). Choice remembered in localStorage (wrapped in try/catch). Keyboard: 1/2/3 switch preset
   only when focus isn't in an input.
5. **Expandable value cards.** Every value tile has an expand button (≥32 px, aria-label). Expanded
   = full-width card at top of the main area: 220 px chart with y-axis labels, time axis −5:00 …
   now, 1 min / 5 min toggle, session min/max/mean, collapse button. One expanded at a time.
6. **Control column** always on the right (280–340 px), stacks under the main area on narrow
   screens. Phase 5b builds the layout and the IN CONTROL / VIEW ONLY badge + TAKE CONTROL button
   (already backed by the backend); the drive pad, speed limit, mode, servo and buzzer are drawn but
   disabled with title "Phase 6" until Phase 6 wires them.
7. **E-STOP** button top-right: outlined red with a "SPACE" key hint; active (rover reports
   `state.estop`) = solid flashing red. The E-STOP / link banners go in a full-width bar **below** the
   top bar — never over top-bar content. **Setting** E-STOP bypasses the controller/viewer split
   entirely: any connected tab's E-STOP request is always honored (docs/02 §6.9), and SPACE always
   sends it regardless of which element has focus. **Clearing** it does not: `estop_reset` is honored
   only from the tab currently IN CONTROL — a viewer's reset request is silently ignored, so a
   non-controlling tab can always stop the rover but can never be the one to say it's safe to move
   again (F20).

## 2. Colours (dark theme, all text ≥ 4.5:1)
| Token | Hex | Use |
|-------|-----|-----|
| bg | #0E1116 | page |
| panel | #161B22 | cards, top bar |
| border | #262C36 | card borders |
| border-strong | #30363D | controls |
| text | #E6EDF3 | values |
| text-2 | #C9D1D9 | secondary text |
| muted | #8B949E | labels, units |
| stale | #6E7681 | greyed values (≥ 4.5:1 on panel? use for 28 px+ only; small stale text uses muted) |
| accent | #58A6FF | lines, selection |
| ok | #3FB950 | good |
| warn | #D29922 | warning |
| bad | #F85149 | error, E-STOP |

## 3. Top bar (left → right, wraps on narrow screens)
Link pill (LINK OK green / STALE amber / LOST · Ns red / NO BRIDGE red) · PORT · RSSI ↑/↓ · RTT ·
LOSS · MISSION T+ · MODE · BATTERY (V · % + 64 px bar) · spacer · preset switch · VIEW ONLY badge
(viewers only) · REC dot · E-STOP. RTT and LOSS show "—" when link is not OK.

## 4. Presets
**Systems (default):** strips row · 4 power tiles (V, I, W, SoC with "est. min left" when I known) ·
row of 3 cards: Motors (applied PWM bars centred on 0, scale ±pwm_max, rpm), Attitude (horizon +
compass + roll/pitch/yaw + tilt cut), Link (loss 10 s, RTT, rx Hz, RSSI rover, RSSI bridge, bridge
send fails) · row of 4 compact sys tiles (heap, loop Hz, uptime, chip temp "(info)" uncoloured).

**Science:** strips · 3-column grid of large env tiles (temp, hum, press, alt, lux) with 76 px
trend + "−5 min … now" axis, plus a Sonar card (front distance + mini sweep).

**Drive:** large Surroundings card (sonar sweep, range rings 0.66/1.33/2 m, rover marker; becomes
the camera feed when fitted, sweep moves beside it) · right stack: Motors, Attitude.

Event log (all presets): bottom, max 3 rows visible + All/Warn/Error filter chips, newest first.

## 5. LOST / NO_BRIDGE appearance
Link pill red with seconds since last telem; amber banner below top bar: "No telemetry for N s. The
bridge is connected but the rover is silent. E-STOP state unknown; the rover's watchdog stops the
motors after 0.5 s without commands." (NO_BRIDGE: "Ground bridge not connected" + port picker.)
Every value → stale colour, status dot grey, "N s ago" under it; charts show a shaded "lost" band
from the last sample to now; RTT/LOSS "—".

## 6. Acceptance checks
- At 1366×768: no element with a scrollbar other than the page; check all three presets, with and
  without `--ina219 --encoders`, and in LOST.
- Values readable from 2 m (28 px+), no layout jump when digits change (tabular nums).
- Presets switch instantly, survive page refresh.
- Expand/collapse works for every tile; chart shows lost band during `--rover-silent-after`.
- Viewer tab: VIEW ONLY badge, controls disabled, E-STOP works.
- Console: no errors (favicon present).
