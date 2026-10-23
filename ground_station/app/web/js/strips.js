// Camera/map 38px dashed strips for Systems and Science (docs/03b §1, §4).
// Mapping stays on hold (CLAUDE.md hard rule 6) -- the map strip never
// grows; sonar's sweep is its stand-in (Drive's surroundingswidget.js).

export class StripsWidget {
  constructor(root) {
    this.root = root;
    this.root.innerHTML = `
      <div class="strip" id="strip-camera">
        <span class="strip-icon" aria-hidden="true">&#128247;</span>
        <span><strong>Camera</strong> · not installed</span>
        <span class="strip-note">grows into a panel when fitted</span>
      </div>
      <div class="strip" id="strip-map">
        <span class="strip-icon" aria-hidden="true">&#128506;</span>
        <span><strong>Map</strong> · not built yet (mapping on hold)</span>
        <span class="strip-note">sweep shown in Sonar</span>
      </div>
    `;
  }

  render(snapshot) {
    const camera = snapshot.hello ? snapshot.hello.hw.camera : null;
    const present = !!(camera && camera.present);
    // Scoped to this.root -- Systems and Science each mount their own
    // StripsWidget with the same internal id (strip-camera); the global
    // document.getElementById would only ever reach whichever instance's
    // markup is first in index.html, same bug class as motorwidget.js.
    const stripEl = this.root.querySelector("#strip-camera");
    if (!stripEl) return;
    stripEl.classList.toggle("grown", present);
    if (present && camera.url) {
      stripEl.innerHTML = `<img src="${camera.url}" alt="Rover camera feed" class="camera-feed">`;
    } else if (!present && !stripEl.querySelector(".strip-icon")) {
      stripEl.innerHTML = `
        <span class="strip-icon" aria-hidden="true">&#128247;</span>
        <span><strong>Camera</strong> · not installed</span>
        <span class="strip-note">grows into a panel when fitted</span>
      `;
    }
  }
}
