import { renderField, ageText, thresholdClass } from "./hwstate.js";

const THRESHOLDS = {
  vbat_v: { greenAbove: 11.1, redBelow: 10.5 },
  rssi_dbm: { greenAbove: -67, redBelow: -80 },
  loss_pct: { greenBelow: 2, redAbove: 10 },
};

export class TopBar {
  constructor(root) {
    this.root = root;
    this.lastVbatWallMs = null;
    this.lastVbatValue = null;
  }

  render(snapshot, nowWallMs) {
    const link = snapshot.link || {};
    const telem = snapshot.telem;
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";

    this._renderLinkDot(link.state);
    this._text("tb-port", link.serial_port || "—");
    this._text("tb-rssi-up", this._fmtRssi(link.rssi_rover_dbm));
    this._text("tb-rssi-down", this._fmtRssi(link.rssi_bridge_dbm));
    this._text("tb-rtt", link.rtt_ms != null ? `${Math.round(link.rtt_ms)} ms` : "—");
    this._lossText("tb-loss", link.loss_pct);

    // Mission clock is backend-owned (GroundState.mission_start_wall_ms, set
    // once at the first TELEM after the backend started) so a page refresh
    // or a rover reboot doesn't reset it -- only restarting the ground
    // station process does.
    this._text("tb-clock", this._missionClock(snapshot.mission_start_wall_ms, nowWallMs));

    this._renderBattery(telem, linkLost, nowWallMs);

    const recDot = document.getElementById("tb-rec-dot");
    if (recDot) recDot.classList.toggle("active", link.state !== "NO_BRIDGE");

    const noBridge = document.getElementById("no-bridge-banner");
    if (noBridge) noBridge.classList.toggle("visible", link.state === "NO_BRIDGE");
  }

  _renderLinkDot(state) {
    const dot = document.getElementById("link-dot");
    const label = document.getElementById("link-state-text");
    if (dot) dot.className = `link-dot ${state || ""}`;
    if (label) label.textContent = state || "—";
  }

  _renderBattery(telem, linkLost, nowWallMs) {
    const vbat = telem ? telem.pwr.vbat_v : undefined;
    const soc = telem ? telem.pwr.soc_pct : undefined;

    if (vbat != null) {
      this.lastVbatValue = vbat;
      this.lastVbatWallMs = nowWallMs;
    }

    const field = renderField({
      present: true,
      value: vbat,
      linkLost,
      format: (v) => `${v.toFixed(1)} V`,
    });
    const vbatEl = document.getElementById("tb-vbat");
    if (vbatEl) {
      vbatEl.textContent = linkLost && this.lastVbatValue != null
        ? `${this.lastVbatValue.toFixed(1)} V (${ageText(this.lastVbatWallMs, nowWallMs)})`
        : field.text;
      vbatEl.className = field.cls || thresholdClass(vbat, THRESHOLDS.vbat_v);
    }

    const fill = document.querySelector("#tb-battery-bar .fill");
    if (fill) {
      const pct = soc != null ? Math.max(0, Math.min(100, soc)) : 0;
      fill.style.width = `${pct}%`;
      fill.style.background = linkLost
        ? "var(--grey)"
        : thresholdClass(vbat, THRESHOLDS.vbat_v) === "value-red"
          ? "var(--red)"
          : thresholdClass(vbat, THRESHOLDS.vbat_v) === "value-amber"
            ? "var(--amber)"
            : "var(--green)";
    }
    this._text("tb-soc", soc != null ? `${Math.round(soc)} %` : "—");
  }

  _fmtRssi(v) {
    if (v == null) return "—";
    const field = renderField({
      present: true,
      value: v,
      linkLost: false,
      format: (x) => `${x} dBm`,
    });
    return field.text;
  }

  _missionClock(missionStartWallMs, nowWallMs) {
    if (missionStartWallMs == null) return "T+00:00:00";
    const elapsedS = Math.max(0, Math.round((nowWallMs - missionStartWallMs) / 1000));
    const hh = String(Math.floor(elapsedS / 3600)).padStart(2, "0");
    const mm = String(Math.floor((elapsedS % 3600) / 60)).padStart(2, "0");
    const ss = String(elapsedS % 60).padStart(2, "0");
    return `T+${hh}:${mm}:${ss}`;
  }

  _text(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  _lossText(id, lossPct) {
    const el = document.getElementById(id);
    if (!el) return;
    // null = not enough samples yet (e.g. just after a restart), not 0%.
    el.textContent = lossPct != null ? `${lossPct.toFixed(1)} %` : "—";
    el.className = lossPct != null ? thresholdClass(lossPct, THRESHOLDS.loss_pct) : "";
  }
}
