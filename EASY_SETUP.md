# Easy Setup — Bandwidth Report Manager

This guide assumes you know nothing. Just follow the steps in order.
The whole thing takes about 10-15 minutes, most of it waiting for downloads.

---

## Step 1 — Install Python (one time only)

Python is a free program this app needs to run.

1. Open this link in your web browser:
   **https://www.python.org/downloads/**
2. Click the big yellow **"Download Python 3.x"** button.
3. Open the file it downloaded.
4. ⚠️ **IMPORTANT — READ BEFORE CLICKING:** at the bottom of the first
   screen there is a small checkbox that says
   **"Add Python to PATH"**. **TICK IT.**
   (If you miss this, nothing else will work. If you already clicked past
   it, just run the installer again and choose "Modify".)
5. Now click **"Install Now"** and wait for it to finish.
6. Close the installer.

---

## Step 2 — Put the app folder somewhere normal

1. You were given a zip file called something like
   **"Bandwidth Report Manager.zip"**.
2. Right-click it → **"Extract All..."** → click **Extract**.
3. Move the extracted folder somewhere easy, like your **Documents**
   folder or your **Desktop**.

   🚫 Do **not** put it in "Program Files". The app needs to save
   settings inside its own folder and Windows blocks that there.
4. Make sure the two Outlook email templates are in the folder:
   - `Daily Morning Reports yy-mm-dd.oft`
   - `Daily Afternoon Reports yy-mm-dd.oft`

   If you don't have them, ask whoever gave you this app.

---

## Step 3 — Run the setup (one time only)

1. Open the folder from Step 2.
2. Double-click the file called **`setup`** (or **`setup.bat`**).
3. A black window will open and start printing text. **This is normal.**
   It is installing the pieces the app needs, including a browser engine
   (about 150 MB), so it can take 5-10 minutes.

   💡 If Windows shows a blue warning saying *"Windows protected your
   PC"*, click **"More info"**, then **"Run anyway"**. This just means
   Windows doesn't recognize the file — it's ours and it's safe.
4. Near the end, the same window asks you a few questions:
   - **Where should reports be saved?** — press Enter to accept the
     suggested folder (a `reports` folder inside the app folder).
   - **Username / Password** — your eHealth portal login.
     (Nothing appears while you type the password — that's on purpose.)
   - **Encrypt the password?** — just press Enter (yes). It scrambles
     your password so it isn't readable in the app's files.
   - **Add to Windows Task Scheduler?** — type `y` if you want the
     morning and afternoon reports to run automatically every day,
     or `n` to always run them yourself from the app.
5. When the black window says **"Done!"**, press any key to close it.
6. There should now be a **"Bandwidth Report Manager"** icon on your
   Desktop.

---

## Step 4 — Run your first report 🎉

1. Double-click the **Bandwidth Report Manager** icon on your Desktop.
   A dark blue window opens.
2. Click the big **"Run Morning Report Now"** button
   (or Afternoon — whichever applies right now).
3. The app switches to the **Console Output** tab at the bottom.
   Text will scroll by as the report runs — that's the report working.
   - Green lines = good
   - Yellow lines = minor warnings, usually fine
   - Red lines = something went wrong
4. When it says **"finished (exit code 0)"** in green, it worked, and an
   Outlook email opens with the report attached, ready to review and send.
5. Click **📁 Open Reports Folder** in the sidebar to see the saved PDFs.

That's it. Day to day, you only ever repeat Step 4 — or nothing at all,
if you turned on the scheduler.

Need to change your password or the save folder later? Open the app and
click **⚙ Options** in the sidebar.

Want to know everything the app can do? Click **📖 User Guide** in the
sidebar — the full guide opens right inside the app.

---

## If something goes wrong

**"Python was not found" in the black setup window**
→ Step 1 didn't finish, or the PATH box wasn't ticked. Run the Python
installer again, tick **"Add Python to PATH"**, then run `setup` again.

**Double-clicking the Desktop icon does nothing**
→ Wait 10 seconds first (first launch is slow). Still nothing? Restart
your computer once — Windows sometimes needs it after installing Python.

**Red lines in the Console / "ended with exit code 1"**
→ The most common cause is a wrong username or password. Re-check them
in **⚙ Options**. If they're right, take a screenshot of the red lines
and send it to whoever gave you this app.

**"password could not be decrypted" in red**
→ This copy of the app came from another computer or Windows account.
Your saved password is locked to the computer it was typed on — just
re-enter it in **⚙ Options** (or run `setup` again) and it's fixed.

**The report runs but no email window opens**
→ Make sure Outlook (the desktop app) is installed and the two `.oft`
template files from Step 2.4 are in the app folder.

**A report is stuck and won't finish**
→ Go to the **Console Output** tab and click the red **⏹ Stop** button.
Then just run it again.

**Anything else**
→ Screenshot the window (including the Console tab) and send it to
whoever gave you this app. The colored text at the bottom usually tells
us exactly what happened.
