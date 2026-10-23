import test from "node:test";
import assert from "node:assert/strict";
import { sonarAngleToXY } from "../ground_station/app/web/js/sonargeometry.js";

// sonarwidget.js's panel: viewBox "0 0 100 55", semicircle from (2,52) to
// (98,52) through the top (50,4), radius 48, centred at (50,52).
const CX = 50, CY = 52, LENGTH = 48;

test("angle 0 maps to the left endpoint, inside the viewBox", () => {
  const { x, y } = sonarAngleToXY(0, LENGTH, CX, CY);
  assert.ok(Math.abs(x - 2) < 0.1, `x=${x}`);
  assert.ok(Math.abs(y - 52) < 0.1, `y=${y}`);
});

test("angle 90 maps to the top apex, inside the viewBox", () => {
  const { x, y } = sonarAngleToXY(90, LENGTH, CX, CY);
  assert.ok(Math.abs(x - 50) < 0.1, `x=${x}`);
  assert.ok(Math.abs(y - 4) < 0.1, `y=${y}`);
});

test("angle 180 maps to the right endpoint, inside the viewBox (P4 regression)", () => {
  const { x, y } = sonarAngleToXY(180, LENGTH, CX, CY);
  assert.ok(Math.abs(x - 98) < 0.1, `x=${x}`);
  assert.ok(Math.abs(y - 52) < 0.1, `y=${y}`);
  // the bug this guards against: the old "-90" formula put angle=180 at
  // y=100, far outside the viewBox's 0-55 height.
  assert.ok(y <= 55, `y=${y} is outside the viewBox height`);
});

test("all three reference angles stay within the 100x55 viewBox at full range", () => {
  for (const angle of [0, 45, 90, 135, 180]) {
    const { x, y } = sonarAngleToXY(angle, LENGTH, CX, CY);
    assert.ok(x >= 0 && x <= 100, `angle=${angle} x=${x} out of bounds`);
    assert.ok(y >= 0 && y <= 55, `angle=${angle} y=${y} out of bounds`);
  }
});
