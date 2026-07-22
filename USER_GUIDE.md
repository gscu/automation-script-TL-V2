# Bandwidth Report Manager — User Guide

This guide covers day-to-day use of the app. For first-time installation,
see EASY_SETUP.md instead.

The app generates the twice-daily TELUS eHealth bandwidth reports: it
fetches a 24-hour trend PDF for every monitored interface, checks each one
for peaks (70% or more of capacity) and dips (below 1 Mbps), and opens a
pre-filled Outlook email with the PDFs attached and a color-coded summary
at the top. You review the email and press Send.

---

## The main window

**Run buttons** — "Run Morning Report Now" and "Run Afternoon Report Now"
start a report immediately. While one is running, both buttons are
disabled until it finishes. (The sidebar has the same two buttons.)

**Task Scheduler panel** — the table lists the two Windows scheduled
tasks with their status, next run, and last result. The switch on each
row enables or disables that task without deleting it. The "N/2 enabled"
summary on the right is an at-a-glance count of active tasks.

**Console** — the panel filling the bottom of the window is always
visible, so you never have to click around to find output. It streams
both what the app is doing and the live output of a running report
(bandwidth readings, alerts, errors), color-coded (see below). The
window is fully resizable — drag any edge and everything, including the
console, scales with it.

**Appearance** — the **Light / Dark** toggle at the bottom of the sidebar
switches the whole app between themes on the spot.

---

## Running a report

1. Click **Run Morning Report Now** (or Afternoon).
2. The **Console** at the bottom streams the report's progress live — no
   separate console window opens:
   - White/grey lines — normal progress (each interface being processed,
     with its bandwidth readings)
   - Green lines — success messages
   - Yellow lines — warnings and retries (usually fine; the portal is
     often slow and the script retries up to 10 times per interface)
   - Red lines — errors
3. A browser window opens and works through the portal by itself —
   leave it alone; it closes when done.
4. When the console shows **"finished (exit code 0)"** in green, the run
   worked. An Outlook email opens with the PDFs attached and the alert
   summary on top — review it and press Send.
5. **📁 Open Reports Folder** in the sidebar opens the folder where every
   run saves its PDFs and summary. Each run gets its **own timestamped
   subfolder** (e.g. `Morning Reports - 2026-07-22 14-30-05`), so running
   twice in a day never mixes files into one folder.

**If a run gets stuck**, press the red **⏹ Stop** button in the Console
header, then simply run it again. **Clear** empties the console; the
sidebar's **🧹 Clear Console** does the same.

**Prefer a separate console window?** Tick "Open reports in a separate
console window" above the run buttons — the output then goes to its own
window instead of the in-app console. Most people can leave this off.

---

## Automatic (scheduled) reports

If scheduling was enabled during setup, Windows Task Scheduler runs the
Morning report at 10:58 and the Afternoon report at 14:58 every day —
the app does not need to be open for this.

- Use the switches in the Task Scheduler panel to pause/resume a task.
- **🔄 Refresh Scheduler** re-reads the current task states.
- "Not found" means the task was never created — re-run `Setup_script.py`
  and answer **y** when asked about Task Scheduler.
- To change the times, edit `SCHEDULED_TASKS` in `Setup_script.py` and
  re-run it.

---

## ⚙ Options

**eHealth Credentials** — your portal username and password, used by the
report scripts to log in. The password is encrypted for your Windows
account (DPAPI) before it is saved, so it never sits in the files as
plain text. Untick **"Encrypt password when saving"** only if you are
deliberately preparing this folder to move to another PC — an encrypted
password cannot travel; a plain-text one can (re-encrypt it there by
saving Options once).

**Reports Folder** — where the per-run report folders are created. Leave
it as suggested unless you want them somewhere specific (e.g. OneDrive).

Changes take effect the next time a report runs.

---

## 🖧 Interfaces

Open it from **🖧 Interfaces** in the sidebar. This is where you manage
which interfaces the reports cover, without touching any code.

- **Interface (MSUID)** — the exact filter text typed into the portal for
  each report. Edit any name in place.
- **Bandwidth limit (Gbps)** — the total capacity used to work out the
  "% of capacity" peaks. Leave it **blank** to read the capacity straight
  from each report PDF (the normal case); fill it in only for interfaces
  whose PDF doesn't state a bandwidth.
- **Skip low-BW alert** — tick this for an interface that is expected to
  sit idle, so it won't raise a "dipped below 1 Mbps" alert.
- **＋ Add interface** adds a blank row; the **🗑** button deletes a row
  (it asks first).
- **Restore defaults** brings back the built-in list; **Save** writes your
  changes. Saved changes apply to the **next** report run.

---

## Moving to a new computer or user account

1. Copy the whole folder.
2. Run `setup.bat` there once (installs Python packages, recreates the
   Desktop shortcut, asks for credentials again).

The saved password from the old machine will not decrypt on the new one —
that is by design. Re-entering it during setup (or in ⚙ Options) fixes it.

---

## Quick troubleshooting

| What you see | What it means |
|---|---|
| Red lines right at the portal step | Wrong username/password (fix in ⚙ Options) or the portal URL changed |
| "report not ready (attempt N/10)" repeating | Portal is slow or down — it retries by itself; try again later if it gives up |
| "BW not found in …" | That interface's PDF doesn't state total bandwidth — the run continues, percentages show 0 for it |
| "password could not be decrypted" | Folder came from another PC/account — re-enter the password in ⚙ Options |
| Run finishes but no email opens | Outlook desktop isn't installed, or the two `.oft` template files are missing from the app folder |
| Task shows "Not found" | Scheduling was never set up — re-run `Setup_script.py` |

Still stuck? Screenshot the Console panel (the colored lines tell most of
the story) and send it to whoever maintains the app.
