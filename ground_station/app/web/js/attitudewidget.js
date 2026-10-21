// Attitude card (docs/03b §4): roll/pitch artificial-horizon circle + yaw
// compass needle. docs/02: yaw drifts (no magnetometer) -- shown as-is, no
// absolute-heading claim. Mounted once per preset that shows it.
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";
import { ExpandableTile } from "./expandable.js";

const REDRAW_PERIOD_MS = 500; // 2 Hz

export class AttitudeWidget {
  constructor(root, expandSlotEl) {
    this.root = root;
    this.root.innerHTML = `
      <section class="card attitude-card">
        <h2>ATTITUDE</h2>
        <div class="attitude-widget">
          <svg class="attitude-horizon" viewBox="0 0 60 60">
            <circle cx="30" cy="30" r="28" fill="none" stroke="var(--border)" />
            <g id="attitude-horizon-g">
              <line x1="2" y1="30" x2="58" y2="30" stroke="currentColor" stroke-width="2" />
            </g>
          </svg>
          <svg class="attitude-compass" viewBox="0 0 60 60">
            <circle cx="30" cy="30" r="28" fill="none" stroke="var(--border)" />
            <g id="attitude-compass-g">
              <line x1="30" y1="30" x2="30" y2="6" stroke="currentColor" stroke-width="2" />
            </g>
          </svg>
          <div class="attitude-readout">
            <div class="row" id="attitude-roll-row"><button class="expand-btn" aria-label="Expand roll chart">&#x2922;</button><span class="k">Roll</span><span class="v" id="attitude-roll"></span></div>
            <div class="row" id="attitude-pitch-row"><button class="expand-btn" aria-label="Expand pitch chart">&#x2922;</button><span class="k">Pitch</span><span class="v" id="attitude-pitch"></span></div>
            <div class="row"><span class="k">Yaw</span><span class="v" id="attitude-yaw"></span></div>
          </div>
        </div>
      </section>
    `;
    this._lastDrawWallMs = -Infinity;
    this._expandables = {};
    if (expandSlotEl) {
      this._expandables.roll = new ExpandableTile({
        slotEl: expandSlotEl, tileKey: "roll_deg", label: "Roll", unit: "°",
        formatValue: (v) => v.toFixed(1), field: "imu.roll_deg",
      });
      this._expandables.roll.attach(document.getElementById("attitude-roll-row"));
      this._expandables.pitch = new ExpandableTile({
        slotEl: expandSlotEl, tileKey: "pitch_deg", label: "Pitch", unit: "°",
        formatValue: (v) => v.toFixed(1), field: "imu.pitch_deg",
      });
      this._expandables.pitch.attach(document.getElementById("attitude-pitch-row"));
    }
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const imuPresent = hello ? hello.hw.imu.present : undefined;
    const imu = telem ? telem.imu : {};

    this._renderField("attitude-roll", imuPresent, imu.roll_deg, linkLost, "roll_pitch_deg");
    this._renderField("attitude-pitch", imuPresent, imu.pitch_deg, linkLost, "roll_pitch_deg");
    this._renderField("attitude-yaw", imuPresent, imu.yaw_deg, linkLost, null);

    if (this._expandables.roll) this._expandables.roll.renderIfOpen(snapshot);
    if (this._expandables.pitch) this._expandables.pitch.renderIfOpen(snapshot);

    if (nowWallMs - this._lastDrawWallMs < REDRAW_PERIOD_MS) return;
    this._lastDrawWallMs = nowWallMs;

    const horizonG = document.getElementById("attitude-horizon-g");
    if (horizonG) {
      if (imu.roll_deg == null || imu.pitch_deg == null || !imuPresent) {
        horizonG.setAttribute("transform", "");
      } else {
        const pitchOffsetPx = Math.max(-20, Math.min(20, imu.pitch_deg * 0.5));
        horizonG.setAttribute("transform", `translate(0, ${pitchOffsetPx}) rotate(${-imu.roll_deg}, 30, 30)`);
      }
    }
    const compassG = document.getElementById("attitude-compass-g");
    if (compassG) {
      compassG.setAttribute(
        "transform",
        imu.yaw_deg != null && imuPresent ? `rotate(${imu.yaw_deg}, 30, 30)` : "",
      );
    }
  }

  _renderField(id, present, value, linkLost, thresholdKey) {
    const field = renderField({
      present,
      value,
      linkLost,
      format: (v) => `${v.toFixed(1)}°`,
    });
    const el = document.getElementById(id);
    if (el) {
      el.textContent = field.text;
      el.className = `v ${field.cls || (thresholdKey ? thresholdClassFor(thresholdKey, value) : "")}`;
    }
    return field;
  }
}
