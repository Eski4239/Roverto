// Shared sonar-angle-to-xy math for the radar widgets (sonarwidget.js,
// surroundingswidget.js). docs/02: angle_deg 0 = front, CCW+. Both widgets
// draw a semicircle from the left point (angle=0) through the top
// (angle=90) to the right point (angle=180), centred at (cx, cy).
// P4 fix: pulled out as a pure function so the angle math is unit-testable
// (tests_js/) without a DOM, same convention as sparkline.js's downsample.

/**
 * @param {number} angleDeg - 0..180, 0 = front/left point, 180 = right point
 * @param {number} length - distance from centre, in the same units as cx/cy
 * @param {number} cx
 * @param {number} cy
 * @returns {{x: number, y: number}}
 */
export function sonarAngleToXY(angleDeg, length, cx, cy) {
  const angleRad = ((angleDeg - 180) * Math.PI) / 180;
  return {
    x: cx + length * Math.cos(angleRad),
    y: cy + length * Math.sin(angleRad),
  };
}
