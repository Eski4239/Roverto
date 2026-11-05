// Science preset -- small Sonar card: front distance + mini classic radar
// (docs/03b §4). docs/02: dist_cm null = "no echo" (nodata, not absent).
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";
import { RadarWidget } from "./radarwidget.js";

export class SonarWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <section class="card sonar-card">
        <h2>SONAR · FRONT</h2>
        <div class="sonar-widget">
          <div class="tile-value" id="sonar-dist"></div>
          <div class="radar-slot" id="sonar-radar-slot"></div>
        </div>
      </section>
    `;
    this.radar = new RadarWidget(this.root.querySelector("#sonar-radar-slot"), { mini: true });
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
    const distEl = this.root.querySelector("#sonar-dist");
    if (distEl) {
      distEl.textContent = field.text;
      distEl.className = `tile-value ${field.cls || thresholdClassFor("sonar_dist_cm", sonar.dist_cm)}`;
    }

    this.radar.render(snapshot, nowWallMs);
  }
}
