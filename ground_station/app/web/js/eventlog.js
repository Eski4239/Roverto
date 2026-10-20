// Minimal Event Log widget -- newest 10 events from snapshot.recent_events
// (time, level, code, msg). Wired now so GS-2/ROVER_RESTART is visible
// during testing; the full filterable panel stays Phase 7 (docs/06).

function fmtT(tMs) {
  const totalS = Math.floor(tMs / 1000);
  const hh = String(Math.floor(totalS / 3600)).padStart(2, "0");
  const mm = String(Math.floor((totalS % 3600) / 60)).padStart(2, "0");
  const ss = String(totalS % 60).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export class EventLogWidget {
  constructor(root) {
    this.root = root;
  }

  render(snapshot) {
    const events = snapshot.recent_events || [];
    if (events.length === 0) {
      this.root.innerHTML = `<div class="placeholder-body">events will appear here</div>`;
      return;
    }
    const rows = events.map((e) => {
      const cls = e.level === "error" ? "ev-error" : e.level === "warn" ? "ev-warn" : "ev-info";
      return `<div class="ev-row ${cls}"><span class="ev-t">${fmtT(e.t)}</span><span class="ev-code">${e.code}</span><span class="ev-msg">${e.msg}</span></div>`;
    }).join("");
    this.root.innerHTML = `<div class="event-log">${rows}</div>`;
  }
}
