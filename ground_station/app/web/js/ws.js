// Websocket connection to /ws/ui: dispatches each snapshot to a listener and
// exposes a sendCmd() for outbound cmd messages (estop / estop_reset / request_hello
// this phase; full drive loop comes with the Control panel phase).

export class UiSocket {
  constructor({ onSnapshot, onOpen, onClose } = {}) {
    this._onSnapshot = onSnapshot || (() => {});
    this._onOpen = onOpen || (() => {});
    this._onClose = onClose || (() => {});
    this._ws = null;
    // F21: the very first connect() from a fresh page load may become
    // controller if nobody else is; every connect() after that (ws.js's
    // own auto-reconnect, e.g. after a backend restart) tells the server
    // this is a reconnect, not a fresh load, so it's never auto-promoted
    // -- the operator has to press TAKE CONTROL again on purpose.
    this._hasConnectedBefore = false;
    this._connect();
  }

  _connect() {
    const url = `ws://${location.host}/ws/ui`;
    const ws = new WebSocket(url);
    const isReconnect = this._hasConnectedBefore;
    this._hasConnectedBefore = true;
    this._ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "hello", reconnect: isReconnect }));
      this._onOpen();
    };
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

  setInputMode(mode) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) return;
    this._ws.send(JSON.stringify({ type: "set_input_mode", mode }));
  }
}
