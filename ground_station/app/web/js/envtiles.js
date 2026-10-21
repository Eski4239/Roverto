// Science preset -- 5 large env tiles (docs/03b §4), 76px trend + axis
// labels, each expandable (env fields already have history rings predating
// Phase 5b). Replaces environmentwidget.js's old smaller Rover Health tiles.
import { renderField } from "./hwstate.js";
import { Sparkline } from "./sparkline.js";
import { ExpandableTile } from "./expandable.js";

const FIELDS = [
  { key: "temp_c", label: "Temp", unit: "°C", decimals: 1, minSpan: 2 },
  { key: "hum_pct", label: "Hum", unit: "%", decimals: 0, minSpan: 10 },
  { key: "press_hpa", label: "Press", unit: "hPa", decimals: 0, minSpan: 4 },
  { key: "alt_m", label: "Alt", unit: "m", decimals: 0, minSpan: 2 },
  { key: "lux", label: "Lux", unit: "", decimals: 0, minSpan: 100 },
];

export class EnvTilesWidget {
  constructor(root, expandSlotEl) {
    this.root = root;
    this.root.innerHTML = `
      <div class="tile-grid env-tiles science">
        ${FIELDS.map((f) => `
          <div class="value-tile" id="envtile-${f.key}">
            <button class="expand-btn" aria-label="Expand ${f.label} chart">&#x2922;</button>
            <div class="tile-label">${f.label}</div>
            <div class="tile-value-row"><span class="status-dot" id="envtile-${f.key}-dot"></span><span class="tile-value science" id="envtile-${f.key}-value"></span><span class="tile-unit">${f.unit}</span></div>
            <svg class="sparkline large" id="envtile-${f.key}-spark"></svg>
            <div class="tile-axis"><span>-5 min</span><span>now</span></div>
          </div>
        `).join("")}
      </div>
    `;
    this._sparklines = {};
    this._expandables = {};
    for (const f of FIELDS) {
      this._sparklines[f.key] = new Sparkline(document.getElementById(`envtile-${f.key}-spark`));
      const tile = new ExpandableTile({
        slotEl: expandSlotEl,
        tileKey: f.key,
        label: f.label,
        unit: f.unit ? ` ${f.unit}` : "",
        formatValue: (v) => v.toFixed(f.decimals),
        field: f.key,
      });
      tile.attach(document.getElementById(`envtile-${f.key}`));
      this._expandables[f.key] = tile;
    }
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const envModel = hello ? hello.hw.env.model : null;
    const envPresent = hello ? hello.hw.env.present : undefined;
    const lightPresent = hello ? hello.hw.light.present : undefined;
    const history = snapshot.history || {};

    for (const f of FIELDS) {
      const present = f.key === "lux" ? lightPresent
        : f.key === "hum_pct" ? envPresent && envModel !== "bmp280"
        : f.key === "press_hpa" ? envPresent && envModel !== "dht11"
        : f.key === "alt_m" ? envPresent && envModel !== "dht11"
        : envPresent;

      const value = telem
        ? f.key === "lux" ? telem.light.lux : telem.env[f.key]
        : undefined;

      const field = renderField({
        present,
        value,
        linkLost,
        format: (v) => `${v.toFixed(f.decimals)}`,
      });

      const valueEl = document.getElementById(`envtile-${f.key}-value`);
      if (valueEl) {
        valueEl.textContent = field.text;
        valueEl.className = `tile-value science ${field.cls || ""}`;
      }
      const dotEl = document.getElementById(`envtile-${f.key}-dot`);
      if (dotEl) dotEl.className = `status-dot ${field.cls === "hw-stale" ? "" : field.cls || ""}`;

      this._sparklines[f.key].render(history[f.key], nowWallMs, f.minSpan);
      this._expandables[f.key].renderIfOpen(snapshot);
    }
  }
}
