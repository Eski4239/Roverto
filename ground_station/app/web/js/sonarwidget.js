// Science preset -- small Sonar card: front distance + mini sweep
// (docs/03b §4). docs/02: dist_cm null = "no echo" (nodata, not absent).
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";

const MAX_RANGE_CM = 200;
const REDRAW_PERIOD_MS = 500; // 2 Hz

export class SonarWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <section class="card sonar-card">
        <h2>SONAR · FRONT</h2>
        <div class="sonar-widget">
          <div class="tile-value" id="sonar-dist"></div>
          <svg class="sonar-radar" viewBox="0 0 100 55">
            <path d="M 2 52 A 48 48 0 0 1 98 52" fill="none" stroke="var(--border)" />
            <line id="sonar-radar-line" x1="50" y1="52" x2="50" y2="52" stroke="currentColor" stroke-width="2" />
          </svg>
        </div>
      </section>
    `;
    this._lastDrawWallMs = -Infinity;
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const sonarPresent = hello ? hello.hw.sonar.present : undefined;
    const sonar = telem ? telem.sonar : {};

    const field = renderField({
      present: sonarPresent,
      value: sonar.dist_cm,
      linkLost,
      format: (v) => `${v.toFixed(0)} cm`,
    });
    const distEl = document.getElementById("sonar-dist");
    if (distEl) {
      distEl.textContent = field.text;
      distEl.className = `tile-value ${field.cls || thresholdClassFor("sonar_dist_cm", sonar.dist_cm)}`;
    }

    if (nowWallMs - this._lastDrawWallMs < REDRAW_PERIOD_MS) return;
    this._lastDrawWallMs = nowWallMs;

    const line = document.getElementById("sonar-radar-line");
    if (!line) return;
    if (!sonarPresent || sonar.dist_cm == null || sonar.angle_deg == null) {
      line.setAttribute("x2", "50");
      line.setAttribute("y2", "52");
      return;
    }
    const range = Math.min(sonar.dist_cm, MAX_RANGE_CM) / MAX_RANGE_CM;
    const angleRad = ((sonar.angle_deg - 90) * Math.PI) / 180;
    const length = 48 * range;
    line.setAttribute("x2", (50 + length * Math.cos(angleRad)).toFixed(1));
    line.setAttribute("y2", (52 + length * Math.sin(angleRad)).toFixed(1));
  }
}
