import test from "node:test";
import assert from "node:assert/strict";
import { downsample, yRange } from "../ground_station/app/web/js/sparkline.js";

test("downsample returns empty for empty input", () => {
  assert.deepEqual(downsample([]), []);
});

test("downsample averages points within a bucket", () => {
  const points = [
    [0, 10],
    [200, 20],
    [1000, 30],
  ];
  const result = downsample(points, 1000);
  assert.deepEqual(result, [
    [0, 15],
    [1000, 30],
  ]);
});

test("downsample keeps bucket order ascending regardless of map iteration", () => {
  const points = [
    [5000, 1],
    [0, 2],
    [2000, 3],
  ];
  const result = downsample(points, 1000);
  assert.deepEqual(result.map((p) => p[0]), [0, 2000, 5000]);
});

test("yRange returns the natural span when it already meets minSpan", () => {
  assert.deepEqual(yRange([10, 20], 2), [10, 20]);
});

test("yRange centers a minimum span when the data is flatter than minSpan", () => {
  assert.deepEqual(yRange([10, 10.5], 2), [9.25, 11.25]);
});

test("yRange with minSpan 0 behaves like plain min/max", () => {
  assert.deepEqual(yRange([3, 7, 5], 0), [3, 7]);
});
