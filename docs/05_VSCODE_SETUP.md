# 05 — Setting up VS Code + Claude Code

Goal: every team member opens the same repo in VS Code, with Claude Code in a side panel that
already knows the project (via `CLAUDE.md` and these docs).

## Step 0 — Move the code OUT of OneDrive
Keep the docs in OneDrive if you like, but put the **git repo** in a normal folder, e.g.
`C:\dev\rover-software`. OneDrive syncing `.git/` and `.venv/` causes locked files, sync conflicts
and corrupted repos. Share code between teammates through GitHub instead.

## Step 1 — Install the tools (each team member)
1. **VS Code** 1.94 or newer — https://code.visualstudio.com
2. **Python 3.12** — https://www.python.org (Windows: tick "Add python.exe to PATH")
3. **Git** — https://git-scm.com
4. **USB driver** for the ESP32 DevKit (CP210x or CH340, depending on the chip next to the USB port)
5. A **paid Claude account** (Pro/Max/Team) — required for Claude Code. No API key needed.

## Step 2 — VS Code extensions
Open Extensions (`Ctrl+Shift+X`) and install:
- **Claude Code** (publisher: Anthropic)
- **Python** + **Pylance** (Microsoft)
- **PlatformIO IDE** (for ESP32 firmware)
- Optional: **GitLens**, **Error Lens**

If the Claude Code icon doesn't appear, run "Developer: Reload Window" from `Ctrl+Shift+P`.

## Step 3 — Create the repo
`C:\dev` does not exist by default — you create it. Use **PowerShell** (Start menu → "PowerShell"),
not Command Prompt:
```powershell
New-Item -ItemType Directory -Force C:\dev
Copy-Item -Recurse "C:\Users\Usuario\Desktop\OneDrive\Univesidad Europea\Year 3\Space Vehicles & Missiles\Rover Project\rover-software" C:\dev\
cd C:\dev\rover-software
git init
git add .
git commit -m "Add planning docs and CLAUDE.md"
```
If Windows refuses to create `C:\dev` (locked-down PC), use `$HOME\dev` instead — any folder
**outside OneDrive** works.

No terminal? In File Explorer: open `C:\`, New → Folder → `dev`, then copy the `rover-software`
folder into it. Afterwards run the `git` lines from a terminal opened in that folder.

Create a **private** GitHub repo, add teammates as collaborators, then:
```powershell
git remote add origin https://github.com/<you>/rover-software.git
git branch -M main ; git push -u origin main
```
Teammates: `git clone` it into their own `C:\dev`.

## Step 4 — Open in VS Code and start Claude Code
1. `File → Open Folder… → C:\dev\rover-software`
2. Click the **Spark icon** (Claude Code) in the left Activity Bar or top-right of an open file.
3. Sign in with your Claude account the first time.
4. **Don't run `/init`** — `CLAUDE.md` already exists and `/init` would rewrite it.
5. Check the permission mode at the bottom of the prompt box. Start in a mode that **asks before
   editing** until you trust the workflow. Use **plan mode** (`/plan`) for each new phase so you
   review the plan before any code is written.
6. Reference files in prompts with `@`, e.g. `@docs/02_TELEMETRY_PROTOCOL.md`.

## Step 5 — Python environment (Claude Code can do this in Prompt 1, or do it yourself)
```powershell
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -r ground_station/requirements.txt
```
In VS Code: `Ctrl+Shift+P → Python: Select Interpreter → .venv`.

## Step 5b — Turn on the repo's Git reminders (once per clone)
```powershell
git config core.hooksPath tools/hooks
```
After this, `git pull` prints a warning whenever `ground_station/requirements.txt` changed, telling
you to run `pip install -r ground_station/requirements.txt`.

## Step 6 — Work loop (per prompt in 06_CLAUDE_CODE_PROMPTS.md)
1. New Claude Code conversation per phase (keeps context focused).
2. Paste the prompt → review the plan → approve.
3. Review the diffs Claude shows; ask for changes in plain language.
4. Run the acceptance check listed under the prompt yourself.
5. `git commit` (or ask Claude to commit) → `git push`.
6. If something breaks: Claude Code has checkpoints/rewind, and git is your real safety net.

## Team workflow tips
- One person per phase/branch: `git checkout -b phase-3-dashboard`, merge via Pull Request.
- If you change the protocol, the PR must touch `docs/02`, `protocol.py` and `fake_rover.py` together
  (rule in CLAUDE.md — Claude Code will follow it).
- Commit `CLAUDE.md` changes too: it is the shared memory for everyone's Claude Code.
