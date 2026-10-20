// Rover Health -> Motors sub-widget: cmd (pwm) vs rpm bars, L/R.
// docs/06 D-013: pwm_l/pwm_r on the wire peak at ±pwm_max, not ±255 -- bars
// must scale to pwmMax, fetched once from GET /config.
import { renderField } from "./hwstate.js";

const MOTORS = [
  { key: "l", label: "L" },
  { key: "r", label: "R" },
];

export class MotorWidget {
  constructor(root, pwmMax) {
    this.root = root;
    this.pwmMax = pwmMax || 255;
    // No documented max RPM; simulator models rpm ~= pwm * 0.5 (fake_rover.py),
    // so scale the rpm bar off the same pwmMax rather than a separate constant.
    this.rpmMax = this.pwmMax * 0.5;
    this.root.innerHTML = MOTORS.map(
      (m) => `
        <div class="motor-row">
          <span class="k">${m.label}</span>
          <div class="motor-bar">
            <span class="motor-bar-fill cmd" id="motor-${m.key}-cmd-fill"></span>
          </div>
          <span class="v" id="motor-${m.key}-cmd-value"></span>
          <div class="motor-bar">
            <span class="motor-bar-fill rpm" id="motor-${m.key}-rpm-fill"></span>
          </div>
          <span class="v" id="motor-${m.key}-rpm-value"></span>
        </div>
      `,
    ).join("");
  }

  render(snapshot) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const encodersPresent = hello ? hello.hw.encoders.present : undefined;

    for (const m of MOTORS) {
      const pwm = telem ? telem.mot[`pwm_${m.key}`] : undefined;
      const rpm = telem ? telem.mot[`rpm_${m.key}`] : undefined;

      const cmdField = renderField({
        present: true,
        value: pwm,
        linkLost,
        format: (v) => `${v}`,
      });
      this._setFill(`motor-${m.key}-cmd-fill`, pwm, this.pwmMax);
      this._setText(`motor-${m.key}-cmd-value`, cmdField.text, cmdField.cls);

      const rpmField = renderField({
        present: encodersPresent,
        value: rpm,
        linkLost,
        format: (v) => `${v.toFixed(0)}`,
      });
      this._setFill(`motor-${m.key}-rpm-fill`, rpm, encodersPresent ? this.rpmMax : null);
      this._setText(`motor-${m.key}-rpm-value`, rpmField.text, rpmField.cls);
    }
  }

  _setFill(id, value, scale) {
    const el = document.getElementById(id);
    if (!el) return;
    if (value == null || scale == null) {
      el.style.width = "0%";
      return;
    }
    const pct = Math.max(-100, Math.min(100, (value / scale) * 100));
    el.style.width = `${Math.abs(pct) / 2}%`;
    el.style.left = pct >= 0 ? "50%" : `${50 - Math.abs(pct) / 2}%`;
  }

  _setText(id, text, cls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = text;
    el.className = `v ${cls || ""}`;
  }
}
