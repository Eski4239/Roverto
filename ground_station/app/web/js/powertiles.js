// Systems preset -- 4 power tiles: V, I, W, SoC (docs/03b §4). No expand
// buttons: none of these fields are in state.CHARTABLE_FIELDS (scope
// decision 1) -- sparklines only, same as the Power sub-panel they replace.
import { renderField } from "./hwstate.js";
import { Sparkline } from "./sparkline.js";
import { thresholdClassFor } from "./thresholds.js";

export class PowerTilesWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <div class="tile-grid power-tiles">
        <div class="value-tile">
          <div class="tile-label">Battery</div>
          <div class="tile-value-row"><span class="status-dot" id="pt-vbat-dot"></span><span class="tile-value" id="pt-vbat"></span><span class="tile-unit">V</span></div>
          <svg class="sparkline" id="pt-vbat-spark"></svg>
        </div>
        <div class="value-tile">
          <div class="tile-label">Current</div>
          <div class="tile-value-row"><span class="status-dot" id="pt-ibat-dot"></span><span class="tile-value" id="pt-ibat"></span><span class="tile-unit">A</span></div>
        </div>
        <div class="value-tile">
          <div class="tile-label">Power</div>
          <div class="tile-value-row"><span class="status-dot" id="pt-pwr-dot"></span><span class="tile-value" id="pt-pwr"></span><span class="tile-unit">W</span></div>
        </div>
        <div class="value-tile">
          <div class="tile-label">SoC</div>
          <div class="tile-value-row"><span class="status-dot" id="pt-soc-dot"></span><span class="tile-value" id="pt-soc"></span><span class="tile-unit">%</span></div>
          <div class="tile-note" id="pt-eta"></div>
          <svg class="sparkline" id="pt-soc-spark"></svg>
        </div>
      </div>
    `;
    this._vbatSpark = new Sparkline(document.getElementById("pt-vbat-spark"));
    this._socSpark = new Sparkline(document.getElementById("pt-soc-spark"));
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const currentPresent = hello ? hello.hw.current.present : undefined;
    const pwr = telem ? telem.pwr : {};

    const vbatCls = linkLost ? "value-stale" : thresholdClassFor("vbat_v", pwr.vbat_v);
    this._tile("pt-vbat", "pt-vbat-dot", renderField({
      present: true, value: pwr.vbat_v, linkLost, format: (v) => v.toFixed(1),
    }), vbatCls);

    this._tile("pt-ibat", "pt-ibat-dot", renderField({
      present: currentPresent, value: pwr.ibat_a, linkLost, format: (v) => v.toFixed(2),
    }), "");

    this._tile("pt-pwr", "pt-pwr-dot", renderField({
      present: currentPresent, value: pwr.p_w, linkLost, format: (v) => v.toFixed(1),
    }), "");

    // soc_pct colors from the vbat_v threshold state (confirmed decision):
    // same underlying battery condition, not a separate numeric band.
    this._tile("pt-soc", "pt-soc-dot", renderField({
      present: true, value: pwr.soc_pct, linkLost, format: (v) => Math.round(v).toString(),
    }), vbatCls);

    const etaEl = document.getElementById("pt-eta");
    if (etaEl) {
      if (currentPresent && pwr.ibat_a > 0 && pwr.soc_pct != null) {
        // Rough linear estimate; no capacity model exists yet -- "est." in the label is load-bearing.
        const etaMin = (pwr.soc_pct / 100) * 60; // placeholder until a real capacity figure exists
        etaEl.textContent = `est. ${Math.round(etaMin)} min left`;
      } else {
        etaEl.textContent = "";
      }
    }

    const history = snapshot.history || {};
    this._vbatSpark.render(history.vbat_v, nowWallMs, 1);
    this._socSpark.render(history.soc_pct, nowWallMs, 10);
  }

  _tile(valueId, dotId, field, thresholdCls) {
    const valueEl = document.getElementById(valueId);
    if (valueEl) {
      valueEl.textContent = field.text;
      valueEl.className = `tile-value ${field.cls || thresholdCls}`;
    }
    const dotEl = document.getElementById(dotId);
    if (dotEl) dotEl.className = `status-dot ${field.cls === "hw-stale" ? "" : field.cls || thresholdCls}`;
  }
}
