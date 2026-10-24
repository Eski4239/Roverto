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

test("Phase 10: ArrowRight/ArrowLeft step the servo angle, clamped, without touching drive", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "ArrowRight"));
    let last = socket.sent[socket.sent.length - 1];
    assert.deepEqual(last.servo, { mode: "fixed", angle_deg: 95 });

    window.dispatchEvent(keyEvent("keydown", "ArrowLeft"));
    window.dispatchEvent(keyEvent("keydown", "ArrowLeft"));
    last = socket.sent[socket.sent.length - 1];
    assert.deepEqual(last.servo, { mode: "fixed", angle_deg: 85 });

    assert.ok(!socket.sent.some((c) => c.drive), "servo keys must never send a drive command");
  } finally {
    kb.destroy();
  }
});

test("Phase 10: ArrowRight clamps at 180 degrees", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    for (let i = 0; i < 30; i++) window.dispatchEvent(keyEvent("keydown", "ArrowRight"));
    const last = socket.sent[socket.sent.length - 1];
    assert.deepEqual(last.servo, { mode: "fixed", angle_deg: 180 });
  } finally {
    kb.destroy();
  }
});

test("Phase 10: holding B sounds the buzzer once, releasing stops it", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "b"));
    window.dispatchEvent(keyEvent("keydown", "b")); // key-repeat while held -- must not re-send
    assert.deepEqual(
      socket.sent.filter((c) => "buzzer" in c),
      [{ buzzer: true }],
    );

    window.dispatchEvent(keyEvent("keyup", "b"));
    const last = socket.sent[socket.sent.length - 1];
    assert.deepEqual(last, { buzzer: false });
  } finally {
    kb.destroy();
  }
});

test("Phase 10: blur while B is held stops the buzzer", async () => {
  const socket = fakeSocket();
  const kb = new KeyboardInput(socket, { isActive: () => true });
  kb.setSpeedLimit(1.0);
  try {
    window.dispatchEvent(keyEvent("keydown", "b"));
    window.dispatchEvent(new Event("blur"));
    const last = socket.sent[socket.sent.length - 1];
    assert.deepEqual(last, { buzzer: false });
  } finally {
    kb.destroy();
  }
});
