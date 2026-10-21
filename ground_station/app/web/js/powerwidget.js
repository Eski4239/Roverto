// Rover Health -> Power sub-widget. Wired live this phase (unlike the rest of Rover
// Health) because it's what the docs/06 Phase 4 check exercises: toggling
// `simulator/fake_rover.py --ina219` must flip hw.current.present without any
// frontend change.
import { renderField } from "./hwstate.js";
import { Sparkline } from "./sparkline.js";

export class PowerWidget {
  constructor(root) {
    this.root = root;
    this._sparkEl = null;
    this._spark = null;
    this._vbatSparkEl = null;
    this._vbatSpark = null;
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const linkLost = snapshot.link && (snapshot.link.state === "LOST" || snapshot.link.state === "NO_BRIDGE");
    const currentPresent = hello ? hello.hw.current.present : undefined;

    const vbat = renderField({
      present: true,
      value: telem ? telem.pwr.vbat_v : undefined,
      linkLost,
      format: (v) => `${v.toFixed(1)} V`,
    });
    const ibat = renderField({
      present: currentPresent,
      value: telem ? telem.pwr.ibat_a : undefined,
      linkLost,
      format: (v) => `${v.toFixed(2)} A`,
    });
    const pwr = renderField({
      present: currentPresent,
      value: telem ? telem.pwr.p_w : undefined,
      linkLost,
      format: (v) => `${v.toFixed(1)} W`,
    });
    const soc = renderField({
      present: true,
      value: telem ? telem.pwr.soc_pct : undefined,
      linkLost,
      format: (v) => `${Math.round(v)} %`,
    });

    this.root.innerHTML = `
      <div class="power-widget">
        <div class="row"><span class="k">V</span><span class="${vbat.cls}">${vbat.text}</span></div>
        <svg class="sparkline" id="power-vbat-spark"></svg>
        <div class="row"><span class="k">I</span><span class="${ibat.cls}">${ibat.text}</span></div>
        <div class="row"><span class="k">W</span><span class="${pwr.cls}">${pwr.text}</span></div>
        <div class="row"><span class="k">SoC</span><span class="${soc.cls}">${soc.text}</span></div>
        <svg class="sparkline" id="power-soc-spark"></svg>
      </div>
    `;
    const vbatSparkEl = document.getElementById("power-vbat-spark");
    if (vbatSparkEl !== this._vbatSparkEl) {
      this._vbatSparkEl = vbatSparkEl;
      this._vbatSpark = new Sparkline(vbatSparkEl);
    }
    const sparkEl = document.getElementById("power-soc-spark");
    if (sparkEl !== this._sparkEl) {
      this._sparkEl = sparkEl;
      this._spark = new Sparkline(sparkEl);
    }
    const history = snapshot.history || {};
    const now = nowWallMs ?? Date.now();
    this._vbatSpark.render(history.vbat_v, now, 1);
    this._spark.render(history.soc_pct, now, 10);
  }
}
