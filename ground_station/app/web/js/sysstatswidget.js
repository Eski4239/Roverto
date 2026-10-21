// Systems preset -- 4 compact sys tiles: heap, loop Hz, uptime, chip_temp
// (docs/03b §4). D-011: chip_temp_c is informational only on classic ESP32
// -- never colour-alarmed. heap/uptime have no config.toml threshold entry
// (confirmed decision) -- left uncolored, not guessed.
import { renderField } from "./hwstate.js";
import { thresholdClassFor } from "./thresholds.js";

function fmtUptime(uptimeS) {
  const hh = String(Math.floor(uptimeS / 3600)).padStart(2, "0");
  const mm = String(Math.floor((uptimeS % 3600) / 60)).padStart(2, "0");
  const ss = String(uptimeS % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export class SysStatsWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <div class="tile-grid sys-tiles">
        <div class="value-tile compact"><div class="tile-label">Heap</div><div class="tile-value-row"><span class="v" id="sys-heap"></span></div></div>
        <div class="value-tile compact"><div class="tile-label">Loop</div><div class="tile-value-row"><span class="status-dot" id="sys-loophz-dot"></span><span class="v" id="sys-loophz"></span></div></div>
        <div class="value-tile compact"><div class="tile-label">Uptime</div><div class="tile-value-row"><span class="v" id="sys-uptime"></span></div></div>
        <div class="value-tile compact"><div class="tile-label">Chip T (info)</div><div class="tile-value-row"><span class="v" id="sys-chiptemp"></span></div></div>
      </div>
    `;
  }

  render(snapshot) {
    const telem = snapshot.telem;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    const sys = telem ? telem.sys : null;

    this._render("sys-heap", renderField({
      present: true, value: sys ? sys.heap_b : undefined, linkLost,
      format: (v) => `${(v / 1024).toFixed(1)} KB`,
    }));

    const loopHz = sys ? sys.loop_hz : undefined;
    const loopField = renderField({
      present: true, value: loopHz, linkLost,
      format: (v) => `${v} Hz`,
    });
    this._render("sys-loophz", loopField, thresholdClassFor("loop_hz", loopHz));
    const loopDot = document.getElementById("sys-loophz-dot");
    if (loopDot) loopDot.className = `status-dot ${loopField.cls === "hw-stale" ? "" : loopField.cls || thresholdClassFor("loop_hz", loopHz)}`;

    this._render("sys-uptime", renderField({
      present: true, value: sys ? sys.uptime_s : undefined, linkLost,
      format: fmtUptime,
    }));
    // chip_temp_c: no thresholdClass call -- D-011, informational only.
    this._render("sys-chiptemp", renderField({
      present: true, value: sys ? sys.chip_temp_c : undefined, linkLost,
      format: (v) => `${v.toFixed(0)} °C`,
    }));
  }

  _render(id, field, thresholdCls) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = field.text;
    el.className = `v ${field.cls || thresholdCls || ""}`;
  }
}
