// Classic ultrasonic-radar display, shared by the Science Sonar mini card
// and the Drive preset Surroundings card. docs/02 §2.3: angle_deg 0..180,
// 0 = front, CCW positive -- drawn as a half-disc with 0 at the left point,
// 180 at the right point, 90 (straight ahead) at the top, matching
// sonargeometry.js's existing convention so both widgets keep agreeing on
// which side is which.
//
// Draws from snapshot.sonar_recent (every sample since the last snapshot,
// docs/03 radar spec), not just the latest telem.sonar ping, so a wedge is
// drawn per real sample and none are skipped between animation frames.
import { sonarAngleToXY } from "./sonargeometry.js";

const MAX_RANGE_CM = 200;
const RANGE_RINGS_CM = [66, 133, 200]; // 0.66 / 1.33 / 2 m
const BIN_DEG = 2; // persistence bin width
const N_BINS = Math.ceil(180 / BIN_DEG);
const FADE_MS = 1500; // ~1.5 sweep periods at the simulator's ~3s full sweep
const MAX_EXTRAPOLATE_MS = 200;
// docs/02 has no telemetry echo of cmd.servo.mode (ground->rover only, never
// reported back) -- Fixed vs Sweep is inferred from the servo's own recent
// motion instead: if it hasn't moved more than this much across the last
// few samples, treat it as fixed and stop animating a sweep line.
const FIXED_MODE_DEG_TOLERANCE = 1.0;
const FIXED_MODE_SAMPLE_WINDOW = 5;

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

export class RadarWidget {
  /**
   * @param {HTMLElement} root
   * @param {{mini?: boolean}} [opts] - mini = Science Sonar card sizing
   */
  constructor(root, opts = {}) {
    this.root = root;
    this.mini = !!opts.mini;
    this.root.innerHTML = `
      <div class="radar-widget${this.mini ? " mini" : ""}">
        <canvas class="radar-canvas"></canvas>
        <div class="radar-status" hidden></div>
      </div>
    `;
    this.canvas = this.root.querySelector(".radar-canvas");
    this.ctx = this.canvas.getContext("2d");
    this.statusEl = this.root.querySelector(".radar-status");

    // Per-2deg-bin latest sample: {t_ms, angle_deg, dist_cm, recvWallMs}.
    this._bins = new Array(N_BINS).fill(null);

    // Sweep tracking, derived from consecutive real samples.
    this._lastSample = null; // {t_ms, angle_deg, recvWallMs}
    this._prevSample = null;
    this._angularSpeedDegPerMs = 0; // signed
    this._recentAngles = []; // last few angle_deg, for fixed-mode inference

    this._present = undefined;
    this._linkLost = false;
    this._lastGoodWallMs = null;

    // Debug-only, read by tests/test_layout_playwright.py to check the
    // sweep is actually animating and old wedges aren't drawn -- not used
    // by any rendering logic itself.
    this._lastDrawnSweepAngleDeg = null;
    this._lastDrawnWedgeAgesMs = [];
    this.root.radarWidget = this;

    this._raf = requestAnimationFrame(this._tick.bind(this));
  }

  /** Read-only debug snapshot for layout tests (docs/03 radar spec):
   * the angle actually drawn for the sweep line on the most recent frame,
   * and the ages (ms) of every wedge actually drawn that frame -- both
   * populated by the real draw path, not recomputed here, so this can't
   * disagree with what's on screen. */
  debugState() {
    return {
      lastDrawnSweepAngleDeg: this._lastDrawnSweepAngleDeg,
      lastDrawnWedgeAgesMs: this._lastDrawnWedgeAgesMs || [],
    };
  }

  destroy() {
    if (this._raf) cancelAnimationFrame(this._raf);
  }

  render(snapshot, nowWallMs) {
    const hello = snapshot.hello;
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    this._linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    this._present = hello ? hello.hw.sonar.present : undefined;

    if (telem && !this._linkLost) this._lastGoodWallMs = nowWallMs;

    const recent = Array.isArray(snapshot.sonar_recent) ? snapshot.sonar_recent : [];
    for (const [tMs, angleDeg, distCm] of recent) {
      if (angleDeg == null) continue;
      this._ingestSample(tMs, angleDeg, distCm, nowWallMs);
    }
  }

  _ingestSample(tMs, angleDeg, distCm, recvWallMs) {
    const a = clamp(angleDeg, 0, 180);
    const bin = Math.min(N_BINS - 1, Math.floor(a / BIN_DEG));
    this._bins[bin] = { t_ms: tMs, angle_deg: a, dist_cm: distCm, recvWallMs };

    this._prevSample = this._lastSample;
    this._lastSample = { t_ms: tMs, angle_deg: a, recvWallMs };
    if (this._prevSample && this._lastSample.t_ms !== this._prevSample.t_ms) {
      const dDeg = this._lastSample.angle_deg - this._prevSample.angle_deg;
      const dMs = this._lastSample.t_ms - this._prevSample.t_ms;
      if (dMs > 0) this._angularSpeedDegPerMs = dDeg / dMs;
    }

    this._recentAngles.push(a);
    if (this._recentAngles.length > FIXED_MODE_SAMPLE_WINDOW) this._recentAngles.shift();
  }

  /** True if the servo hasn't moved across the last few samples -- the only
   * signal available (docs/02 never echoes cmd.servo.mode back on the wire). */
  _isFixedMode() {
    if (this._recentAngles.length < FIXED_MODE_SAMPLE_WINDOW) return false;
    const min = Math.min(...this._recentAngles);
    const max = Math.max(...this._recentAngles);
    return max - min <= FIXED_MODE_DEG_TOLERANCE;
  }

  _currentSweepAngle(nowWallMs) {
    if (!this._lastSample) return null;
    const dtMs = nowWallMs - this._lastSample.recvWallMs;
    if (dtMs > MAX_EXTRAPOLATE_MS) return null;
    let angle = this._lastSample.angle_deg + this._angularSpeedDegPerMs * dtMs;
    // Reverse at the ends, same bounce the real servo does.
    if (angle > 180) angle = 360 - angle;
    if (angle < 0) angle = -angle;
    return clamp(angle, 0, 180);
  }

  _tick() {
    // rAF's own timestamp is ms-since-page-load, not epoch ms -- every
    // sample's recvWallMs is stamped with Date.now() in render(), so this
    // must use the same clock or ages come out wildly wrong (huge negative
    // deltas: wedges never fade, the sweep extrapolates to +-infinity and
    // pins at 0/180).
    this._raf = requestAnimationFrame(this._tick.bind(this));
    this._draw(Date.now());
  }

  _draw(nowWallMs) {
    const canvas = this.canvas;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(1, Math.round(rect.width * dpr));
    const h = Math.max(1, Math.round(rect.height * dpr));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = this.ctx;
    ctx.save();
    ctx.scale(dpr, dpr);
    const W = rect.width, H = rect.height;
    ctx.clearRect(0, 0, W, H);

    const absent = this._present === false || this._present === undefined;
    const lost = this._linkLost;
    const stale = absent || lost;

    const cx = W / 2;
    const cy = H - (this.mini ? 6 : 10);
    const maxR = Math.max(1, Math.min(W / 2 - 4, H - (this.mini ? 10 : 16)));

    this._drawBackground(ctx, cx, cy, maxR, stale);

    if (!absent) {
      this._drawWedges(ctx, cx, cy, maxR, nowWallMs, lost);
      if (!lost) this._drawSweep(ctx, cx, cy, maxR, nowWallMs);
    }

    ctx.restore();

    this._renderStatus(nowWallMs, absent, lost);
  }

  _drawBackground(ctx, cx, cy, maxR, stale) {
    ctx.fillStyle = "#05070a";
    ctx.fillRect(0, 0, cx * 2, cy + 4);

    const ringColor = stale ? "rgba(140,148,158,0.35)" : "rgba(63,185,80,0.35)";
    const textColor = stale ? "rgba(140,148,158,0.6)" : "rgba(63,185,80,0.65)";
    ctx.strokeStyle = ringColor;
    ctx.lineWidth = 1;
    ctx.font = `${this.mini ? 7 : 10}px monospace`;
    ctx.fillStyle = textColor;

    for (const rCm of RANGE_RINGS_CM) {
      const r = maxR * (rCm / MAX_RANGE_CM);
      ctx.beginPath();
      ctx.arc(cx, cy, r, Math.PI, 2 * Math.PI);
      ctx.stroke();
      if (!this.mini) {
        ctx.fillText(`${(rCm / 100).toFixed(2)}m`, cx + r - 18, cy - 2);
      }
    }

    // Angle spokes every 30 degrees, labelled.
    for (let deg = 0; deg <= 180; deg += 30) {
      const rad = ((deg - 180) * Math.PI) / 180;
      const x = cx + maxR * Math.cos(rad);
      const y = cy + maxR * Math.sin(rad);
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(x, y);
      ctx.stroke();
      if (!this.mini) {
        const lx = cx + (maxR + 10) * Math.cos(rad);
        const ly = cy + (maxR + 10) * Math.sin(rad);
        ctx.fillText(`${deg}°`, lx - 8, ly);
      }
    }
  }

  _drawWedges(ctx, cx, cy, maxR, nowWallMs, lost) {
    const binWidthRad = (BIN_DEG * Math.PI) / 180;
    this._lastDrawnWedgeAgesMs = [];
    for (let i = 0; i < N_BINS; i++) {
      const sample = this._bins[i];
      if (!sample) continue;
      const ageMs = nowWallMs - sample.recvWallMs;
      if (ageMs > FADE_MS) continue;
      this._lastDrawnWedgeAgesMs.push(ageMs);
      const alpha = lost ? 0.25 : clamp(1 - ageMs / FADE_MS, 0, 1);

      const angleDeg = sample.angle_deg;
      const angleRad = ((angleDeg - 180) * Math.PI) / 180;
      const a0 = angleRad - binWidthRad / 2;
      const a1 = angleRad + binWidthRad / 2;

      const dist = sample.dist_cm;
      const hasReturn = dist != null;
      const rEcho = hasReturn ? maxR * clamp(dist / MAX_RANGE_CM, 0, 1) : 0;

      const grey = lost ? 140 : null;
      const okColor = grey != null ? `rgba(${grey},${grey},${grey},${alpha * 0.5})` : `rgba(63,185,80,${hasReturn ? alpha : alpha * 0.35})`;
      const badColor = grey != null ? `rgba(${grey},${grey},${grey},${alpha * 0.3})` : `rgba(248,81,73,${alpha})`;

      if (hasReturn) {
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, rEcho, a0, a1);
        ctx.closePath();
        ctx.fillStyle = okColor;
        ctx.fill();

        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, maxR, a0, a1);
        ctx.closePath();
        ctx.fillStyle = "rgba(0,0,0,0)";
        ctx.save();
        ctx.beginPath();
        ctx.arc(cx, cy, maxR, a0, a1);
        ctx.arc(cx, cy, rEcho, a1, a0, true);
        ctx.closePath();
        ctx.fillStyle = badColor;
        ctx.fill();
        ctx.restore();
      } else {
        // No return anywhere in range: all green, dim.
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, maxR, a0, a1);
        ctx.closePath();
        ctx.fillStyle = okColor;
        ctx.fill();
      }
    }
  }

  _drawSweep(ctx, cx, cy, maxR, nowWallMs) {
    const angleDeg = this._isFixedMode()
      ? this._lastSample.angle_deg
      : this._currentSweepAngle(nowWallMs);
    if (angleDeg == null) return;
    this._lastDrawnSweepAngleDeg = angleDeg;

    const { x, y } = sonarAngleToXY(angleDeg, maxR, cx, cy);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.strokeStyle = "#3fb950";
    ctx.lineWidth = this.mini ? 1.5 : 2;
    ctx.shadowColor = "#3fb950";
    ctx.shadowBlur = this.mini ? 3 : 6;
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  _renderStatus(nowWallMs, absent, lost) {
    if (!this.statusEl) return;
    if (absent) {
      this.statusEl.hidden = false;
      this.statusEl.textContent = "NOT INSTALLED";
      return;
    }
    if (lost) {
      const ageS = this._lastGoodWallMs == null
        ? 0
        : Math.max(0, Math.round((nowWallMs - this._lastGoodWallMs) / 1000));
      this.statusEl.hidden = false;
      this.statusEl.textContent = `STALE · ${ageS} s ago`;
      return;
    }
    this.statusEl.hidden = true;
  }
}
