// Drive/Science/Systems preset switching (docs/03b §1, §4). Each preset's
// cards are separate, always-rendering widget instances (dashboard.js) --
// switching is a pure visibility toggle here, never a DOM rebuild, so it is
// instant and correct immediately after a page refresh.

const KEY_TO_PRESET = { 1: "drive", 2: "science", 3: "systems" };

export class PresetController {
  /**
   * @param {object} opts
   * @param {Record<string, HTMLElement>} opts.panelsByName - {drive, science, systems}
   * @param {NodeListOf<HTMLElement>} opts.switchEls - top-bar buttons, each with data-preset
   * @param {string} [opts.storageKey]
   * @param {string} [opts.defaultPreset]
   */
  constructor({ panelsByName, switchEls, storageKey = "gs.preset", defaultPreset = "systems" }) {
    this._panels = panelsByName;
    this._switchEls = switchEls;
    this._storageKey = storageKey;
    this._default = defaultPreset;
    this._listeners = [];
    this._current = this._loadPersisted() || this._default;

    for (const el of this._switchEls) {
      el.addEventListener("click", () => this.switchTo(el.dataset.preset));
    }
    window.addEventListener("keydown", (e) => this._onKeydown(e));

    this._apply();
  }

  current() {
    return this._current;
  }

  switchTo(name) {
    if (!this._panels[name] || name === this._current) return;
    this._current = name;
    this._apply();
    this._savePersisted(name);
    for (const cb of this._listeners) cb(name);
  }

  onChange(cb) {
    this._listeners.push(cb);
  }

  _apply() {
    for (const [name, panel] of Object.entries(this._panels)) {
      panel.hidden = name !== this._current;
    }
    for (const el of this._switchEls) {
      el.classList.toggle("active", el.dataset.preset === this._current);
    }
  }

  _onKeydown(e) {
    const target = document.activeElement;
    const isInput = target && ["INPUT", "SELECT", "TEXTAREA"].includes(target.tagName);
    if (isInput) return;
    const preset = KEY_TO_PRESET[e.key];
    if (preset) this.switchTo(preset);
  }

  _loadPersisted() {
    try {
      return localStorage.getItem(this._storageKey);
    } catch {
      return null;
    }
  }

  _savePersisted(name) {
    try {
      localStorage.setItem(this._storageKey, name);
    } catch {
      // storage blocked (private window, etc.) -- preset just won't persist
    }
  }
}
