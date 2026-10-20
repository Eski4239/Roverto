// NO_BRIDGE banner: "Plug in ground bridge" + serial port picker, populated via
// GET /ports. Connecting a different port requires restarting the backend with
// --link <port> today (no hot-swap endpoint exists yet), so "Connect" here just
// surfaces the chosen port for the user to re-launch with.

export class PortPicker {
  constructor(selectEl, buttonEl, statusEl) {
    this.selectEl = selectEl;
    this.buttonEl = buttonEl;
    this.statusEl = statusEl;
    this._loaded = false;
    if (this.buttonEl) {
      this.buttonEl.addEventListener("click", () => this._onConnect());
    }
  }

  async ensureLoaded() {
    if (this._loaded) return;
    this._loaded = true;
    try {
      const resp = await fetch("/ports");
      const ports = await resp.json();
      this.selectEl.innerHTML = ports
        .map((p) => `<option value="${p.device}">${p.device} — ${p.description || ""}</option>`)
        .join("") || `<option value="">(no serial ports found)</option>`;
    } catch (err) {
      this.selectEl.innerHTML = `<option value="">(failed to list ports)</option>`;
    }
  }

  _onConnect() {
    const port = this.selectEl.value;
    if (this.statusEl) {
      this.statusEl.textContent = port
        ? `Restart ground station with --link ${port}`
        : "Pick a port first";
    }
  }
}
