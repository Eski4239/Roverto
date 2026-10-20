import { UiSocket } from "./ws.js";
import { TopBar } from "./topbar.js";
import { PowerWidget } from "./powerwidget.js";
import { PortPicker } from "./portpicker.js";
import { EventLogWidget } from "./eventlog.js";

const topBar = new TopBar(document.getElementById("topbar"));
const powerWidget = new PowerWidget(document.getElementById("power-widget"));
const eventLog = new EventLogWidget(document.getElementById("event-log"));
const portPicker = new PortPicker(
  document.getElementById("port-select"),
  document.getElementById("port-connect"),
  document.getElementById("port-status"),
);

const socket = new UiSocket({
  onSnapshot: (snapshot) => {
    const nowWallMs = Date.now();
    topBar.render(snapshot, nowWallMs);
    powerWidget.render(snapshot);
    eventLog.render(snapshot);
    renderEstop(snapshot);
    if (snapshot.link && snapshot.link.state === "NO_BRIDGE") {
      portPicker.ensureLoaded();
    }
  },
});

// E-STOP: button + Space *send* the estop cmd, but the button's visual state
// (outlined vs. solid-flashing-active + banner) is driven entirely by
// telem.state.estop -- what the rover reports -- not by the key press, so it
// stays correct if the rover latches estop on its own (tilt, watchdog, etc.)
// and only clears once the rover confirms it (docs/02 TILT/WD_STOP; docs/03 §3).
const estopBtn = document.getElementById("estop-btn");
const estopBanner = document.getElementById("estop-banner");
let roverEstopActive = false;
let resetRequestedAt = 0; // debounce: avoid spamming estop_reset while rover hasn't cleared yet

function sendEstop() {
  for (let i = 0; i < 3; i++) {
    setTimeout(() => socket.sendCmd({ estop: true }), i * 50);
  }
}

function requestEstopReset() {
  const confirmed = window.confirm("Reset E-STOP?");
  if (!confirmed) return;
  resetRequestedAt = Date.now();
  socket.sendCmd({ estop_reset: true });
}

function renderEstop(snapshot) {
  const active = !!(snapshot.telem && snapshot.telem.state.estop);
  roverEstopActive = active;
  estopBtn.classList.toggle("latched", active);
  if (estopBanner) estopBanner.classList.toggle("visible", active);
}

estopBtn.addEventListener("click", () => {
  if (roverEstopActive) {
    requestEstopReset();
  } else {
    sendEstop();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat) {
    e.preventDefault();
    if (!roverEstopActive) sendEstop();
  }
});
