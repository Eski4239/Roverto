// Inline-SVG sparkline, hand-rolled (no vendored charting lib needed for a
// single polyline) -- used by Environment's 4 fields and Power's SoC trend.
// Redraws are throttled to <=2 Hz per instance regardless of how often
// render() is called (snapshots arrive at 10 Hz per docs/03 §2).

const REDRAW_PERIOD_MS = 500; // 2 Hz

export class Sparkline {
  constructor(svgEl) {
    this.svg = svgEl;
    this._lastDrawWallMs = -Infinity;
  }

  /**
   * @param {Array<[number, number]>} points - [(t_ms, value), ...]
   * @param {number} nowWallMs
   */
  render(points, nowWallMs) {
    if (nowWallMs - this._lastDrawWallMs < REDRAW_PERIOD_MS) return;
    this._lastDrawWallMs = nowWallMs;

    if (!points || points.length < 2) {
      this.svg.innerHTML = "";
      return;
    }
    const w = 100;
    const h = 24;
    const values = points.map((p) => p[1]);
    const minV = Math.min(...values);
    const maxV = Math.max(...values);
    const span = maxV - minV || 1;
    const tMin = points[0][0];
    const tMax = points[points.length - 1][0];
    const tSpan = tMax - tMin || 1;

    const coords = points.map(([t, v]) => {
      const x = ((t - tMin) / tSpan) * w;
      const y = h - ((v - minV) / span) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.svg.innerHTML = `<polyline points="${coords.join(" ")}" fill="none" stroke="currentColor" stroke-width="1.5" />`;
  }
}
