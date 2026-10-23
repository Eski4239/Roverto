import test from "node:test";
import assert from "node:assert/strict";

// Minimal window shim: addEventListener/removeEventListener backed by a
// real EventTarget, so KeyboardInput's window.addEventListener("keydown",
// ...) calls work without a browser. setInterval/clearInterval and
// performance.now() are already real Node globals.
class FakeWindow extends EventTarget {}
globalThis.window = new FakeWindow();

const { KeyboardInput } = await import("../ground_station/app/web/js/keyboard.js");

function keyEvent(type, key) {
  const e = new Event(type);
  e.key = key;
  // target is read-only on a native Event, but dispatchEvent() sets it to
  // the EventTarget it was dispatched on (our FakeWindow instance), which
  // has no tagName -- keyboard.js's `target.tagName === "INPUT"` check
  // reads as undefined, same as a real non-input dispatch target.
  return e;
}

function fakeSocket() {
  const sent = [];
  return { sent, sendCmd: (partial) => sent.push(partial) };
}

test("P5 regression: Shift pressed just after a direction key still boosts, via the periodic flush", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "w"));
    window.dispatchEvent(keyEvent("keydown", "Shift"));

    // give the periodic flush (<=20Hz, i.e. every 50ms) a couple of ticks
    await new Promise((r) => setTimeout(r, 150));

    const boosted = socket.sent.some((c) => c.drive && c.drive.l === 1.0 && c.drive.r === 1.0);
    assert.ok(boosted, `Shift boost never reached the backend; sent=${JSON.stringify(socket.sent)}`);
  } finally {
    kb.destroy();
  }
});

test("release (key-up) sends drive 0 promptly", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "w"));
    await new Promise((r) => setTimeout(r, 80));
    window.dispatchEvent(keyEvent("keyup", "w"));
    await new Promise((r) => setTimeout(r, 80));

    const last = socket.sent[socket.sent.length - 1];
    assert.equal(last.drive.l, 0);
    assert.equal(last.drive.r, 0);
  } finally {
    kb.destroy();
  }
});

test("blur releases held keys", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "w"));
    await new Promise((r) => setTimeout(r, 20));
    window.dispatchEvent(new Event("blur"));

    const last = socket.sent[socket.sent.length - 1];
    assert.equal(last.drive.l, 0);
    assert.equal(last.drive.r, 0);
  } finally {
    kb.destroy();
  }
});
