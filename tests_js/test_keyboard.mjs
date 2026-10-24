import test from "node:test";
import assert from "node:assert/strict";
import { driveFromKeys } from "../ground_station/app/web/js/keyboard.js";

test("no keys held -> zero drive", () => {
  assert.deepEqual(driveFromKeys(new Set(), 1.0), { l: 0, r: 0 });
});

test("W alone drives both wheels forward at half (no Shift boost)", () => {
  const { l, r } = driveFromKeys(new Set(["w"]), 1.0);
  assert.equal(l, 0.5);
  assert.equal(r, 0.5);
});

test("arrow keys no longer drive (Phase 10: freed up for servo pan)", () => {
  assert.deepEqual(driveFromKeys(new Set(["arrowup", "arrowdown", "arrowleft", "arrowright"]), 1.0), { l: 0, r: 0 });
});

test("Shift boosts W to full speed", () => {
  const { l, r } = driveFromKeys(new Set(["w", "shift"]), 1.0);
  assert.equal(l, 1.0);
  assert.equal(r, 1.0);
});

test("S alone drives both wheels backward", () => {
  const { l, r } = driveFromKeys(new Set(["s"]), 1.0);
  assert.equal(l, -0.5);
  assert.equal(r, -0.5);
});

test("A alone turns in place (left back, right forward)", () => {
  const { l, r } = driveFromKeys(new Set(["a"]), 1.0);
  assert.equal(l, -0.5);
  assert.equal(r, 0.5);
});

test("D alone turns the other way", () => {
  const { l, r } = driveFromKeys(new Set(["d"]), 1.0);
  assert.equal(l, 0.5);
  assert.equal(r, -0.5);
});

test("W+D curves forward-right, clamped to +-1", () => {
  const { l, r } = driveFromKeys(new Set(["w", "d", "shift"]), 1.0);
  assert.equal(l, 1.0); // fwd(1) + turn(1) = 2, clamped to 1
  assert.equal(r, 0.0); // fwd(1) - turn(1) = 0
});

test("opposing keys (W+S) cancel out", () => {
  assert.deepEqual(driveFromKeys(new Set(["w", "s"]), 1.0), { l: 0, r: 0 });
});

test("speed limit scales the result", () => {
  const { l, r } = driveFromKeys(new Set(["w", "shift"]), 0.5);
  assert.equal(l, 0.5);
  assert.equal(r, 0.5);
});
