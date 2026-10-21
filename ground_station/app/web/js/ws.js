// Websocket connection to /ws/ui: dispatches each snapshot to a listener and
// exposes a sendCmd() for outbound cmd messages (estop / estop_reset / request_hello
// this phase; full drive loop comes with the Control panel phase).

export class UiSocket {
  constructor({ onSnapshot, onOpen, onClose } = {}) {
    this._onSnapshot = onSnapshot || (() => {});
    this._onOpen = onOpen || (() => {});
    this._onClose = onClose || (() => {});
    this._ws = null;
    this._connect();
  }

  _connect() {
    const url = `ws://${location.host}/ws/ui`;
    const ws = new WebSocket(url);
    this._ws = ws;
    ws.onopen = () => this._onOpen();
    ws.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch (err) {
        return;
      }
      this._onSnapshot(data);
    };
    ws.onclose = () => {
      this._onClose();
      setTimeout(() => this._connect(), 1000);
    };
    ws.onerror = () => ws.close();
  }

  sendCmd(partial) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ws.send(JSON.stringify({ type: "cmd", ...partial }));
  }

  takeControl() {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ws.send(JSON.stringify({ type: "take_control" }));
  }
}
