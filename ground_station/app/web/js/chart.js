// 220px expand-card chart (docs/03b §1.5): y-axis labels, -5:00..now x-axis,
// 1 min/5 min window toggle, session min/max/mean, lost-band shading.
// Reuses sparkline.js's downsample/yRange rather than reimplementing them --
// this is just a bigger, axis-labeled version of the same polyline idea.
import { downsample, yRange } from "./sparkline.js";

const CHART_W = 600;
const CHART_H = 220;
const PAD_LEFT = 44;
const PAD_RIGHT = 8;
const PAD_TOP = 10;
const PAD_BOTTOM = 20;

export class Chart {
  constructor(svgEl) {
    this.svg = svgEl;
    this.windowSec = 300; // default 5 min, per plan
  }

  setWindowSec(windowSec) {
    this.windowSec = windowSec;
  }

  /**
   * @param {{t: number[], v: number[]}} series - from history.js, already
   *   sliced to this.windowSec server-side; re-slicing here only applies
   *   when the 1 min toggle narrows a 5-min fetch further client-side.
   * @param {boolean} linkLost
   * @param {number|null} lastSampleT - t_ms of the last real sample, for the
   *   lost-band rect; null if nothing has ever arrived.
   */
  render(series, linkLost, lastSampleT) {
    const points = series.t.map((t, i) => [t, series.v[i]]);
    const cutoffT = points.length ? points[points.length - 1][0] - this.windowSec * 1000 : 0;
    const windowed = points.filter(([t]) => t >= cutoffT);
    const ds = downsample(windowed);

    if (ds.length < 2) {
      this.svg.innerHTML = `<text x="${CHART_W / 2}" y="${CHART_H / 2}" text-anchor="middle" fill="var(--muted)" font-size="12">no data yet</text>`;
      return;
    }

    const [minV, maxV] = yRange(ds.map((p) => p[1]));
    const span = maxV - minV || 1;
    const tMin = ds[0][0];
    const tMax = ds[ds.length - 1][0];
    const tSpan = tMax - tMin || 1;

    const x = (t) => PAD_LEFT + ((t - tMin) / tSpan) * (CHART_W - PAD_LEFT - PAD_RIGHT);
    const y = (v) => CHART_H - PAD_BOTTOM - ((v - minV) / span) * (CHART_H - PAD_TOP - PAD_BOTTOM);

    const coords = ds.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`);

    const gridlines = [0, 0.5, 1].map((f) => {
      const yy = PAD_TOP + f * (CHART_H - PAD_TOP - PAD_BOTTOM);
      const val = maxV - f * span;
      return `
        <line x1="${PAD_LEFT}" y1="${yy}" x2="${CHART_W - PAD_RIGHT}" y2="${yy}" stroke="var(--border)" />
        <text x="${PAD_LEFT - 6}" y="${yy + 3}" text-anchor="end" fill="var(--muted)" font-size="10">${val.toFixed(1)}</text>
      `;
    }).join("");

    const xAxisLabels = `
      <text x="${PAD_LEFT}" y="${CHART_H - 4}" fill="var(--muted)" font-size="10">-${(this.windowSec / 60).toFixed(0)}:00</text>
      <text x="${CHART_W - PAD_RIGHT}" y="${CHART_H - 4}" text-anchor="end" fill="var(--muted)" font-size="10">now</text>
    `;

    let lostBand = "";
    if (linkLost && lastSampleT != null && lastSampleT >= tMin) {
      const bandX = x(lastSampleT);
      lostBand = `<rect x="${bandX.toFixed(1)}" y="${PAD_TOP}" width="${(CHART_W - PAD_RIGHT - bandX).toFixed(1)}" height="${CHART_H - PAD_TOP - PAD_BOTTOM}" fill="var(--bad)" fill-opacity="0.15" />`;
    }

    this.svg.setAttribute("viewBox", `0 0 ${CHART_W} ${CHART_H}`);
    this.svg.innerHTML = `
      ${gridlines}
      ${lostBand}
      <polyline points="${coords.join(" ")}" fill="none" stroke="var(--accent)" stroke-width="1.5" />
      ${xAxisLabels}
    `;
  }
}
