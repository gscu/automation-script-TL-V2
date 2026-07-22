import ast
import os
import re
import shutil
import subprocess
import sys
import threading
import queue
from pathlib import Path
from datetime import datetime

import customtkinter as ctk
from tkinter import messagebox

# Password encryption helpers (Windows DPAPI). The stored value inside the
# report scripts is "ENC:<base64>"; see credential_store.py.
try:
    from credential_store import protect, try_reveal, dpapi_available
except ImportError:
    def protect(value):
        return value

    def try_reveal(value):
        return "" if value.startswith("ENC:") else value

    def dpapi_available():
        return False

# Shared interface list/bandwidth config (see interfaces_config.py). The
# Interfaces editor reads/writes it; the report scripts read it at startup.
try:
    import interfaces_config
except ImportError:
    interfaces_config = None


def format_bandwidth_value(value) -> str:
    """Render a Gbps override without trailing '.0' clutter (10.0 -> '10')."""
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number)


# ============================================================
# Basic configuration
# ============================================================

APP_NAME = "Bandwidth Report Manager"
APP_VERSION = "1.3.0"

SCRIPT_DIR = Path(__file__).resolve().parent

# When frozen by PyInstaller, __file__ lives inside the bundle; the icon is
# shipped next to the .exe, so resolve it from there instead.
if getattr(sys, "frozen", False):
    ICON_FILE = Path(sys.executable).resolve().parent / "bw.ico"
else:
    ICON_FILE = SCRIPT_DIR / "bw.ico"

# Default window size — chosen to fit common laptop screens (incl. 1080p at
# 125-150% scaling). The layout scales from here; see _capture_baseline.
BASE_WIDTH = 1160
BASE_HEIGHT = 760

MORNING_SCRIPT = SCRIPT_DIR / "Morning BW Reports.py"
AFTERNOON_SCRIPT = SCRIPT_DIR / "Afternoon BW Reports.py"

MORNING_BAT = SCRIPT_DIR / "Task Morning BW Reports.bat"
AFTERNOON_BAT = SCRIPT_DIR / "Task Afternoon BW Reports.bat"

MORNING_TASK_NAME = "Bandwidth Morning Reports"
AFTERNOON_TASK_NAME = "Bandwidth Afternoon Reports"

DEFAULT_REPORTS_FOLDER = SCRIPT_DIR / "reports"

USER_GUIDE_FILE = SCRIPT_DIR / "USER_GUIDE.md"

# Keeps schtasks / taskkill from flashing console windows, especially when
# the manager is packaged as a windowed .exe.
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# ============================================================
# Palette
# ============================================================
# Each color is a (light, dark) pair so the whole UI follows the appearance
# toggle. customtkinter widgets accept the tuple directly and pick the right
# side for the current mode; for raw Tk bits (text-widget tags) use pick().
# Status colors keep their meaning-color in both themes, tuned for contrast
# on that theme's surfaces.

OK = ("#059669", "#34D399")        # success green
WARN = ("#B45309", "#FBBF24")      # warning amber
DANGER = ("#DC2626", "#F87171")    # error red

BG = ("#EEF2F7", "#0B1120")        # main background
CARD = ("#FFFFFF", "#111827")      # raised card surface
WELL = ("#E9EEF5", "#0F172A")      # sunken well (tables, panes)
CONSOLE_BG = ("#F4F7FB", "#060B15")  # console well
CONSOLE_TEXT = ("#1E293B", "#CDDBEA")  # default console text
LINE = ("#D3DAE6", "#1F2937")      # subtle border line

ACCENT = ("#2563EB", "#1D4ED8")
ACCENT_HOVER = ("#1D4ED8", "#2563EB")
ACCENT_LIGHT = ("#2563EB", "#3B82F6")

INK = ("#0F172A", "#E5E7EB")       # primary text
MUTED = ("#64748B", "#9CA3AF")     # secondary text
FAINT = ("#94A3B8", "#6B7280")     # tertiary text
SOFT = ("#334155", "#CBD5E1")      # soft body text

# Buttons keep white text, so their light-mode fills stay dark enough to read.
GRAY_BTN = ("#64748B", "#374151")
GRAY_BTN_HOVER = ("#475569", "#4B5563")
RED_BTN = ("#B91C1C", "#7F1D1D")
RED_BTN_HOVER = ("#991B1B", "#991B1B")


def pick(color):
    """Resolve a (light, dark) pair to the single hex for the current mode.
    Used for raw Tk APIs (text-widget tag colors) that don't accept tuples."""
    if isinstance(color, tuple):
        return color[0] if ctk.get_appearance_mode() == "Light" else color[1]
    return color


def classify_log_line(message: str) -> str:
    """Pick a text tag for a log/console line so status reads at a glance:
    green = success, amber = warning/fallback, red = error, else neutral."""
    low = message.lower()
    if any(w in low for w in ("error", "failed", "failure", "could not",
                              "traceback", "exception", "denied", "not found")):
        return "err"
    if any(w in low for w in ("warn", "retry", "retrying", "falling back",
                              "skipped", "timed out", "timeout", "unavailable")):
        return "warn"
    if any(w in low for w in ("done", "saved", "success", "finished",
                              "downloaded", "complete", "launched", "enabled",
                              "ready")):
        return "ok"
    return "info"


# ============================================================
# Helper functions
# ============================================================

def find_python() -> str | None:
    """
    Locate a real Python interpreter for launching the report scripts.
    Running from source this is simply sys.executable; in a frozen
    (PyInstaller) build sys.executable is this app itself, so search PATH.
    """
    if not getattr(sys, "frozen", False):
        return sys.executable

    for name in ("python.exe", "python", "py.exe", "py"):
        found = shutil.which(name)
        if found:
            return found

    return None


def parse_reports_folder_from_script(script_path: Path) -> Path:
    """
    Attempts to read REPORTS_FOLDER from one of the report scripts.
    Falls back to ./reports if it cannot find a patched value.
    """
    try:
        if not script_path.exists():
            return DEFAULT_REPORTS_FOLDER

        content = script_path.read_text(encoding="utf-8")
        match = re.search(r'REPORTS_FOLDER\s*=\s*(r?["\'].*?["\'])', content)

        if not match:
            return DEFAULT_REPORTS_FOLDER

        token = match.group(1)

        # The patcher writes a repr() literal, so literal_eval round-trips
        # escaped backslashes correctly. Fall back to the raw text between
        # the quotes for hand-edited values.
        try:
            raw_path = str(ast.literal_eval(token)).strip()
        except (ValueError, SyntaxError):
            inner = re.match(r'r?["\'](.*)["\']$', token, flags=re.S)
            raw_path = inner.group(1).strip() if inner else ""

        if not raw_path:
            return DEFAULT_REPORTS_FOLDER

        return Path(raw_path).expanduser()

    except Exception:
        return DEFAULT_REPORTS_FOLDER


def parse_credentials_from_script(script_path: Path) -> tuple[str, str]:
    """
    Reads EHEALTH_USERNAME and EHEALTH_PASSWORD from a report script.
    This matches the current project design where setup patches credentials
    directly into Morning/Afternoon report scripts.
    """
    try:
        if not script_path.exists():
            return "", ""

        content = script_path.read_text(encoding="utf-8")

        username_match = re.search(r'EHEALTH_USERNAME\s*=\s*r?["\'](.*?)["\']', content, flags=re.IGNORECASE)
        password_match = re.search(r'EHEALTH_PASSWORD\s*=\s*r?["\'](.*?)["\']', content, flags=re.IGNORECASE)

        username = username_match.group(1) if username_match else ""
        password = password_match.group(1) if password_match else ""

        return username, password

    except Exception:
        return "", ""


def patch_credentials_in_script(script_path: Path, username: str, password: str) -> tuple[bool, str]:
    """
    Updates EHEALTH_USERNAME and EHEALTH_PASSWORD inside a report script.
    """
    if not script_path.exists():
        return False, f"Script not found: {script_path.name}"

    try:
        content = script_path.read_text(encoding="utf-8")

        content, username_replacements = re.subn(
            r'(EHEALTH_USERNAME\s*=\s*)["\'].*?["\']',
            lambda match: f'{match.group(1)}"{username}"',
            content,
            flags=re.IGNORECASE,
        )

        content, password_replacements = re.subn(
            r'(EHEALTH_PASSWORD\s*=\s*)["\'].*?["\']',
            lambda match: f'{match.group(1)}"{password}"',
            content,
            flags=re.IGNORECASE,
        )

        if username_replacements == 0:
            return False, f"Could not find EHEALTH_USERNAME in {script_path.name}"

        if password_replacements == 0:
            return False, f"Could not find EHEALTH_PASSWORD in {script_path.name}"

        script_path.write_text(content, encoding="utf-8")
        return True, f"Credentials updated in {script_path.name}"

    except Exception as error:
        return False, f"Failed to update {script_path.name}: {error}"


def update_all_report_credentials(username: str, password: str) -> tuple[bool, str]:
    """
    Updates credentials in both Morning and Afternoon report scripts.
    """
    messages = []

    for script_path in [MORNING_SCRIPT, AFTERNOON_SCRIPT]:
        success, message = patch_credentials_in_script(script_path, username, password)
        messages.append(message)

        if not success:
            return False, "\n".join(messages)

    return True, "\n".join(messages)


def patch_reports_folder_in_script(script_path: Path, reports_folder: Path) -> tuple[bool, str]:
    """
    Updates REPORTS_FOLDER inside a report script.
    """
    if not script_path.exists():
        return False, f"Script not found: {script_path.name}"

    try:
        content = script_path.read_text(encoding="utf-8")

        content, replacements = re.subn(
            r'REPORTS_FOLDER\s*=\s*r?["\'].*?["\']',
            lambda match: f'REPORTS_FOLDER = {repr(str(reports_folder))}',
            content,
            flags=re.IGNORECASE,
        )

        if replacements == 0:
            return False, f"Could not find REPORTS_FOLDER in {script_path.name}"

        script_path.write_text(content, encoding="utf-8")
        return True, f"Reports folder updated in {script_path.name}"

    except Exception as error:
        return False, f"Failed to update {script_path.name}: {error}"


def update_all_report_folders(reports_folder: Path) -> tuple[bool, str]:
    messages = []

    for script_path in [MORNING_SCRIPT, AFTERNOON_SCRIPT]:
        success, message = patch_reports_folder_in_script(script_path, reports_folder)
        messages.append(message)

        if not success:
            return False, "\n".join(messages)

    return True, "\n".join(messages)


def run_command(command, cwd=None):
    """
    Runs a command and returns (success, output_text).
    """
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            shell=False,
            creationflags=NO_WINDOW,
        )

        output = ""
        if result.stdout:
            output += result.stdout.strip()
        if result.stderr:
            if output:
                output += "\n"
            output += result.stderr.strip()

        return result.returncode == 0, output

    except Exception as error:
        return False, str(error)


def get_task_status(task_name: str) -> dict:
    """
    Queries Windows Task Scheduler for a task.
    Returns a dictionary with basic status fields.
    """
    command = [
        "schtasks",
        "/Query",
        "/TN",
        task_name,
        "/FO",
        "LIST",
        "/V",
    ]

    success, output = run_command(command)

    if not success:
        return {
            "exists": False,
            "enabled": False,
            "status": "Not found",
            "next_run": "N/A",
            "last_run": "N/A",
            "last_result": "N/A",
            "raw": output,
        }

    info = {
        "exists": True,
        "enabled": True,
        "status": "Unknown",
        "next_run": "N/A",
        "last_run": "N/A",
        "last_result": "N/A",
        "raw": output,
    }

    for line in output.splitlines():
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "status":
            info["status"] = value
        elif key == "next run time":
            info["next_run"] = value
        elif key == "last run time":
            info["last_run"] = value
        elif key == "last result":
            info["last_result"] = value
        elif key == "scheduled task state":
            info["enabled"] = value.lower() == "enabled"

    return info


def set_task_enabled(task_name: str, enabled: bool):
    command = [
        "schtasks",
        "/Change",
        "/TN",
        task_name,
        "/ENABLE" if enabled else "/DISABLE",
    ]
    return run_command(command)


def kill_process_tree(pid: int):
    """Kills a process and all of its children (cmd.exe -> python, etc.)."""
    return run_command(["taskkill", "/PID", str(pid), "/T", "/F"])


def open_path(path: Path):
    path.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# ============================================================
# GUI application
# ============================================================

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class BandwidthReportManager(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"{APP_NAME}  v{APP_VERSION}")
        self.geometry(f"{BASE_WIDTH}x{BASE_HEIGHT}")
        # Floor keeps the console from being squeezed out; the layout scales
        # to match the window between here and any larger size.
        self.minsize(880, 640)
        self.configure(fg_color=BG)

        self.reports_folder = parse_reports_folder_from_script(MORNING_SCRIPT)

        # Console runner state. Background threads never touch widgets:
        # they push (kind, text) tuples onto console_q and the Tk after()
        # loop drains them on the main thread (FortiAnalyzer pattern).
        self.console_q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.active_process: subprocess.Popen | None = None
        self.active_label: str | None = None
        self._refresh_in_flight = False

        # Responsive scaling state (see _on_resize / _apply_scale).
        self._scale_job = None
        self._applied_scale = 1.0
        self._base_px = None  # window size (physical px) that maps to scale 1.0

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_area()
        self.refresh_task_status()
        self.log("Application started.")

        self.apply_icon(self)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        # Capture the startup size as the "scale = 1.0" reference once the
        # window has settled, then start reacting to resizes.
        self.after(250, self._capture_baseline)
        self.bind("<Configure>", self._on_resize)
        self.after(120, self.drain_console_queue)

    # --------------------------------------------------------
    # Window icon + responsive scaling
    # --------------------------------------------------------

    def apply_icon(self, window):
        """Sets the taskbar/title-bar icon on a window. customtkinter sets its
        own icon shortly after a window is created, so we re-apply on a small
        delay to win that race. No-op if the .ico is missing or on non-Windows."""
        if os.name != "nt" or not ICON_FILE.exists():
            return

        def _set():
            try:
                window.iconbitmap(str(ICON_FILE))
            except Exception:
                pass

        _set()
        window.after(300, _set)

    def _capture_baseline(self):
        """Record the startup window size as the scale=1.0 reference. We scale
        by the RATIO to this size rather than an absolute pixel target, which
        cancels out customtkinter's DPI factor (baked equally into the baseline
        and every later measurement) — so the UI never double-scales on
        high-DPI displays, and stays at its designed size until actually
        resized."""
        width = self.winfo_width()
        height = self.winfo_height()
        if width > 1 and height > 1:
            self._base_px = (width, height)

    def _on_resize(self, event):
        """Debounced: only the root window's own resize events matter."""
        if event.widget is not self:
            return
        if self._scale_job is not None:
            self.after_cancel(self._scale_job)
        self._scale_job = self.after(140, self._apply_scale)

    def _apply_scale(self):
        self._scale_job = None
        if self._base_px is None:
            self._capture_baseline()
            return

        width = self.winfo_width()
        height = self.winfo_height()
        if width <= 1 or height <= 1:
            return

        base_w, base_h = self._base_px

        # Scale by whichever dimension grew/shrank less, so text never outgrows
        # the window. Clamped to a sane range.
        scale = min(width / base_w, height / base_h)
        scale = max(0.70, min(1.60, scale))

        # Ignore tiny deltas; this also breaks any feedback loop with the
        # relayout that set_widget_scaling triggers.
        if abs(scale - self._applied_scale) < 0.03:
            return

        self._applied_scale = scale
        ctk.set_widget_scaling(scale)

    def on_appearance_change(self, choice):
        """Light/Dark toggle. customtkinter re-resolves every (light, dark)
        color pair automatically; only the raw Tk console tags need a nudge."""
        mode = "light" if "Light" in choice else "dark"
        ctk.set_appearance_mode(mode)
        self.apply_console_theme()
        self.log(f"Switched to {mode} mode.")

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    def build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color=CARD)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_frame.pack(fill="x", padx=22, pady=(28, 20))

        logo = ctk.CTkLabel(
            brand_frame,
            text="▮▮▮",
            font=ctk.CTkFont(size=34, weight="bold"),
            text_color=ACCENT_LIGHT,
        )
        logo.pack(anchor="w")

        title = ctk.CTkLabel(
            brand_frame,
            text="BW Reports",
            font=ctk.CTkFont(size=25, weight="bold"),
        )
        title.pack(anchor="w", pady=(8, 0))

        subtitle = ctk.CTkLabel(
            brand_frame,
            text="Report Control Panel",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        subtitle.pack(anchor="w")

        divider = ctk.CTkFrame(self.sidebar, height=1, fg_color=LINE)
        divider.pack(fill="x", padx=22, pady=(0, 14))

        self.btn_morning = self.sidebar_button("▶  Run Morning Report", self.run_morning_report)
        self.btn_afternoon = self.sidebar_button("▶  Run Afternoon Report", self.run_afternoon_report)
        self.btn_folder = self.sidebar_button("📁  Open Reports Folder", self.open_reports_folder)
        self.btn_refresh = self.sidebar_button("🔄  Refresh Scheduler", self.refresh_task_status)
        self.btn_interfaces = self.sidebar_button("🖧  Interfaces", self.open_interfaces_window, color="gray")
        self.btn_options = self.sidebar_button("⚙  Options", self.open_options_window, color="gray")
        self.btn_guide = self.sidebar_button("📖  User Guide", self.open_help_window, color="gray")
        self.btn_exit = self.sidebar_button("⎋  Exit", self.on_close, color="red")

        # Bottom cluster (packed bottom-up: version lowest, toggle above it).
        bottom_label = ctk.CTkLabel(
            self.sidebar,
            text=f"Version {APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=FAINT,
        )
        bottom_label.pack(side="bottom", anchor="w", padx=24, pady=(6, 18))

        self.appearance_seg = ctk.CTkSegmentedButton(
            self.sidebar,
            values=["☀ Light", "🌙 Dark"],
            command=self.on_appearance_change,
            font=ctk.CTkFont(size=13, weight="bold"),
            selected_color=ACCENT,
            selected_hover_color=ACCENT_HOVER,
            unselected_color=WELL,
            unselected_hover_color=GRAY_BTN,
        )
        self.appearance_seg.set("🌙 Dark")
        self.appearance_seg.pack(side="bottom", fill="x", padx=22, pady=(0, 8))

        appearance_caption = ctk.CTkLabel(
            self.sidebar,
            text="Appearance",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        appearance_caption.pack(side="bottom", anchor="w", padx=24, pady=(10, 2))

    def sidebar_button(self, text, command, color="blue"):
        if color == "red":
            fg_color = RED_BTN
            hover_color = RED_BTN_HOVER
        elif color == "gray":
            fg_color = GRAY_BTN
            hover_color = GRAY_BTN_HOVER
        else:
            fg_color = ACCENT
            hover_color = ACCENT_HOVER

        button = ctk.CTkButton(
            self.sidebar,
            text=text,
            command=command,
            height=44,
            corner_radius=10,
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=fg_color,
            hover_color=hover_color,
        )
        button.pack(fill="x", padx=22, pady=6)
        return button

    def build_main_area(self):
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color=BG)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        # The console (row 3) takes all spare vertical space.
        self.main.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(16, 6))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text=APP_NAME,
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        description = ctk.CTkLabel(
            header,
            text="Generate reports, open output folders, and manage scheduled automation.",
            font=ctk.CTkFont(size=15),
            text_color=SOFT,
        )
        description.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.action_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color=CARD)
        self.action_frame.grid(row=1, column=0, sticky="ew", padx=28, pady=(4, 8))
        self.action_frame.grid_columnconfigure((0, 1), weight=1)

        self.action_morning = self.action_button(
            self.action_frame,
            0,
            "▶",
            "Run Morning Report Now",
            "Launch the morning bandwidth report script.",
            self.run_morning_report,
        )
        self.action_afternoon = self.action_button(
            self.action_frame,
            1,
            "▶",
            "Run Afternoon Report Now",
            "Launch the afternoon bandwidth report script.",
            self.run_afternoon_report,
        )

        self.detached_var = ctk.BooleanVar(value=False)
        detached_check = ctk.CTkCheckBox(
            self.action_frame,
            text="Open reports in a separate console window (instead of the Console below)",
            variable=self.detached_var,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            checkbox_width=18,
            checkbox_height=18,
        )
        detached_check.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 10))

        self.scheduler_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color=CARD)
        self.scheduler_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 8))
        self.scheduler_frame.grid_columnconfigure(0, weight=1)

        scheduler_title = ctk.CTkLabel(
            self.scheduler_frame,
            text="Task Scheduler",
            font=ctk.CTkFont(size=19, weight="bold"),
        )
        scheduler_title.grid(row=0, column=0, sticky="w", padx=20, pady=(12, 0))

        # At-a-glance summary that the removed status cards used to carry.
        self.scheduler_summary = ctk.CTkLabel(
            self.scheduler_frame,
            text="●  Checking…",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=MUTED,
        )
        self.scheduler_summary.grid(row=0, column=1, sticky="e", padx=20, pady=(12, 0))

        self.task_table = ctk.CTkFrame(self.scheduler_frame, fg_color=WELL, corner_radius=10)
        self.task_table.grid(row=1, column=0, columnspan=2, sticky="ew", padx=20, pady=(8, 14))
        self.task_table.grid_columnconfigure(0, weight=2)
        self.task_table.grid_columnconfigure(1, weight=2)
        self.task_table.grid_columnconfigure(2, weight=2)
        self.task_table.grid_columnconfigure(3, weight=2)
        self.task_table.grid_columnconfigure(4, weight=1)

        self.build_task_table_header()
        self.build_task_rows()

        self.build_console_panel()

    def build_console_panel(self):
        """Always-visible console on the main page (FortiAnalyzer style):
        one color-coded pane showing app activity AND the live stdout/stderr
        of report runs — no tabs, no clicking around to find the output."""
        panel = ctk.CTkFrame(self.main, corner_radius=14, fg_color=CARD)
        panel.grid(row=3, column=0, sticky="nsew", padx=28, pady=(0, 20))
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))
        header.grid_columnconfigure(1, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Console",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        self.console_status = ctk.CTkLabel(
            header,
            text="●  Idle",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=FAINT,
            anchor="w",
        )
        self.console_status.grid(row=0, column=1, sticky="w", padx=(14, 0))

        self.stop_button = ctk.CTkButton(
            header,
            text="⏹  Stop",
            width=92,
            height=30,
            state="disabled",
            fg_color=RED_BTN,
            hover_color=RED_BTN_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.stop_report,
        )
        self.stop_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

        clear_console_button = ctk.CTkButton(
            header,
            text="Clear",
            width=72,
            height=30,
            fg_color=GRAY_BTN,
            hover_color=GRAY_BTN_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.clear_console,
        )
        clear_console_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

        subtitle = ctk.CTkLabel(
            panel,
            text="Live app activity and report output (bandwidth readings, alerts, errors).",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            anchor="w",
        )
        subtitle.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 4))

        self.console_box = ctk.CTkTextbox(
            panel,
            corner_radius=10,
            fg_color=CONSOLE_BG,
            text_color=CONSOLE_TEXT,
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.console_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(2, 12))
        self.console_box.configure(state="disabled")
        self.apply_console_theme()

    def apply_console_theme(self):
        """(Re)apply the console text-tag colors for the current appearance
        mode. Tk tag colors are raw hex, so they need re-picking on a toggle."""
        for tag, color in (("err", DANGER), ("warn", WARN), ("ok", OK),
                           ("info", CONSOLE_TEXT), ("sys", ACCENT_LIGHT)):
            self.console_box.tag_config(tag, foreground=pick(color))

    def action_button(self, parent, column, icon, title, subtitle, command):
        frame = ctk.CTkButton(
            parent,
            command=command,
            height=66,
            corner_radius=12,
            text=f"{icon}   {title}\n{subtitle}",
            font=ctk.CTkFont(size=15, weight="bold"),
            anchor="w",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        frame.grid(row=0, column=column, sticky="ew", padx=14, pady=(14, 8))
        return frame

    def build_task_table_header(self):
        headers = ["Task Name", "Status", "Next Run", "Last Result", "Enabled"]
        for col, text in enumerate(headers):
            label = ctk.CTkLabel(
                self.task_table,
                text=text,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color=SOFT,
            )
            label.grid(row=0, column=col, sticky="w", padx=14, pady=(10, 6))

    def build_task_rows(self):
        self.morning_task_labels = self.create_task_row(1, "Morning Task", MORNING_TASK_NAME)
        self.afternoon_task_labels = self.create_task_row(2, "Afternoon Task", AFTERNOON_TASK_NAME)

    def create_task_row(self, row, display_name, task_name):
        name = ctk.CTkLabel(self.task_table, text=display_name, font=ctk.CTkFont(size=14))
        name.grid(row=row, column=0, sticky="w", padx=14, pady=5)

        status = ctk.CTkLabel(self.task_table, text="Unknown", font=ctk.CTkFont(size=14))
        status.grid(row=row, column=1, sticky="w", padx=14, pady=5)

        next_run = ctk.CTkLabel(self.task_table, text="N/A", font=ctk.CTkFont(size=14))
        next_run.grid(row=row, column=2, sticky="w", padx=14, pady=5)

        last_result = ctk.CTkLabel(self.task_table, text="N/A", font=ctk.CTkFont(size=14))
        last_result.grid(row=row, column=3, sticky="w", padx=14, pady=5)

        switch = ctk.CTkSwitch(
            self.task_table,
            text="",
            progress_color=ACCENT,
            command=lambda: self.toggle_task(task_name, switch),
        )
        switch.grid(row=row, column=4, sticky="w", padx=14, pady=5)

        return {
            "status": status,
            "next_run": next_run,
            "last_result": last_result,
            "switch": switch,
        }

    # --------------------------------------------------------
    # Console (single main-page pane — app activity + report output)
    # log() writes timestamped app events; console_emit() writes raw
    # report stdout/stderr. Both land in the same box. The reader thread
    # never touches Tk — it feeds console_q, drained on the main thread.
    # --------------------------------------------------------

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = classify_log_line(message)
        self.console_box.configure(state="normal")
        self.console_box.insert("end", f"[{timestamp}] {message}\n", tag)
        self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def console_emit(self, text: str, kind: str = "auto"):
        tag = classify_log_line(text) if kind == "auto" else kind
        self.console_box.configure(state="normal")
        self.console_box.insert("end", text.rstrip("\n") + "\n", tag)
        self.console_box.see("end")
        self.console_box.configure(state="disabled")

    def clear_console(self):
        self.console_box.configure(state="normal")
        self.console_box.delete("1.0", "end")
        self.console_box.configure(state="disabled")
        self.log("Console cleared.")

    def drain_console_queue(self):
        try:
            for _ in range(500):
                kind, text = self.console_q.get_nowait()
                if kind == "exit":
                    self.finish_captured_run(text)
                else:
                    self.console_emit(text, kind)
        except queue.Empty:
            pass
        self.after(120, self.drain_console_queue)

    def set_console_running(self, label: str):
        self.active_label = label
        self.console_status.configure(text=f"●  Running — {label}", text_color=WARN)
        self.stop_button.configure(state="normal")
        for button in (self.btn_morning, self.btn_afternoon,
                       self.action_morning, self.action_afternoon):
            button.configure(state="disabled")

    def set_console_idle(self, text="●  Idle", color=FAINT):
        self.console_status.configure(text=text, text_color=color)
        self.stop_button.configure(state="disabled")
        for button in (self.btn_morning, self.btn_afternoon,
                       self.action_morning, self.action_afternoon):
            button.configure(state="normal")

    # --------------------------------------------------------
    # Script launching
    # --------------------------------------------------------

    def run_morning_report(self):
        self.launch_report(MORNING_BAT, MORNING_SCRIPT, "Morning report")

    def run_afternoon_report(self):
        self.launch_report(AFTERNOON_BAT, AFTERNOON_SCRIPT, "Afternoon report")

    def launch_report(self, bat_path: Path, script_path: Path, label: str):
        if self.detached_var.get():
            self.launch_detached(bat_path, script_path, label)
        else:
            self.launch_captured(bat_path, script_path, label)

    def launch_detached(self, bat_path: Path, script_path: Path, label: str):
        """Original behavior: pop a separate console window."""
        try:
            python = find_python()

            if bat_path.exists():
                command = ["cmd.exe", "/c", str(bat_path)]
                launch_target = bat_path.name
            elif script_path.exists() and python:
                command = [python, str(script_path)]
                launch_target = script_path.name
            else:
                self.log(f"ERROR: {label} file was not found.")
                return

            self.log(f"Launching {label}: {launch_target}")

            subprocess.Popen(
                command,
                cwd=str(SCRIPT_DIR),
                creationflags=subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0,
            )

            self.log(f"{label} launched in a separate console window.")

        except Exception as error:
            self.log(f"ERROR launching {label}: {error}")

    def launch_captured(self, bat_path: Path, script_path: Path, label: str):
        """Runs the report with stdout/stderr streamed into the Console tab."""
        if self.active_process is not None and self.active_process.poll() is None:
            self.log("A report is already running — wait for it to finish or press Stop.")
            return

        python = find_python()

        # Prefer the .py directly (clean unbuffered streaming); fall back to
        # the .bat wrapper. stdin is closed so a trailing `pause` cannot hang.
        if script_path.exists() and python:
            command = [python, "-u", str(script_path)]
            launch_target = script_path.name
        elif bat_path.exists():
            command = ["cmd.exe", "/c", str(bat_path)]
            launch_target = bat_path.name
        else:
            self.log(f"ERROR: {label} file was not found.")
            if python is None:
                self.log("ERROR: No Python interpreter found on PATH either.")
            return

        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")

        try:
            process = subprocess.Popen(
                command,
                cwd=str(SCRIPT_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
                creationflags=NO_WINDOW,
            )
        except Exception as error:
            self.log(f"ERROR launching {label}: {error}")
            return

        self.active_process = process
        self.set_console_running(label)
        self.log(f"Launching {label}: {launch_target} (output below)")

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.console_emit(f"── [{timestamp}] {label}: {' '.join(command)} ──", "sys")

        reader = threading.Thread(
            target=self.pump_process_output,
            args=(process, label),
            daemon=True,
        )
        reader.start()

    def pump_process_output(self, process: subprocess.Popen, label: str):
        """Background thread: stream child output into the console queue."""
        try:
            for line in process.stdout:
                self.console_q.put(("auto", line))
        except Exception as error:
            self.console_q.put(("err", f"[reader error] {error}"))
        finally:
            code = process.wait()
            self.console_q.put(("exit", str(code)))

    def finish_captured_run(self, code_text: str):
        """Main thread: a captured run ended (sentinel from the queue)."""
        label = self.active_label or "Report"
        code = int(code_text) if code_text.lstrip("-").isdigit() else -1
        timestamp = datetime.now().strftime("%H:%M:%S")

        if code == 0:
            self.console_emit(f"── [{timestamp}] {label} finished (exit code 0) ──", "ok")
            self.set_console_idle(f"●  Finished — {label} (exit code 0)", OK)
            self.log(f"{label} finished successfully.")
        else:
            self.console_emit(f"── [{timestamp}] {label} ended with exit code {code} ──", "err")
            self.set_console_idle(f"●  Ended — {label} (exit code {code})", DANGER)
            self.log(f"ERROR: {label} ended with exit code {code}.")

        self.active_process = None
        self.active_label = None

    def stop_report(self):
        process = self.active_process
        if process is None or process.poll() is not None:
            return

        label = self.active_label or "Report"
        self.console_emit(f"Stopping {label}…", "warn")
        success, output = kill_process_tree(process.pid)

        if not success:
            self.console_emit(f"Could not stop process tree: {output}", "err")
        # The reader thread sees the pipe close and posts the exit sentinel.

    # --------------------------------------------------------
    # Options window
    # --------------------------------------------------------

    def open_options_window(self):
        username, password = parse_credentials_from_script(MORNING_SCRIPT)
        # Decrypt the stored password for pre-fill; comes back empty if it
        # was saved on a different machine/user account.
        password = try_reveal(password)

        window = ctk.CTkToplevel(self, fg_color=BG)
        window.title("Options")
        window.geometry("620x560")
        window.minsize(560, 520)
        window.transient(self)
        window.after(120, window.grab_set)
        window.focus()
        self.apply_icon(window)

        window.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            window,
            text="Options",
            font=ctk.CTkFont(size=28, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w", padx=28, pady=(26, 4))

        subtitle = ctk.CTkLabel(
            window,
            text="Update credentials and report folder settings used by the report scripts.",
            font=ctk.CTkFont(size=14),
            text_color=SOFT,
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        credentials_card = ctk.CTkFrame(window, corner_radius=14, fg_color=CARD)
        credentials_card.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 16))
        credentials_card.grid_columnconfigure(1, weight=1)

        credentials_title = ctk.CTkLabel(
            credentials_card,
            text="eHealth Credentials",
            font=ctk.CTkFont(size=19, weight="bold"),
        )
        credentials_title.grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 12))

        username_label = ctk.CTkLabel(credentials_card, text="Username:", font=ctk.CTkFont(size=14))
        username_label.grid(row=1, column=0, sticky="w", padx=20, pady=8)

        username_entry = ctk.CTkEntry(credentials_card, width=340)
        username_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(6, 20), pady=8)
        username_entry.insert(0, username)

        password_label = ctk.CTkLabel(credentials_card, text="Password:", font=ctk.CTkFont(size=14))
        password_label.grid(row=2, column=0, sticky="w", padx=20, pady=8)

        password_entry = ctk.CTkEntry(credentials_card, width=340, show="*")
        password_entry.grid(row=2, column=1, sticky="ew", padx=(6, 8), pady=8)
        password_entry.insert(0, password)

        show_password_var = ctk.BooleanVar(value=False)

        def toggle_password_visibility():
            password_entry.configure(show="" if show_password_var.get() else "*")

        show_password = ctk.CTkCheckBox(
            credentials_card,
            text="Show",
            variable=show_password_var,
            command=toggle_password_visibility,
            width=70,
        )
        show_password.grid(row=2, column=2, sticky="w", padx=(0, 20), pady=8)

        # Encryption toggle. ON (recommended): password is DPAPI-encrypted for
        # this Windows user before being written into the report scripts.
        # OFF: stored as plain text — readable, but survives moving the folder
        # to another PC/user (re-encrypt it there afterwards).
        note_encrypted = (
            "Saved into both report scripts. The password is encrypted for this\n"
            "Windows user (DPAPI) before saving — no plain text in the files."
        )
        note_plaintext = (
            "Plain text: the password will be readable inside the report scripts.\n"
            "Only useful for a folder you'll move to another PC — re-encrypt there."
        )
        note_unavailable = (
            "Encryption unavailable (pywin32 not installed) — the password will\n"
            "be stored as plain text. Run setup.bat to install what's missing."
        )

        encrypt_password_var = ctk.BooleanVar(value=True)

        credentials_note = ctk.CTkLabel(
            credentials_card,
            text=note_encrypted,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            justify="left",
        )

        def on_encrypt_toggle():
            if encrypt_password_var.get():
                credentials_note.configure(text=note_encrypted, text_color=MUTED)
            else:
                credentials_note.configure(text=note_plaintext, text_color=WARN)

        encrypt_password = ctk.CTkCheckBox(
            credentials_card,
            text="Encrypt password when saving (recommended)",
            variable=encrypt_password_var,
            command=on_encrypt_toggle,
        )
        encrypt_password.grid(row=3, column=0, columnspan=3, sticky="w", padx=20, pady=(10, 0))

        if not dpapi_available():
            encrypt_password_var.set(False)
            encrypt_password.configure(state="disabled")
            credentials_note.configure(text=note_unavailable, text_color=WARN)

        credentials_note.grid(row=4, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 18))

        folder_card = ctk.CTkFrame(window, corner_radius=14, fg_color=CARD)
        folder_card.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 16))
        folder_card.grid_columnconfigure(1, weight=1)

        folder_title = ctk.CTkLabel(
            folder_card,
            text="Reports Folder",
            font=ctk.CTkFont(size=19, weight="bold"),
        )
        folder_title.grid(row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 12))

        folder_label = ctk.CTkLabel(folder_card, text="Folder:", font=ctk.CTkFont(size=14))
        folder_label.grid(row=1, column=0, sticky="w", padx=20, pady=8)

        folder_entry = ctk.CTkEntry(folder_card)
        folder_entry.grid(row=1, column=1, sticky="ew", padx=(6, 8), pady=8)
        folder_entry.insert(0, str(self.reports_folder))

        def browse_folder():
            from tkinter import filedialog

            selected = filedialog.askdirectory(initialdir=str(self.reports_folder))
            if selected:
                folder_entry.delete(0, "end")
                folder_entry.insert(0, selected)

        browse_button = ctk.CTkButton(
            folder_card,
            text="Browse...",
            width=90,
            command=browse_folder,
        )
        browse_button.grid(row=1, column=2, sticky="ew", padx=(0, 20), pady=8)

        folder_note = ctk.CTkLabel(
            folder_card,
            text="Changing this will patch REPORTS_FOLDER in both report scripts.",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        )
        folder_note.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 18))

        status_label = ctk.CTkLabel(
            window,
            text="",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
            wraplength=540,
            justify="left",
        )
        status_label.grid(row=4, column=0, sticky="ew", padx=28, pady=(0, 10))

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=5, column=0, sticky="ew", padx=28, pady=(4, 24))
        button_row.grid_columnconfigure(0, weight=1)

        def save_options():
            new_username = username_entry.get().strip()
            new_password = password_entry.get().strip()
            new_reports_folder_raw = folder_entry.get().strip()

            if not new_username or not new_password:
                status_label.configure(
                    text="Username and password are required.",
                    text_color=DANGER,
                )
                return

            if not new_reports_folder_raw:
                status_label.configure(
                    text="Reports folder cannot be blank.",
                    text_color=DANGER,
                )
                return

            new_reports_folder = Path(new_reports_folder_raw).expanduser()

            try:
                new_reports_folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                status_label.configure(
                    text=f"Could not create/use reports folder: {error}",
                    text_color=DANGER,
                )
                return

            # Encrypt before writing (unless the user opted for plain text)
            if encrypt_password_var.get():
                stored_password = protect(new_password)
            else:
                stored_password = new_password

            credentials_success, credentials_message = update_all_report_credentials(new_username, stored_password)
            if not credentials_success:
                status_label.configure(text=credentials_message, text_color=DANGER)
                self.log(f"ERROR updating credentials: {credentials_message}")
                return

            folder_success, folder_message = update_all_report_folders(new_reports_folder)
            if not folder_success:
                status_label.configure(text=folder_message, text_color=DANGER)
                self.log(f"ERROR updating reports folder: {folder_message}")
                return

            self.reports_folder = new_reports_folder
            status_label.configure(
                text="Options saved successfully.",
                text_color=OK,
            )
            self.log("Options updated successfully.")

        save_button = ctk.CTkButton(
            button_row,
            text="Save Options",
            command=save_options,
            width=160,
            height=40,
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        save_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        close_button = ctk.CTkButton(
            button_row,
            text="Close",
            command=window.destroy,
            width=120,
            height=40,
            fg_color=GRAY_BTN,
            hover_color=GRAY_BTN_HOVER,
        )
        close_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    # --------------------------------------------------------
    # User guide window
    # --------------------------------------------------------

    def open_help_window(self):
        """Shows USER_GUIDE.md inside the app, so users don't have to hunt
        for the file. Non-modal — it can stay open while reports run."""
        window = ctk.CTkToplevel(self, fg_color=BG)
        window.title("User Guide")
        window.geometry("820x680")
        window.minsize(640, 480)
        window.transient(self)
        window.focus()
        self.apply_icon(window)

        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        header = ctk.CTkLabel(
            window,
            text="📖  User Guide",
            font=ctk.CTkFont(size=24, weight="bold"),
        )
        header.grid(row=0, column=0, sticky="w", padx=24, pady=(20, 8))

        box = ctk.CTkTextbox(
            window,
            corner_radius=10,
            fg_color=WELL,
            wrap="word",
            font=ctk.CTkFont(size=13),
        )
        box.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))

        box.tag_config("h1", foreground=pick(ACCENT_LIGHT))
        box.tag_config("h2", foreground=pick(ACCENT_LIGHT))
        box.tag_config("dim", foreground=pick(FAINT))
        box.tag_config("body", foreground=pick(INK))
        # Heavier heading fonts via the underlying Tk widget where available;
        # the color tags above already carry the structure if this fails.
        try:
            box._textbox.tag_configure("h1", font=("Segoe UI", 19, "bold"))
            box._textbox.tag_configure("h2", font=("Segoe UI", 15, "bold"))
        except Exception:
            pass

        if USER_GUIDE_FILE.exists():
            raw = USER_GUIDE_FILE.read_text(encoding="utf-8")
        else:
            raw = (
                "# User guide not found\n\n"
                "USER_GUIDE.md should sit next to the app. Re-copy it from "
                "the original folder or repository."
            )

        for line in raw.splitlines():
            stripped = line.strip()
            text = line.replace("**", "").replace("`", "")
            if stripped.startswith("# "):
                box.insert("end", text.lstrip("# ") + "\n", "h1")
            elif stripped.startswith("## "):
                box.insert("end", "\n" + text.lstrip("# ") + "\n", "h2")
            elif stripped.startswith("---"):
                box.insert("end", "─" * 60 + "\n", "dim")
            elif stripped.startswith("|"):
                cells = [c.strip() for c in stripped.strip("|").split("|")]
                if all(set(c) <= {"-", " ", ":"} for c in cells):
                    continue  # markdown table separator row
                cells = [c.replace("**", "").replace("`", "") for c in cells if c]
                box.insert("end", "  •  " + "  —  ".join(cells) + "\n", "body")
            else:
                box.insert("end", text + "\n", "body")

        box.configure(state="disabled")

    # --------------------------------------------------------
    # Interfaces editor window
    # --------------------------------------------------------

    def open_interfaces_window(self):
        """Add / edit / delete the monitored interfaces and their optional
        bandwidth limits. Writes interfaces.json, which both report scripts
        read at startup."""
        if interfaces_config is None:
            self.log("ERROR: interfaces_config.py is missing — cannot edit interfaces.")
            messagebox.showerror(
                "Interfaces unavailable",
                "interfaces_config.py must sit next to the app to edit interfaces.",
                parent=self,
            )
            return

        window = ctk.CTkToplevel(self, fg_color=BG)
        window.title("Interfaces")
        window.geometry("900x660")
        window.minsize(740, 540)
        window.transient(self)
        window.after(150, window.grab_set)
        window.focus()
        self.apply_icon(window)
        self.iface_window = window

        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(3, weight=1)

        title = ctk.CTkLabel(window, text="Interfaces", font=ctk.CTkFont(size=28, weight="bold"))
        title.grid(row=0, column=0, sticky="w", padx=28, pady=(24, 2))

        subtitle = ctk.CTkLabel(
            window,
            text="Add, edit, or remove the monitored interfaces (MSUID). Bandwidth limit is in "
                 "Gbps —\nleave it blank to read the capacity from the report PDF. "
                 "“Skip low-BW alert” excludes an\ninterface from the "
                 "“dipped below 1 Mbps” check. Changes apply to the next report run.",
            font=ctk.CTkFont(size=13),
            text_color=SOFT,
            justify="left",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 12))

        self.iface_list = ctk.CTkScrollableFrame(window, fg_color=WELL, corner_radius=10)
        self.iface_list.grid(row=3, column=0, sticky="nsew", padx=28, pady=(0, 10))
        self.iface_list.grid_columnconfigure(0, weight=1)

        self._iface_rows = []
        for entry in interfaces_config.load():
            self._add_interface_row(entry)

        add_btn = ctk.CTkButton(
            window,
            text="＋  Add interface",
            command=lambda: self._add_interface_row(focus=True),
            height=36,
            fg_color=GRAY_BTN,
            hover_color=GRAY_BTN_HOVER,
        )
        add_btn.grid(row=4, column=0, sticky="w", padx=28, pady=(0, 6))

        self.iface_status = ctk.CTkLabel(
            window, text="", font=ctk.CTkFont(size=13), text_color=MUTED,
            wraplength=820, justify="left",
        )
        self.iface_status.grid(row=5, column=0, sticky="w", padx=28, pady=(0, 4))

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=6, column=0, sticky="ew", padx=28, pady=(0, 20))
        button_row.grid_columnconfigure(0, weight=1)

        restore_btn = ctk.CTkButton(
            button_row, text="Restore defaults", width=150,
            command=self._restore_default_interfaces,
            fg_color=GRAY_BTN, hover_color=GRAY_BTN_HOVER,
        )
        restore_btn.grid(row=0, column=0, sticky="w")

        save_btn = ctk.CTkButton(
            button_row, text="Save", width=140, command=self._save_interfaces,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
        )
        save_btn.grid(row=0, column=1, padx=(8, 0))

        close_btn = ctk.CTkButton(
            button_row, text="Close", width=110, command=window.destroy,
            fg_color=GRAY_BTN, hover_color=GRAY_BTN_HOVER,
        )
        close_btn.grid(row=0, column=2, padx=(8, 0))

    def _add_interface_row(self, entry=None, focus=False):
        entry = entry or {"name": "", "bandwidth_gbps": None, "exclude_dip": False}

        row = ctk.CTkFrame(self.iface_list, fg_color=CARD, corner_radius=8)
        row.pack(fill="x", padx=6, pady=4)
        row.grid_columnconfigure(0, weight=1)

        name_entry = ctk.CTkEntry(row, placeholder_text="EXAMPLE-GO...-TH-10GEth0/1*")
        name_entry.grid(row=0, column=0, sticky="ew", padx=(10, 8), pady=8)
        if entry.get("name"):
            name_entry.insert(0, entry["name"])

        bw_entry = ctk.CTkEntry(row, width=90, placeholder_text="auto")
        bw_entry.grid(row=0, column=1, padx=(8, 2), pady=8)
        if entry.get("bandwidth_gbps") is not None:
            bw_entry.insert(0, format_bandwidth_value(entry["bandwidth_gbps"]))

        gbps_label = ctk.CTkLabel(row, text="Gbps", font=ctk.CTkFont(size=12), text_color=MUTED)
        gbps_label.grid(row=0, column=2, padx=(0, 10), pady=8)

        excl_check = ctk.CTkCheckBox(row, text="Skip low-BW alert", font=ctk.CTkFont(size=12))
        excl_check.grid(row=0, column=3, padx=(4, 12), pady=8)
        if entry.get("exclude_dip"):
            excl_check.select()

        record = {"frame": row, "name": name_entry, "bw": bw_entry, "excl": excl_check}

        delete_btn = ctk.CTkButton(
            row, text="\U0001f5d1", width=42,
            fg_color=RED_BTN, hover_color=RED_BTN_HOVER,
            command=lambda: self._delete_interface_row(record),
        )
        delete_btn.grid(row=0, column=4, padx=(0, 10), pady=8)

        self._iface_rows.append(record)

        if focus:
            name_entry.focus()
            # Scroll the new row into view.
            self.iface_list.after(50, lambda: self.iface_list._parent_canvas.yview_moveto(1.0))
        return record

    def _delete_interface_row(self, record):
        label = record["name"].get().strip() or "this interface"
        if not messagebox.askyesno(
            "Delete interface",
            f"Delete “{label}” from the list?",
            parent=self.iface_window,
        ):
            return
        record["frame"].destroy()
        self._iface_rows.remove(record)

    def _collect_interface_rows(self) -> list:
        return [
            {
                "name": r["name"].get(),
                "bandwidth_gbps": r["bw"].get(),
                "exclude_dip": bool(r["excl"].get()),
            }
            for r in self._iface_rows
        ]

    def _save_interfaces(self):
        entries = self._collect_interface_rows()
        try:
            interfaces_config.save(entries)
        except OSError as error:
            self.iface_status.configure(text=f"Could not save: {error}", text_color=DANGER)
            self.log(f"ERROR saving interfaces: {error}")
            return

        saved = interfaces_config.load()
        dropped = len(entries) - len(saved)
        note = f"Saved {len(saved)} interface(s). Applies to the next report run."
        if dropped > 0:
            note += f"  ({dropped} blank/duplicate row(s) skipped.)"
        self.iface_status.configure(text=note, text_color=OK)
        self.log(f"Interfaces saved ({len(saved)}).")

    def _restore_default_interfaces(self):
        if not messagebox.askyesno(
            "Restore defaults",
            "Replace the current list with the built-in default interfaces?\n"
            "This is not saved until you press Save.",
            parent=self.iface_window,
        ):
            return
        for record in list(self._iface_rows):
            record["frame"].destroy()
        self._iface_rows.clear()
        for entry in interfaces_config.DEFAULT_INTERFACES:
            self._add_interface_row(dict(entry))
        self.iface_status.configure(
            text="Defaults restored — press Save to keep them.", text_color=WARN
        )

    # --------------------------------------------------------
    # Reports folder
    # --------------------------------------------------------

    def open_reports_folder(self):
        try:
            self.reports_folder.mkdir(parents=True, exist_ok=True)
            open_path(self.reports_folder)
            self.log(f"Opened reports folder: {self.reports_folder}")
        except Exception as error:
            self.log(f"ERROR opening reports folder: {error}")

    # --------------------------------------------------------
    # Scheduler controls
    # --------------------------------------------------------

    def refresh_task_status(self):
        """Queries Task Scheduler on a background thread so the two
        schtasks calls never freeze the UI, then applies on the main thread."""
        if self._refresh_in_flight:
            return

        self._refresh_in_flight = True
        self.scheduler_summary.configure(text="●  Checking…", text_color=MUTED)

        def worker():
            morning = get_task_status(MORNING_TASK_NAME)
            afternoon = get_task_status(AFTERNOON_TASK_NAME)
            self.after(0, lambda: self.apply_task_status(morning, afternoon))

        threading.Thread(target=worker, daemon=True).start()

    def apply_task_status(self, morning: dict, afternoon: dict):
        self._refresh_in_flight = False

        self.update_task_row(self.morning_task_labels, morning)
        self.update_task_row(self.afternoon_task_labels, afternoon)

        enabled_count = int(morning["enabled"]) + int(afternoon["enabled"])
        if enabled_count == 2:
            scheduler_color = OK
        elif enabled_count == 1:
            scheduler_color = WARN
        else:
            scheduler_color = DANGER

        self.scheduler_summary.configure(
            text=f"●  {enabled_count}/2 enabled · checked {datetime.now().strftime('%H:%M:%S')}",
            text_color=scheduler_color,
        )

        self.log("Scheduler status refreshed.")

    def update_task_row(self, row_labels, task_info):
        if not task_info["exists"]:
            row_labels["status"].configure(text="Not found", text_color=DANGER)
            row_labels["next_run"].configure(text="N/A")
            row_labels["last_result"].configure(text="N/A")
            row_labels["switch"].deselect()
            return

        status_text = task_info["status"]
        enabled = task_info["enabled"]

        row_labels["status"].configure(
            text=status_text,
            text_color=OK if enabled else WARN,
        )
        row_labels["next_run"].configure(text=task_info["next_run"])
        row_labels["last_result"].configure(text=task_info["last_result"])

        if enabled:
            row_labels["switch"].select()
        else:
            row_labels["switch"].deselect()

    def toggle_task(self, task_name: str, switch):
        enabled = bool(switch.get())
        success, output = set_task_enabled(task_name, enabled)

        if success:
            self.log(f"{'Enabled' if enabled else 'Disabled'} task: {task_name}")
        else:
            self.log(f"ERROR changing task state for {task_name}: {output}")

        self.refresh_task_status()

    # --------------------------------------------------------
    # Shutdown
    # --------------------------------------------------------

    def on_close(self):
        process = self.active_process
        if process is not None and process.poll() is None:
            label = self.active_label or "A report"
            if not messagebox.askyesno(
                "Report still running",
                f"{label} is still running in the console.\n\nStop it and exit?",
                parent=self,
            ):
                return
            kill_process_tree(process.pid)

        self.destroy()


if __name__ == "__main__":
    app = BandwidthReportManager()
    app.mainloop()
