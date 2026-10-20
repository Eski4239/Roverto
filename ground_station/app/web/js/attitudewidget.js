// Rover Health -> Attitude sub-widget: roll/pitch artificial-horizon circle
// + yaw compass needle. docs/03 thresholds: roll/pitch green<20°, red>30°.
// docs/02: yaw drifts (no magnetometer) -- shown as-is, no absolute-heading claim.
import { renderField, thresholdClass } from "./hwstate.js";

const THRESHOLDS_ROLL_PITCH = { greenBelow: 20, redAbove: 30 };
const REDRAW_PERIOD_MS = 500; // 2 Hz

export class AttitudeWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <div class="attitude-widget">
        <svg class="attitude-horizon" viewBox="0 0 60 60">
          <circle cx="30" cy="30" r="28" fill="none" stroke="var(--panel-border)" />
          <g id="attitude-horizon-g">
            <line x1="2" y1="30" x2="58" y2="30" stroke="currentColor" stroke-width="2" />
          </g>
        </svg>
        <svg class="attitude-compass" viewBox="0 0 60 60">
          <circle cx="30" cy="30" r="28" fill="none" stroke="var(--panel-border)" />
          <g id="attitude-compass-g">
            <line x1="30" y1="30" x2="30" y2="6" stroke="currentColor" stroke-width="2" />
          </g>
        </svg>
        <div class="attitude-readout">
          <div class="row"><span class="k">Roll</span><span class="v" id="attitude-roll"></span></div>
          <div class="row"><span class="k">Pitch</span><span class="v" id="attitude-pitch"></span></div>
          <div class="row"><span class="k">Yaw</span><span class="v" id="attitude-yaw"></span></div>
        </div>
      </div>
    `;
    this._lastDrawWallMs = -Infinity;
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const imuPresent = hello ? hello.hw.imu.present : undefined;
    const imu = telem ? telem.imu : {};

    const roll = this._renderField("attitude-roll", imuPresent, imu.roll_deg, linkLost, THRESHOLDS_ROLL_PITCH);
    const pitch = this._renderField("attitude-pitch", imuPresent, imu.pitch_deg, linkLost, THRESHOLDS_ROLL_PITCH);
    this._renderField("attitude-yaw", imuPresent, imu.yaw_deg, linkLost, null);

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

  _renderField(id, present, value, linkLost, thresholds) {
    const field = renderField({
      present,
      value,
      linkLost,
      format: (v) => `${v.toFixed(1)}°`,
    });
    const el = document.getElementById(id);
    if (el) {
      el.textContent = field.text;
      el.className = `v ${field.cls || (thresholds ? thresholdClass(value, thresholds) : "")}`;
    }
    return field;
  }
}
