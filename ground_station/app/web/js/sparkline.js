// Inline-SVG sparkline, hand-rolled (no vendored charting lib needed for a
// single polyline) -- used by Environment's fields and Power's V/SoC trend.
// Points arrive at 10 Hz over up to a 5-min window (docs/03 §2); we
// downsample to 1 point/sec (bucket average) before drawing so the line
// reads as a trend, not a solid block, and redraws are throttled to <=2 Hz.

const REDRAW_PERIOD_MS = 500; // 2 Hz
const BUCKET_MS = 1000; // 1 Hz downsample

/**
 * Bucket (t_ms, value) pairs into 1-per-bucket averages.
 * @param {Array<[number, number]>} points - [(t_ms, value), ...], assumed sorted by t
 * @param {number} bucketMs
 * @returns {Array<[number, number]>}
 */
export function downsample(points, bucketMs = BUCKET_MS) {
  if (!points || points.length === 0) return [];
  const buckets = new Map(); // bucketStart -> {sum, count}
  for (const [t, v] of points) {
    const bucketStart = Math.floor(t / bucketMs) * bucketMs;
    const entry = buckets.get(bucketStart);
    if (entry) {
      entry.sum += v;
      entry.count += 1;
    } else {
      buckets.set(bucketStart, { sum: v, count: 1 });
    }
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([t, { sum, count }]) => [t, sum / count]);
}

/**
 * Compute a [min, max] y-range that is at least minSpan wide, centered on
 * the data when the natural span is narrower than minSpan (so a flat or
 * near-flat signal doesn't look like meaningless full-height noise).
 * @param {number[]} values
 * @param {number} minSpan
 * @returns {[number, number]}
 */
export function yRange(values, minSpan = 0) {
  const minV = Math.min(...values);
  const maxV = Math.max(...values);
  const span = maxV - minV;
  if (span >= minSpan) return [minV, maxV];
  const mid = (minV + maxV) / 2;
  return [mid - minSpan / 2, mid + minSpan / 2];
}

export class Sparkline {
  constructor(svgEl) {
    this.svg = svgEl;
    this._lastDrawWallMs = -Infinity;
  }

  /**
   * @param {Array<[number, number]>} points - [(t_ms, value), ...]
   * @param {number} nowWallMs
   * @param {number} [minSpan] - minimum y-axis span, centered when data is flatter than this
   */
  render(points, nowWallMs, minSpan = 0) {
    if (nowWallMs - this._lastDrawWallMs < REDRAW_PERIOD_MS) return;
    this._lastDrawWallMs = nowWallMs;

    const ds = downsample(points);
    if (ds.length < 2) {
      this.svg.innerHTML = "";
      return;
    }
    const w = 100;
    const h = 24;
    const [minV, maxV] = yRange(ds.map((p) => p[1]), minSpan);
    const span = maxV - minV || 1;
    const tMin = ds[0][0];
    const tMax = ds[ds.length - 1][0];
    const tSpan = tMax - tMin || 1;

    const coords = ds.map(([t, v]) => {
      const x = ((t - tMin) / tSpan) * w;
      const y = h - ((v - minV) / span) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    this.svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    this.svg.innerHTML = `<polyline points="${coords.join(" ")}" fill="none" stroke="currentColor" stroke-width="1.5" />`;
  }
}
