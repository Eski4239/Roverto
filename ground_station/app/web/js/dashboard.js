import { UiSocket } from "./ws.js";
import { TopBar } from "./topbar.js";
import { PortPicker } from "./portpicker.js";
import { EventLogWidget } from "./eventlog.js";
import { MotorWidget } from "./motorwidget.js";
import { AttitudeWidget } from "./attitudewidget.js";
import { SonarWidget } from "./sonarwidget.js";
import { SysStatsWidget } from "./sysstatswidget.js";
import { PresetController } from "./presets.js";
import { ControlPanel } from "./controlpanel.js";
import { StripsWidget } from "./strips.js";
import { PowerTilesWidget } from "./powertiles.js";
import { EnvTilesWidget } from "./envtiles.js";
import { SurroundingsWidget } from "./surroundingswidget.js";
import { setThresholds } from "./thresholds.js";

const expandSlotEl = document.getElementById("expand-slot");

const topBar = new TopBar(document.getElementById("topbar"));
const eventLog = new EventLogWidget(
  document.getElementById("event-log"),
  document.getElementById("eventlog-filter"),
);
const portPicker = new PortPicker(
  document.getElementById("port-select"),
  document.getElementById("port-connect"),
  document.getElementById("port-status"),
);

const stripsSystems = new StripsWidget(document.getElementById("strips-systems"));
const stripsScience = new StripsWidget(document.getElementById("strips-science"));
const powerTiles = new PowerTilesWidget(document.getElementById("power-tiles"));
const envTiles = new EnvTilesWidget(document.getElementById("env-tiles"), expandSlotEl);
const sonarCardScience = new SonarWidget(document.getElementById("sonar-card-science"));
const sysStatsWidget = new SysStatsWidget(document.getElementById("sysstats-widget"));
const surroundingsWidget = new SurroundingsWidget(document.getElementById("surroundings-widget"));

// D-013: motor bars scale to ±pwm_max, not ±255 -- fetched once at startup
// alongside the threshold table (single /config round trip for both).
// F6: previously constructed with a hardcoded `255` default and replaced
// once /config resolved, so bars briefly read against the wrong full
// scale on every page load. Stay null (unrendered, same as every other
// value before the first snapshot) until the real pwm_max is known.
let motorWidgetSystems = null;
let motorWidgetDrive = null;
const attitudeWidgetSystems = new AttitudeWidget(document.getElementById("attitude-card-systems"), expandSlotEl);
const attitudeWidgetDrive = new AttitudeWidget(document.getElementById("attitude-card-drive"), null);

fetch("/config")
  .then((r) => r.json())
  .then((cfg) => {
    setThresholds(cfg.thresholds);
    motorWidgetSystems = new MotorWidget(document.getElementById("motor-card-systems"), cfg.pwm_max, expandSlotEl);
    motorWidgetDrive = new MotorWidget(document.getElementById("motor-card-drive"), cfg.pwm_max, null);
  })
  .catch(() => {});

const socket = new UiSocket({
  onSnapshot: (snapshot) => {
    const nowWallMs = Date.now();
    topBar.render(snapshot, nowWallMs);
    eventLog.render(snapshot);
    stripsSystems.render(snapshot);
    stripsScience.render(snapshot);
    powerTiles.render(snapshot, nowWallMs);
    envTiles.render(snapshot, nowWallMs);
    sonarCardScience.render(snapshot, nowWallMs);
    sysStatsWidget.render(snapshot);
    surroundingsWidget.render(snapshot, nowWallMs);
    if (motorWidgetSystems) motorWidgetSystems.render(snapshot);
    if (motorWidgetDrive) motorWidgetDrive.render(snapshot);
    attitudeWidgetSystems.render(snapshot, nowWallMs);
    attitudeWidgetDrive.render(snapshot, nowWallMs);
    controlPanel.render(snapshot);
    renderLinkCard(snapshot);
    renderEstop(snapshot);
    renderLostBanner(snapshot, nowWallMs);
    renderNoBridgeBanner(snapshot);
    if (snapshot.link && snapshot.link.state === "NO_BRIDGE") {
      portPicker.ensureLoaded();
    }
  },
});

const controlPanel = new ControlPanel(document.getElementById("control-column"), socket);

const presetController = new PresetController({
  panelsByName: {
    systems: document.getElementById("preset-systems"),
    science: document.getElementById("preset-science"),
    drive: document.getElementById("preset-drive"),
  },
  switchEls: document.querySelectorAll("#preset-switch button"),
});
presetController.switchTo(presetController.current());

function renderLinkCard(snapshot) {
  const link = snapshot.link || {};
  const linkOk = link.state === "OK";
  const text = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  };
  text("link-loss", linkOk && link.loss_pct != null ? `${link.loss_pct.toFixed(1)} %` : "—");
  text("link-rtt", linkOk && link.rtt_ms != null ? `${Math.round(link.rtt_ms)} ms` : "—");
  text("link-rxhz", `${link.rx_hz != null ? link.rx_hz.toFixed(1) : "—"} Hz`);
  text("link-rssi-rover", link.rssi_rover_dbm != null ? `${link.rssi_rover_dbm} dBm` : "—");
  text("link-rssi-bridge", link.rssi_bridge_dbm != null ? `${link.rssi_bridge_dbm} dBm` : "—");
  text("link-tx-fail", link.bridge_tx_fail != null ? `${link.bridge_tx_fail}` : "—");
}

// E-STOP: button + Space *send* the estop cmd, but the button's visual state
// (outlined vs. solid-flashing-active + banner) is driven entirely by
// telem.state.estop -- what the rover reports -- not by the key press, so it
// stays correct if the rover latches estop on its own (tilt, watchdog, etc.)
// and only clears once the rover confirms it (docs/02 TILT/WD_STOP; docs/03 §3).
const estopBtn = document.getElementById("estop-btn");
const estopBanner = document.getElementById("estop-banner");
const lostBanner = document.getElementById("lost-banner");
const noBridgeBanner = document.getElementById("no-bridge-banner");
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

function renderLostBanner(snapshot, nowWallMs) {
  if (!lostBanner) return;
  const link = snapshot.link || {};
  if (link.state === "LOST") {
    const ageS = topBar.secondsSinceLastTelem(nowWallMs);
    lostBanner.textContent =
      `No telemetry for ${ageS} s. The bridge is connected but the rover is silent. ` +
      `E-STOP state unknown; the rover's watchdog stops the motors after 0.5 s without commands.`;
    lostBanner.classList.add("visible");
  } else {
    lostBanner.classList.remove("visible");
  }
}

function renderNoBridgeBanner(snapshot) {
  // F25: this banner's HTML/CSS (port picker, "Plug in ground bridge")
  // was fully built (docs/03 §5) but nothing ever toggled its .visible
  // class -- NO_BRIDGE only ever showed up in the top-bar link pill, this
  // banner stayed permanently hidden. Same visible-class pattern as
  // renderLostBanner/renderEstop above.
  if (!noBridgeBanner) return;
  const link = snapshot.link || {};
  noBridgeBanner.classList.toggle("visible", link.state === "NO_BRIDGE");
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
