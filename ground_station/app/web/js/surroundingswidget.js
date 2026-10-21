// Drive preset -- Surroundings card (docs/03b §4): large sonar sweep with
// range rings, filling the card while no camera is fitted. Per the approved
// mockup (docs/design/phase5b_live_presets.dc.html), this is one card that
// swaps -- the camera feed takes the space when fitted, and the sweep moves
// beside it -- not two permanent side-by-side panels.
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";

const MAX_RANGE_CM = 200;
const RANGE_RINGS_CM = [66, 133, 200]; // 0.66m / 1.33m / 2m, per spec
const REDRAW_PERIOD_MS = 500;

export class SurroundingsWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <section class="surroundings-card">
        <div class="surroundings-header">
          <h2>SURROUNDINGS · SONAR SWEEP</h2>
          <span class="tile-value" id="surr-dist"></span>
        </div>
        <div class="surroundings-body">
          <div class="surroundings-camera" id="surr-camera" hidden></div>
          <svg class="sonar-radar large" id="surr-radar" viewBox="0 0 220 112">
            ${RANGE_RINGS_CM.map((r, i) => {
              const frac = r / MAX_RANGE_CM;
              const rx = 95 * frac;
              return `<path d="M${105 - rx} 105 A${rx} ${rx} 0 0 1 ${105 + rx} 105" fill="none" stroke="var(--border-strong)" />`;
            }).join("")}
            <polyline id="surr-sweep" points="" fill="none" stroke="var(--ok)" stroke-width="1.5" />
            <rect x="100" y="100" width="10" height="8" rx="2" fill="var(--accent)" />
          </svg>
        </div>
        <p class="surroundings-note" id="surr-note">The camera feed takes this space when the ESP32-CAM is fitted; the sweep moves beside it.</p>
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
    const camera = hello ? hello.hw.camera : null;
    const cameraPresent = !!(camera && camera.present);

    const field = renderField({
      present: sonarPresent,
      value: sonar.dist_cm,
      linkLost,
      format: (v) => `${v.toFixed(0)} cm ahead`,
    });
    const distEl = document.getElementById("surr-dist");
    if (distEl) {
      distEl.textContent = field.text;
      distEl.className = `tile-value ${field.cls || thresholdClassFor("sonar_dist_cm", sonar.dist_cm)}`;
    }

    const cameraEl = document.getElementById("surr-camera");
    const radarEl = document.getElementById("surr-radar");
    const noteEl = document.getElementById("surr-note");
    if (cameraEl && radarEl) {
      cameraEl.hidden = !cameraPresent;
      radarEl.classList.toggle("companion", cameraPresent);
      if (cameraPresent && camera.url) {
        cameraEl.innerHTML = `<img src="${camera.url}" alt="Rover camera feed" class="camera-feed">`;
      }
      if (noteEl) noteEl.hidden = cameraPresent;
    }

    if (nowWallMs - this._lastDrawWallMs < REDRAW_PERIOD_MS) return;
    this._lastDrawWallMs = nowWallMs;

    const sweep = document.getElementById("surr-sweep");
    if (!sweep) return;
    if (!sonarPresent || sonar.dist_cm == null || sonar.angle_deg == null) {
      sweep.setAttribute("points", "");
      return;
    }
    const range = Math.min(sonar.dist_cm, MAX_RANGE_CM) / MAX_RANGE_CM;
    const angleRad = ((sonar.angle_deg - 90) * Math.PI) / 180;
    const length = 95 * range;
    const px = 105 + length * Math.cos(angleRad);
    const py = 105 + length * Math.sin(angleRad);
    sweep.setAttribute("points", `105,105 ${px.toFixed(1)},${py.toFixed(1)}`);
  }
}
