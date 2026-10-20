// Rover Health -> Sys stats sub-widget: heap, loop Hz, uptime, chip_temp_c.
// D-011: chip_temp_c is informational only on classic ESP32 -- shown
// plainly, never colour-alarmed.
import { renderField } from "./hwstate.js";

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
      <div class="sysstats-widget">
        <div class="row"><span class="k">Heap</span><span class="v" id="sys-heap"></span></div>
        <div class="row"><span class="k">Loop</span><span class="v" id="sys-loophz"></span></div>
        <div class="row"><span class="k">Uptime</span><span class="v" id="sys-uptime"></span></div>
        <div class="row"><span class="k">Chip T</span><span class="v" id="sys-chiptemp"></span></div>
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
    this._render("sys-loophz", renderField({
      present: true, value: sys ? sys.loop_hz : undefined, linkLost,
      format: (v) => `${v} Hz`,
    }));
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

  _render(id, field) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent = field.text;
    el.className = `v ${field.cls || ""}`;
  }
}
