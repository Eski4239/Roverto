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
  constructor(root, filterGroupEl) {
    this.root = root;
    this._filter = "all";
    if (filterGroupEl) {
      for (const btn of filterGroupEl.querySelectorAll("button")) {
        btn.addEventListener("click", () => {
          this._filter = btn.dataset.filter;
          for (const b of filterGroupEl.querySelectorAll("button")) b.classList.toggle("active", b === btn);
          this._lastSnapshot && this.render(this._lastSnapshot);
        });
      }
    }
  }

  render(snapshot) {
    this._lastSnapshot = snapshot;
    const events = (snapshot.recent_events || []).filter(
      (e) => this._filter === "all" || e.level === this._filter,
    );
    if (events.length === 0) {
      this.root.innerHTML = `<div class="placeholder-body">events will appear here</div>`;
      return;
    }
    const rows = events.slice(0, 3).map((e) => {
      const cls = e.level === "error" ? "ev-error" : e.level === "warn" ? "ev-warn" : "ev-info";
      return `<div class="ev-row ${cls}"><span class="ev-t">${fmtT(e.t)}</span><span class="ev-code">${e.code}</span><span class="ev-msg">${e.msg}</span></div>`;
    }).join("");
    this.root.innerHTML = `<div class="event-log">${rows}</div>`;
  }
}
