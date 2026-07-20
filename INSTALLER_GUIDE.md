# Packaging & Installer Guide — Bandwidth Report Manager

How to hand this project to other machines/users. Route A needs no build
step at all; B and B+ produce a branded exe/installer for the GUI.

## The one thing that makes this project different

The manager GUI *could* be frozen into a fully self-contained .exe —
**but the report scripts can't be**, because of how the project works:

1. The manager **patches credentials and paths directly into
   `Morning BW Reports.py` / `Afternoon BW Reports.py`**. Frozen code can't
   be patched, so those two scripts must stay as loose `.py` files.
2. The report scripts therefore **run under the machine's own Python**
   (with pywin32, aiohttp, pdfplumber, and Playwright installed).

So whichever route you pick below, **target machines need Python 3
installed**. The choice is only about how the *manager GUI* is delivered.

---

## Route A — Script package (recommended)

No build step. Zip this folder and send it. The recipient:

1. Installs Python 3 from https://www.python.org/downloads/
   (ticking **"Add Python to PATH"**).
2. Unzips the folder anywhere user-writable (Documents, Desktop — **not**
   Program Files).
3. Double-clicks **`setup.bat`** once. It:
   - installs everything in `requirements.txt`,
   - installs Playwright's Chromium engine (~150 MB, one-time),
   - drops a **"Bandwidth Report Manager"** shortcut on the Desktop,
   - walks them through credentials, reports folder, and scheduling.
4. Opens the app from that shortcut (it uses
   `Launch Bandwidth Report Manager.vbs`, so no console window flashes).

What to include in the zip:

| File | Why |
|---|---|
| `bandwidth_report_manager.py` | the GUI |
| `Morning BW Reports.py`, `Afternoon BW Reports.py` | the report scripts |
| `Setup_script.py` | guided configuration / scheduled-task creation |
| `credential_store.py` | password encryption (DPAPI) — the report scripts import it |
| `Task Morning/Afternoon BW Reports.bat` | Task Scheduler wrappers |
| `*.oft` templates | Outlook email templates — **don't forget these** |
| `requirements.txt`, `setup.bat`, `Launch Bandwidth Report Manager.vbs` | install + launch |
| `EASY_SETUP.md`, `README.md`, `USER_GUIDE.md` | instructions (the app's 📖 button reads USER_GUIDE.md) |

## Route B — Frozen .exe

Gives users a branded, double-clickable **`Bandwidth Report Manager.exe`**
with no console window and no need for customtkinter on their machine.
Python is still required for the report scripts (see above), so users still
run `setup.bat` once.

On **your** machine:

1. Double-click **`BUILD_EXE.bat`**. It:
   - installs PyInstaller + dependencies,
   - compiles the GUI using **`bandwidth_manager.spec`**,
   - copies the report scripts, `.oft` templates, `setup.bat`, and
     `requirements.txt` next to the exe,
   - zips everything into **`Bandwidth Report Manager.zip`**.
2. Send the zip. Recipients unzip, run `setup.bat` once, then use the exe.

Notes:

- The spec collects customtkinter's theme assets automatically.
- The frozen manager finds the machine's Python on PATH at runtime
  (`find_python()` in the manager handles this — `sys.executable` points at
  the exe itself when frozen, which is why this helper exists).
- To brand the exe, drop an `.ico` file next to the spec and set
  `icon="bw.ico"` in `bandwidth_manager.spec`.

## Route B+ — Real Setup.exe wizard (optional, Inno Setup)

Wraps Route B's output in a proper installer with Start-menu entry,
uninstaller, and desktop-shortcut checkbox:

1. Run `BUILD_EXE.bat` first (creates `dist\Bandwidth Report Manager\`).
2. Install Inno Setup (free): https://jrsoftware.org/isdl.php
3. Open **`installer.iss`** in Inno Setup and click **Build**
   (or run `ISCC.exe installer.iss` from a terminal).
4. Send `Output\BandwidthReportManagerSetup.exe`.

This installs **per-user** into
`%LOCALAPPDATA%\Programs\Bandwidth Report Manager` instead of Program
Files. That's deliberate: the manager writes credentials into the report
scripts sitting next to it, and Program Files is read-only for normal
users. Don't change `DefaultDirName` back to `{autopf}` — Options → Save
would silently fail.

## Quick comparison

|  | Route A (scripts) | Route B (exe) | Route B+ (Setup.exe) |
|---|---|---|---|
| Build step needed | none | PyInstaller | PyInstaller + Inno |
| Python needed on target | yes | yes (for reports) | yes (for reports) |
| Console-free GUI launch | yes (via .vbs) | yes (native) | yes (native) |
| Easiest to update | ✔ just resend a .py | rebuild | rebuild |
| Most professional feel | – | ✔ | ✔✔ |

Start with Route A. Reach for B/B+ when you want to hand this to people
who shouldn't ever see a `.py` file.
