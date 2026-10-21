// Single source of threshold bands for status-dot coloring, backed by
// config.toml's [thresholds.*] table (fetched once via GET /config) instead
// of the per-widget hardcoded constants this replaces (topbar.js,
// attitudewidget.js, sonarwidget.js each had their own copy of the same
// numbers before Phase 5b).
import { thresholdClass } from "./hwstate.js";

let _table = {};

/**
 * Normalize config.toml's [thresholds.<field>] snake_case keys to the
 * camelCase shape hwstate.js's thresholdClass() expects.
 * @param {object} raw - config.thresholds from GET /config
 */
export function setThresholds(raw) {
  _table = {};
  for (const [field, band] of Object.entries(raw || {})) {
    _table[field] = {
      greenAbove: band.green_above,
      redBelow: band.red_below,
      greenBelow: band.green_below,
      redAbove: band.red_above,
    };
  }
}

/**
 * @param {string} fieldKey - as named in config.toml (e.g. "vbat_v")
 * @param {number|null|undefined} value
 * @returns {string} "value-green"/"value-amber"/"value-red", or "" if the
 *   field has no documented threshold (left uncolored, not guessed).
 */
export function thresholdClassFor(fieldKey, value) {
  const band = _table[fieldKey];
  if (!band) return "";
  return thresholdClass(value, band);
}
