// Reusable hardware-absent / stale-data rendering rules — docs/03 §2 "Hardware-absent
// behaviour". Pure functions, no DOM coupling, so every panel (this phase's power
// widget, and later Environment/Rover Health/etc.) can share them.

/**
 * @param {boolean|undefined} present - hello.hw.<item>.present
 * @returns {boolean} true if the whole card/field should render as NOT INSTALLED
 */
export function isAbsent(present) {
  return present === false || present === undefined;
}

/**
 * @param {boolean} present
 * @param {*} value
 * @returns {"absent"|"nodata"|"ok"}
 */
export function fieldStatus(present, value) {
  if (isAbsent(present)) return "absent";
  if (value === null || value === undefined) return "nodata";
  return "ok";
}

/**
 * Format a value per docs/03 rules, honoring link-lost freezing.
 * @param {object} opts
 * @param {boolean} opts.present
 * @param {*} opts.value
 * @param {boolean} opts.linkLost
 * @param {(v:*)=>string} [opts.format] - formatter for the "ok" case
 * @returns {{text:string, cls:string}}
 */
export function renderField({ present, value, linkLost, format }) {
  const status = fieldStatus(present, value);
  if (status === "absent") {
    return { text: "NOT INSTALLED", cls: "hw-absent" };
  }
  if (status === "nodata") {
    return { text: "—", cls: "hw-stale" };
  }
  const text = format ? format(value) : String(value);
  return { text, cls: linkLost ? "hw-stale" : "" };
}

/** Age string for a frozen value when link is LOST, e.g. "12 s ago". */
export function ageText(lastGoodWallMs, nowWallMs) {
  if (lastGoodWallMs === null || lastGoodWallMs === undefined) return "";
  const ageS = Math.max(0, Math.round((nowWallMs - lastGoodWallMs) / 1000));
  return `${ageS} s ago`;
}

/** Three-band threshold coloring: green/amber/red. */
export function thresholdClass(value, { greenAbove, redBelow, greenBelow, redAbove }) {
  if (value === null || value === undefined) return "";
  if (greenAbove !== undefined || redBelow !== undefined) {
    if (redBelow !== undefined && value < redBelow) return "value-red";
    if (greenAbove !== undefined && value > greenAbove) return "value-green";
    return "value-amber";
  }
  if (greenBelow !== undefined || redAbove !== undefined) {
    if (redAbove !== undefined && value > redAbove) return "value-red";
    if (greenBelow !== undefined && value < greenBelow) return "value-green";
    return "value-amber";
  }
  return "";
}
