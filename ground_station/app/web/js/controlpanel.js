// Right-side CONTROL column (docs/03b §1): IN CONTROL/VIEW ONLY badge + TAKE
// CONTROL button, Joystick/Keyboard input selector, drive pad status, speed
// limit, mode, servo and buzzer (Phase 6, docs/02 §6.12, docs/03 §3).
// Mode enum confirmed from ground_station/app/wire.py MODE: idle/manual/assisted/auto.
import { KeyboardInput } from "./keyboard.js";

const MODES = ["idle", "manual", "assisted", "auto"];

export class ControlPanel {
  constructor(root, socket) {
    this.root = root;
    this.socket = socket;
    this._speedLimit = 1.0;
    this.root.innerHTML = `
      <div class="control-panel">
        <div class="control-badge-row">
          <span class="control-badge" id="control-badge">IN CONTROL</span>
          <button id="take-control-btn" class="take-control-btn">TAKE CONTROL</button>
        </div>
        <div class="control-group">
          <label class="control-label">Input</label>
          <div class="btn-group" id="input-mode-group">
            <button class="mode-btn" data-mode="keyboard">KEYBOARD</button>
            <button class="mode-btn" data-mode="joystick" id="joystick-mode-btn">JOYSTICK</button>
          </div>
        </div>
        <div class="control-group" id="joystick-widget-group">
          <div class="joystick-widget" id="joystick-widget">
            <div class="joy-stick" data-side="left">
              <div class="joy-ring"></div>
              <div class="joy-dot"></div>
              <div class="joy-btn"></div>
            </div>
            <div class="joy-stick" data-side="right">
              <div class="joy-ring"></div>
              <div class="joy-dot"></div>
              <div class="joy-btn"></div>
            </div>
          </div>
          <div class="joy-status" id="joy-status">NO JOYSTICK</div>
          <div class="joy-drive" id="joy-drive">L 0.00 &middot; R 0.00</div>
        </div>
        <div class="control-group">
          <div class="drive-pad">
            <button class="drive-key" id="key-w">W</button>
            <div class="drive-pad-row">
              <button class="drive-key" id="key-a">A</button>
              <button class="drive-key" id="key-s">S</button>
              <button class="drive-key" id="key-d">D</button>
            </div>
          </div>
        </div>
        <div class="control-group">
          <label class="control-label">Speed limit</label>
          <input type="range" min="0" max="100" value="100" id="speed-limit-slider">
        </div>
        <div class="control-group">
          <label class="control-label">Mode</label>
          <div class="btn-group" id="mode-group">
            ${MODES.map((m) => `<button class="mode-btn" data-mode="${m}">${m.toUpperCase()}</button>`).join("")}
          </div>
        </div>
        <div class="control-group">
          <label class="control-label">Servo</label>
          <div class="btn-group" id="servo-group">
            <button class="servo-btn" data-servo-mode="sweep">SWEEP</button>
            <button class="servo-btn" data-servo-mode="fixed">FIXED 90&deg;</button>
          </div>
        </div>
        <div class="control-group">
          <button class="buzzer-btn" id="buzzer-btn">BUZZER</button>
        </div>
      </div>
    `;

    this._inputMode = "keyboard";
    this._inControl = false;

    const takeControlBtn = this.root.querySelector("#take-control-btn");
    if (takeControlBtn) {
      takeControlBtn.addEventListener("click", () => {
        this.socket.takeControl();
        this._keyboard.release();
        this._setInputMode("keyboard", /*send=*/ false); // backend resets to keyboard on take_control too
      });
    }

    this.root.querySelector("#input-mode-group").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-mode]");
      if (!btn || btn.disabled) return;
      this._setInputMode(btn.dataset.mode, /*send=*/ true);
    });

    this.root.querySelector("#mode-group").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-mode]");
      if (!btn || !this._inControl) return;
      this.socket.sendCmd({ mode: btn.dataset.mode });
    });

    this.root.querySelector("#servo-group").addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-servo-mode]");
      if (!btn || !this._inControl) return;
      this.socket.sendCmd({ servo: { mode: btn.dataset.servoMode, angle_deg: 90 } });
    });

    this.root.querySelector("#buzzer-btn").addEventListener("mousedown", () => {
      if (this._inControl) this.socket.sendCmd({ buzzer: true });
    });
    const releaseBuzzer = () => {
      if (this._inControl) this.socket.sendCmd({ buzzer: false });
    };
    this.root.querySelector("#buzzer-btn").addEventListener("mouseup", releaseBuzzer);
    this.root.querySelector("#buzzer-btn").addEventListener("mouseleave", releaseBuzzer);

    const slider = this.root.querySelector("#speed-limit-slider");
    slider.addEventListener("input", () => {
      this._speedLimit = Number(slider.value) / 100;
      this._keyboard.setSpeedLimit(this._speedLimit);
      this.socket.sendCmd({ speed_limit: this._speedLimit });
    });

    this._keyboard = new KeyboardInput(this.socket, {
      isActive: () => this._inControl && this._inputMode === "keyboard",
    });
    this._keyboard.setSpeedLimit(this._speedLimit);
  }

  _setInputMode(mode, send) {
    this._inputMode = mode;
    this._keyboard.release();
    if (send) this.socket.setInputMode(mode);
    this._updateInputModeButtons();
  }

  _updateInputModeButtons() {
    this.root.querySelectorAll("#input-mode-group button[data-mode]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.mode === this._inputMode);
    });
  }

  render(snapshot) {
    const inControl = snapshot.in_control !== false;
    this._inControl = inControl;
    const badge = this.root.querySelector("#control-badge");
    if (badge) {
      badge.textContent = inControl ? "IN CONTROL" : "VIEW ONLY";
      badge.classList.toggle("ok", inControl);
      badge.classList.toggle("warn", !inControl);
    }
    const takeControlBtn = this.root.querySelector("#take-control-btn");
    if (takeControlBtn) {
      takeControlBtn.classList.toggle(
        "visible",
        snapshot.in_control === false && snapshot.controller_present === false,
      );
    }

    const joy = snapshot.joystick;
    const joystickBtn = this.root.querySelector("#joystick-mode-btn");
    const hasJoystick = !!(joy && joy.available);
    if (joystickBtn) {
      joystickBtn.disabled = !hasJoystick;
      joystickBtn.title = hasJoystick ? "" : "no joystick";
    }
    if (inControl && snapshot.input_mode && snapshot.input_mode !== this._inputMode) {
      // Backend is authoritative (e.g. reset to keyboard on TAKE CONTROL) --
      // follow it instead of drifting out of sync with what actually drives.
      this._inputMode = snapshot.input_mode;
    }
    this._updateInputModeButtons();

    this.root.querySelectorAll("#mode-group button[data-mode]").forEach((btn) => {
      btn.disabled = !inControl;
      btn.classList.toggle("active", snapshot.telem && snapshot.telem.state.mode === btn.dataset.mode);
    });
    this.root.querySelectorAll("#servo-group button[data-servo-mode]").forEach((btn) => {
      btn.disabled = !inControl;
    });
    const buzzerBtn = this.root.querySelector("#buzzer-btn");
    buzzerBtn.disabled = !inControl;
    // P6: "pressed" reflects what the backend is actually sending
    // (snapshot.buzzer_sent), not local mousedown/mouseup state -- those
    // can desync (e.g. mouseup firing outside the button, or control
    // changing hands mid-press resets last_ui_cmd.buzzer server-side).
    buzzerBtn.classList.toggle("pressed", !!snapshot.buzzer_sent);
    this.root.querySelector("#speed-limit-slider").disabled = !inControl;
    this.root.querySelectorAll(".drive-key").forEach((btn) => {
      btn.disabled = true; // display-only status keys; keyboard.js listens on window
      btn.classList.toggle("held", this._keyboard._held && this._keyboard._held.has(btn.textContent.toLowerCase()));
    });

    this._renderJoystickWidget(joy, hasJoystick);
  }

  _renderJoystickWidget(joy, hasJoystick) {
    const statusEl = this.root.querySelector("#joy-status");
    const driveEl = this.root.querySelector("#joy-drive");
    if (!hasJoystick) {
      statusEl.textContent = "NO JOYSTICK";
      statusEl.className = "joy-status stale";
      driveEl.textContent = "L 0.00 · R 0.00";
      return;
    }
    const statusLabel = { ok: "OK", not_centred: "NOT CENTRED", lost: "LOST", fault: "FAULT" }[joy.status] || joy.status;
    statusEl.textContent = statusLabel;
    statusEl.className = `joy-status ${joy.status === "ok" ? "ok" : joy.status === "not_centred" ? "warn" : "bad"}`;
    driveEl.textContent = `L ${joy.drive.l.toFixed(2)} · R ${joy.drive.r.toFixed(2)}`;

    for (const side of ["left", "right"]) {
      const stickEl = this.root.querySelector(`.joy-stick[data-side="${side}"]`);
      const dot = stickEl.querySelector(".joy-dot");
      const btn = stickEl.querySelector(".joy-btn");
      const reading = joy[side];
      dot.style.left = `${50 + reading.x * 40}%`;
      dot.style.top = `${50 - reading.y * 40}%`;
      btn.classList.toggle("pressed", !!reading.button);
    }
  }
}
