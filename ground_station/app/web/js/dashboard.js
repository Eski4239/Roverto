import { UiSocket } from "./ws.js";
import { TopBar } from "./topbar.js";
import { PowerWidget } from "./powerwidget.js";
import { PortPicker } from "./portpicker.js";

const topBar = new TopBar(document.getElementById("topbar"));
const powerWidget = new PowerWidget(document.getElementById("power-widget"));
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
    if (snapshot.link && snapshot.link.state === "NO_BRIDGE") {
      portPicker.ensureLoaded();
    }
  },
});

// E-STOP: button + Space, sends estop:true three times 50 ms apart (docs/03 §3).
let estopLatched = false;
const estopBtn = document.getElementById("estop-btn");

function sendEstop() {
  estopLatched = true;
  estopBtn.classList.add("latched");
  for (let i = 0; i < 3; i++) {
    setTimeout(() => socket.sendCmd({ estop: true }), i * 50);
  }
}

function resetEstop() {
  if (!estopLatched) return;
  const confirmed = window.confirm("Reset E-STOP?");
  if (!confirmed) return;
  estopLatched = false;
  estopBtn.classList.remove("latched");
  socket.sendCmd({ estop_reset: true });
}

estopBtn.addEventListener("click", () => {
  if (estopLatched) {
    resetEstop();
  } else {
    sendEstop();
  }
});

window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !e.repeat) {
    e.preventDefault();
    if (!estopLatched) sendEstop();
  }
});
