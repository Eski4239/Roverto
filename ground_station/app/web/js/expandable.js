// Expand-button -> full-width chart card mechanic (docs/03b §1.5). Only
// fields in state.CHARTABLE_FIELDS get one -- see Phase 5b scope decision 1.
import { fetchHistory } from "./history.js";
import { Chart } from "./chart.js";

const POLL_PERIOD_MS = 1000; // 1 Hz while open, per scope decision 1
const DEFAULT_WINDOW_SEC = 300;

let _openTile = null; // module-level "one open at a time" registry

export class ExpandableTile {
  /**
   * @param {object} opts
   * @param {HTMLElement} opts.slotEl - shared #expand-slot container
   * @param {string} opts.tileKey - unique id, e.g. "vbat_v"
   * @param {string} opts.label
   * @param {string} opts.unit
   * @param {(v:number)=>string} opts.formatValue
   * @param {string} opts.field - a CHARTABLE_FIELDS name for GET /api/history
   */
  constructor({ slotEl, tileKey, label, unit, formatValue, field }) {
    this.slotEl = slotEl;
    this.tileKey = tileKey;
    this.label = label;
    this.unit = unit;
    this.formatValue = formatValue || ((v) => String(v));
    this.field = field;
    this._open = false;
    this._pollTimer = null;
    this._cardEl = null;
    this._chart = null;
    this._windowSec = DEFAULT_WINDOW_SEC;
    this._lastSampleT = null;
  }

  /** Wires this tile's .expand-btn; call once after the owning widget builds tileEl's HTML. */
  attach(tileEl) {
    const btn = tileEl.querySelector(".expand-btn");
    if (!btn) return;
    btn.addEventListener("click", () => (this._open ? this.collapse() : this.open()));
  }

  open() {
    if (_openTile && _openTile !== this) _openTile.collapse();
    _openTile = this;
    this._open = true;
    this._buildCard();
    this._poll();
    this._pollTimer = setInterval(() => this._poll(), POLL_PERIOD_MS);
  }

  collapse() {
    this._open = false;
    if (_openTile === this) _openTile = null;
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = null;
    this.slotEl.innerHTML = "";
    this._cardEl = null;
    this._chart = null;
  }

  /** No-op if not open; called every tick from the owning widget's render(). */
  renderIfOpen(snapshot) {
    if (!this._open) return;
    const link = snapshot.link || {};
    const linkLost = link.state === "LOST" || link.state === "NO_BRIDGE";
    this._minmax = snapshot.session_minmax ? snapshot.session_minmax[this.field] : null;
    this._renderChart(linkLost);
  }

  _buildCard() {
    this.slotEl.innerHTML = `
      <section class="expand-card">
        <div class="expand-card-header">
          <h2>${this.label} · EXPANDED</h2>
          <div class="expand-card-toggles">
            <button class="win-btn" data-win="60">1 min</button>
            <button class="win-btn active" data-win="300">5 min</button>
            <button class="collapse-btn" aria-label="Collapse chart">×</button>
          </div>
        </div>
        <svg class="chart"></svg>
        <div class="expand-card-stats"></div>
      </section>
    `;
    this._cardEl = this.slotEl.firstElementChild;
    this._chart = new Chart(this._cardEl.querySelector(".chart"));
    this._cardEl.querySelector(".collapse-btn").addEventListener("click", () => this.collapse());
    for (const btn of this._cardEl.querySelectorAll(".win-btn")) {
      btn.addEventListener("click", () => {
        this._windowSec = Number(btn.dataset.win);
        for (const b of this._cardEl.querySelectorAll(".win-btn")) b.classList.toggle("active", b === btn);
        this._chart.setWindowSec(this._windowSec);
        this._renderStats();
        if (this._lastSeries) this._chart.render(this._lastSeries, this._lastLinkLost, this._lastSampleT);
      });
    }
  }

  async _poll() {
    const series = await fetchHistory(this.field, DEFAULT_WINDOW_SEC);
    this._lastSeries = series;
    this._lastSampleT = series.t.length ? series.t[series.t.length - 1] : null;
    this._renderStats(series);
  }

  _renderChart(linkLost) {
    this._lastLinkLost = linkLost;
    if (!this._lastSeries || !this._cardEl) return;
    this._chart.render(this._lastSeries, linkLost, this._lastSampleT);
  }

  _renderStats(series) {
    if (!this._cardEl) return;
    const statsEl = this._cardEl.querySelector(".expand-card-stats");
    const s = series || this._lastSeries;
    if (!statsEl || !s || s.v.length === 0) {
      if (statsEl) statsEl.textContent = "";
      this._renderChart(this._lastLinkLost);
      return;
    }
    let min, max, mean;
    if (this._minmax) {
      [min, max, mean] = this._minmax;
    } else {
      min = Math.min(...s.v);
      max = Math.max(...s.v);
      mean = s.v.reduce((a, b) => a + b, 0) / s.v.length;
    }
    statsEl.textContent =
      `min ${this.formatValue(min)}${this.unit}  ·  max ${this.formatValue(max)}${this.unit}  ·  mean ${this.formatValue(mean)}${this.unit}`;
    this._renderChart(this._lastLinkLost);
  }
}
