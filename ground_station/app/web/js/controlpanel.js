// Right-side CONTROL column (docs/03b §1): IN CONTROL/VIEW ONLY badge + TAKE
// CONTROL button (backend already wired -- main.py ws_ui, docs/02 §6.9),
// plus the Phase-6 drive pad/speed/mode/servo/buzzer controls, drawn but
// disabled until Phase 6 wires them to socket.sendCmd().
// Mode enum confirmed from ground_station/app/wire.py MODE: idle/manual/assisted/auto.
const MODES = ["idle", "manual", "assisted", "auto"];

export class ControlPanel {
  constructor(root, socket) {
    this.root = root;
    this.socket = socket;
    this.root.innerHTML = `
      <div class="control-panel">
        <div class="control-badge-row">
          <span class="control-badge" id="control-badge">IN CONTROL</span>
          <button id="take-control-btn" class="take-control-btn">TAKE CONTROL</button>
        </div>
        <div class="control-group" title="Phase 6">
          <div class="drive-pad">
            <button class="drive-key" disabled>W</button>
            <div class="drive-pad-row">
              <button class="drive-key" disabled>A</button>
              <button class="drive-key" disabled>S</button>
              <button class="drive-key" disabled>D</button>
            </div>
          </div>
        </div>
        <div class="control-group" title="Phase 6">
          <label class="control-label">Speed limit</label>
          <input type="range" min="0" max="100" value="100" disabled>
        </div>
        <div class="control-group" title="Phase 6">
          <label class="control-label">Mode</label>
          <div class="btn-group">
            ${MODES.map((m) => `<button class="mode-btn" disabled>${m.toUpperCase()}</button>`).join("")}
          </div>
        </div>
        <div class="control-group" title="Phase 6">
          <label class="control-label">Servo</label>
          <div class="btn-group">
            <button class="servo-btn" disabled>SWEEP</button>
            <button class="servo-btn" disabled>FIXED 90°</button>
          </div>
        </div>
        <div class="control-group" title="Phase 6">
          <button class="buzzer-btn" disabled>BUZZER</button>
        </div>
      </div>
    `;
    const takeControlBtn = this.root.querySelector("#take-control-btn");
    if (takeControlBtn) {
      takeControlBtn.addEventListener("click", () => this.socket.takeControl());
    }
  }

  render(snapshot) {
    const inControl = snapshot.in_control !== false;
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
  }
}
