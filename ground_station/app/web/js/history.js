// Thin client for GET /api/history (expandable-tile charts only -- the 10
// Hz WS snapshot does not carry this data, state.py §Phase5b).

/**
 * @param {string} field - a state.CHARTABLE_FIELDS name, e.g. "imu.roll_deg"
 * @param {number} windowSec
 * @returns {Promise<{t: number[], v: number[]}>}
 */
export async function fetchHistory(field, windowSec) {
  try {
    const resp = await fetch(`/api/history?field=${encodeURIComponent(field)}&window=${windowSec}`);
    if (!resp.ok) return { t: [], v: [] };
    return await resp.json();
  } catch {
    return { t: [], v: [] };
  }
}
