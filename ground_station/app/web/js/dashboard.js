import { UiSocket } from "./ws.js";
import { TopBar } from "./topbar.js";
import { PowerWidget } from "./powerwidget.js";
import { PortPicker } from "./portpicker.js";
import { EventLogWidget } from "./eventlog.js";
import { EnvironmentWidget } from "./environmentwidget.js";
import { MotorWidget } from "./motorwidget.js";
import { AttitudeWidget } from "./attitudewidget.js";
import { SonarWidget } from "./sonarwidget.js";
import { SysStatsWidget } from "./sysstatswidget.js";

const topBar = new TopBar(document.getElementById("topbar"));
const powerWidget = new PowerWidget(document.getElementById("power-widget"));
const eventLog = new EventLogWidget(document.getElementById("event-log"));
const environmentWidget = new EnvironmentWidget(document.getElementById("env-widget"));
const attitudeWidget = new AttitudeWidget(document.getElementById("attitude-widget"));
const sonarWidget = new SonarWidget(document.getElementById("sonar-widget"));
const sysStatsWidget = new SysStatsWidget(document.getElementById("sysstats-widget"));
const portPicker = new PortPicker(
  document.getElementById("port-select"),
  document.getElementById("port-connect"),
  document.getElementById("port-status"),
);

// D-013: motor bars scale to ±pwm_max, not ±255 -- fetched once at startup.
let motorWidget = new MotorWidget(document.getElementById("motor-widget"), 255);
fetch("/config")
  .then((r) => r.json())
  .then((cfg) => {
    motorWidget = new MotorWidget(document.getElementById("motor-widget"), cfg.pwm_max);
  })
  .catch(() => {});

const socket = new UiSocket({
  onSnapshot: (snapshot) => {
    const nowWallMs = Date.now();
    topBar.render(snapshot, nowWallMs);
    powerWidget.render(snapshot, nowWallMs);
    eventLog.render(snapshot);
    environmentWidget.render(snapshot, nowWallMs);
    motorWidget.render(snapshot);
    attitudeWidget.render(snapshot, nowWallMs);
    sonarWidget.render(snapshot, nowWallMs);
    sysStatsWidget.render(snapshot);
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
  // Backend now owns the 10 Hz heartbeat and the "set CMD_ESTOP on the next
  // 3 CmdMsgs" latch (docs/02 §6.9) -- one request is enough.
  socket.sendCmd({ estop: true });
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

const takeControlBtn = document.getElementById("take-control-btn");
if (takeControlBtn) {
  takeControlBtn.addEventListener("click", () => socket.takeControl());
}
