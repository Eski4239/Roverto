// Phase 6 keyboard drive input (docs/03 §3, prompt item 3): W/S/A/D + arrows,
// Shift boost, focus/blur/release -> 0. Computed entirely client-side; sent
// through the same socket.sendCmd({drive:...}) path the joystick-derived
// backend output uses on the wire. The drive math is a pure function so it's
// unit-testable the same way sparkline.js's downsample/yRange are (tests_js/).

/**
 * Tank-drive from a set of currently-held key names.
 * @param {Set<string>} keys - lowercased key names currently held
 * @param {number} speedLimit - 0..1
 * @returns {{l: number, r: number}}
 */
export function driveFromKeys(keys, speedLimit) {
  const fwd = (keys.has("w") || keys.has("arrowup") ? 1 : 0) - (keys.has("s") || keys.has("arrowdown") ? 1 : 0);
  const turn = (keys.has("d") || keys.has("arrowright") ? 1 : 0) - (keys.has("a") || keys.has("arrowleft") ? 1 : 0);
  const boost = keys.has("shift") ? 1 : 0.5;
  const scale = speedLimit * boost;
  const l = clamp(fwd + turn, -1, 1) * scale;
  const r = clamp(fwd - turn, -1, 1) * scale;
  return { l, r };
}

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v));
}

const DRIVE_KEYS = new Set([
  "w", "s", "a", "d",
  "arrowup", "arrowdown", "arrowleft", "arrowright",
  "shift",
]);

const SEND_PERIOD_MS = 1000 / 20; // <= 20 Hz (prompt item 4)

export class KeyboardInput {
  constructor(socket, { isActive } = {}) {
    this.socket = socket;
    this._isActive = isActive || (() => true);
    this._held = new Set();
    // P5: -Infinity, not 0 -- performance.now() is always >=0, so a 0
    // sentinel can make the very first event land inside its own throttle
    // window if it fires unusually early (reproduced directly with
    // synthetic nowMs=0 at construction time).
    this._lastSentAt = -Infinity;
    this._lastSent = null;

    this._onKeyDown = (e) => this._handleKey(e, true);
    this._onKeyUp = (e) => this._handleKey(e, false);
    this._onBlur = () => this._release();
    window.addEventListener("keydown", this._onKeyDown);
    window.addEventListener("keyup", this._onKeyUp);
    window.addEventListener("blur", this._onBlur);

    // P5 fix: _maybeSend's own throttle (<=20Hz) could silently drop a key
    // STATE change (e.g. Shift pressed a few ms after W, landing inside the
    // same throttle window) with nothing ever re-sending it afterwards --
    // _maybeSend was only ever called from key events, not on a timer. A
    // periodic flush guarantees the current held-key state (boost
    // included) reaches the backend within one SEND_PERIOD_MS even if an
    // individual event got throttled away.
    this._tickHandle = setInterval(() => this._maybeSend(false), SEND_PERIOD_MS);
  }

  setSpeedLimit(limit) {
    this._speedLimit = limit;
  }

  /** TAKE CONTROL / input-mode switch must not let previously-held keys keep driving. */
  release() {
    this._release();
  }

  _release() {
    this._held.clear();
    this._maybeSend(true);
  }

  _handleKey(e, down) {
    const key = e.key.toLowerCase();
    if (!DRIVE_KEYS.has(key)) return;
    if (!this._isActive()) {
      this._held.clear();
      return;
    }
    const target = e.target;
    const typing = target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");
    if (typing) return;
    e.preventDefault();
    if (down) {
      this._held.add(key);
    } else {
      this._held.delete(key);
    }
    this._maybeSend(false);
  }

  _maybeSend(force) {
    if (!this._isActive() && this._held.size === 0 && !force) return;
    const now = performance.now();
    if (!force && now - this._lastSentAt < SEND_PERIOD_MS) return;
    this._lastSentAt = now;
    const drive = this._isActive()
      ? driveFromKeys(this._held, this._speedLimit ?? 1.0)
      : { l: 0, r: 0 };
    const key = `${drive.l.toFixed(3)}:${drive.r.toFixed(3)}`;
    if (!force && key === this._lastSent) return;
    this._lastSent = key;
    this.socket.sendCmd({ drive });
  }

  destroy() {
    window.removeEventListener("keydown", this._onKeyDown);
    window.removeEventListener("keyup", this._onKeyUp);
    window.removeEventListener("blur", this._onBlur);
    clearInterval(this._tickHandle);
  }
}
