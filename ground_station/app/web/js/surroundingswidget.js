// Drive preset -- Surroundings card (docs/03b §4): large sonar sweep with
// range rings, filling the card while no camera is fitted. Per the approved
// mockup (docs/design/phase5b_live_presets.dc.html), this is one card that
// swaps -- the camera feed takes the space when fitted, and the sweep moves
// beside it -- not two permanent side-by-side panels.
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";
import { RadarWidget } from "./radarwidget.js";

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
          <div class="radar-slot large" id="surr-radar-slot"></div>
        </div>
        <p class="surroundings-note" id="surr-note">The camera feed takes this space when the ESP32-CAM is fitted; the sweep moves beside it.</p>
      </section>
    `;
    this.radar = new RadarWidget(this.root.querySelector("#surr-radar-slot"), { mini: false });
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
    const distEl = this.root.querySelector("#surr-dist");
    if (distEl) {
      distEl.textContent = field.text;
      distEl.className = `tile-value ${field.cls || thresholdClassFor("sonar_dist_cm", sonar.dist_cm)}`;
    }

    const cameraEl = this.root.querySelector("#surr-camera");
    const radarSlot = this.root.querySelector("#surr-radar-slot");
    const noteEl = this.root.querySelector("#surr-note");
    if (cameraEl && radarSlot) {
      cameraEl.hidden = !cameraPresent;
      radarSlot.classList.toggle("companion", cameraPresent);
      if (cameraPresent && camera.url) {
        cameraEl.innerHTML = `<img src="${camera.url}" alt="Rover camera feed" class="camera-feed">`;
      }
      if (noteEl) noteEl.hidden = cameraPresent;
    }

    this.radar.render(snapshot, nowWallMs);
  }
}
