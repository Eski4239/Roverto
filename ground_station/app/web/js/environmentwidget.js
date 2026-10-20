// Environment panel -- docs/03 §1-2: temp/hum/press/lux, each with a 5-min
// sparkline + session min/max. docs/02 §2.1: env.model decides which field
// is absent (bme280 has both, bmp280 lacks humidity, dht11 lacks pressure).
import { renderField } from "./hwstate.js";
import { Sparkline } from "./sparkline.js";

const FIELDS = [
  { key: "temp_c", label: "Temp", unit: "°C", decimals: 1 },
  { key: "hum_pct", label: "Hum", unit: "%", decimals: 0 },
  { key: "press_hpa", label: "Press", unit: "hPa", decimals: 0 },
  { key: "lux", label: "Lux", unit: "", decimals: 0 },
];

export class EnvironmentWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = FIELDS.map(
      (f) => `
        <div class="env-field">
          <div class="env-field-top">
            <span class="k">${f.label}</span>
            <span class="v" id="env-${f.key}-value"></span>
          </div>
          <svg class="sparkline" id="env-${f.key}-spark"></svg>
          <div class="env-field-minmax" id="env-${f.key}-minmax"></div>
        </div>
      `,
    ).join("");
    this._sparklines = {};
    for (const f of FIELDS) {
      this._sparklines[f.key] = new Sparkline(document.getElementById(`env-${f.key}-spark`));
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
    const minmax = snapshot.session_minmax || {};

    for (const f of FIELDS) {
      const present = f.key === "lux" ? lightPresent
        : f.key === "hum_pct" ? envPresent && envModel !== "bmp280"
        : f.key === "press_hpa" ? envPresent && envModel !== "dht11"
        : envPresent;

      const value = telem
        ? f.key === "lux" ? telem.light.lux : telem.env[f.key]
        : undefined;

      const field = renderField({
        present,
        value,
        linkLost,
        format: (v) => `${v.toFixed(f.decimals)}${f.unit ? ` ${f.unit}` : ""}`,
      });

      const valueEl = document.getElementById(`env-${f.key}-value`);
      if (valueEl) {
        valueEl.textContent = field.text;
        valueEl.className = `v ${field.cls}`;
      }

      const bounds = minmax[f.key];
      const minmaxEl = document.getElementById(`env-${f.key}-minmax`);
      if (minmaxEl) {
        minmaxEl.textContent = bounds
          ? `min ${bounds[0].toFixed(f.decimals)} / max ${bounds[1].toFixed(f.decimals)}`
          : "";
      }

      this._sparklines[f.key].render(history[f.key], nowWallMs);
    }
  }
}
