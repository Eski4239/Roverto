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
    const stripEl = document.getElementById("strip-camera");
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
