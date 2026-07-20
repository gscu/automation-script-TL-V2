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


# ============================================================
# Basic configuration
# ============================================================

APP_NAME = "Bandwidth Report Manager"
APP_VERSION = "1.1.0"

SCRIPT_DIR = Path(__file__).resolve().parent

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
# Status colors are theme-invariant (same idea as the FortiAnalyzer app):
# a log line keeps its meaning-color no matter what surface it sits on.

OK = "#34D399"        # success green
WARN = "#FBBF24"      # warning amber
DANGER = "#F87171"    # error red

BG = "#0B1120"        # main background
CARD = "#111827"      # raised card surface
WELL = "#0F172A"      # sunken well (tables, log panes)
CONSOLE_BG = "#060B15"  # near-black console well
LINE = "#1F2937"      # subtle border line

ACCENT = "#1D4ED8"
ACCENT_HOVER = "#2563EB"
ACCENT_LIGHT = "#3B82F6"

INK = "#E5E7EB"       # primary text
MUTED = "#9CA3AF"     # secondary text
FAINT = "#6B7280"     # tertiary text
SOFT = "#CBD5E1"      # soft body text

GRAY_BTN = "#374151"
GRAY_BTN_HOVER = "#4B5563"
RED_BTN = "#7F1D1D"
RED_BTN_HOVER = "#991B1B"


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
        self.geometry("1200x800")
        self.minsize(1040, 720)
        self.configure(fg_color=BG)

        self.reports_folder = parse_reports_folder_from_script(MORNING_SCRIPT)

        # Console runner state. Background threads never touch widgets:
        # they push (kind, text) tuples onto console_q and the Tk after()
        # loop drains them on the main thread (FortiAnalyzer pattern).
        self.console_q: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self.active_process: subprocess.Popen | None = None
        self.active_label: str | None = None
        self._refresh_in_flight = False

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_area()
        self.refresh_task_status()
        self.log("Application started.")

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(120, self.drain_console_queue)

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
        self.btn_options = self.sidebar_button("⚙  Options", self.open_options_window, color="gray")
        self.btn_guide = self.sidebar_button("📖  User Guide", self.open_help_window, color="gray")
        self.btn_logs = self.sidebar_button("🧹  Clear Log", self.clear_log, color="gray")
        self.btn_exit = self.sidebar_button("⎋  Exit", self.on_close, color="red")

        bottom_label = ctk.CTkLabel(
            self.sidebar,
            text=f"Version {APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=FAINT,
        )
        bottom_label.pack(side="bottom", anchor="w", padx=24, pady=24)

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
        self.main.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 12))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text=APP_NAME,
            font=ctk.CTkFont(size=32, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        description = ctk.CTkLabel(
            header,
            text="Generate reports, open output folders, and manage scheduled automation.",
            font=ctk.CTkFont(size=15),
            text_color=SOFT,
        )
        description.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.status_row = ctk.CTkFrame(self.main, fg_color="transparent")
        self.status_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(8, 12))
        self.status_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.morning_card = self.status_card(self.status_row, 0, "☀", "Morning Report")
        self.afternoon_card = self.status_card(self.status_row, 1, "🌤", "Afternoon Report")
        self.scheduler_card = self.status_card(self.status_row, 2, "📅", "Scheduler Status")

        self.action_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color=CARD)
        self.action_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 14))
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
            text="Open reports in a separate console window (instead of the Console tab below)",
            variable=self.detached_var,
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
            checkbox_width=18,
            checkbox_height=18,
        )
        detached_check.grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(0, 14))

        self.scheduler_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color=CARD)
        self.scheduler_frame.grid(row=3, column=0, sticky="ew", padx=28, pady=(0, 14))
        self.scheduler_frame.grid_columnconfigure(0, weight=1)

        scheduler_title = ctk.CTkLabel(
            self.scheduler_frame,
            text="Task Scheduler",
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        scheduler_title.grid(row=0, column=0, sticky="w", padx=20, pady=(18, 4))

        scheduler_subtitle = ctk.CTkLabel(
            self.scheduler_frame,
            text="Enable, disable, and inspect Windows Task Scheduler entries.",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        scheduler_subtitle.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        self.task_table = ctk.CTkFrame(self.scheduler_frame, fg_color=WELL, corner_radius=10)
        self.task_table.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        self.task_table.grid_columnconfigure(0, weight=2)
        self.task_table.grid_columnconfigure(1, weight=2)
        self.task_table.grid_columnconfigure(2, weight=2)
        self.task_table.grid_columnconfigure(3, weight=2)
        self.task_table.grid_columnconfigure(4, weight=1)

        self.build_task_table_header()
        self.build_task_rows()

        self.build_output_tabs()

    def build_output_tabs(self):
        """Bottom panel: Activity Log + Console Output tabs.
        The console mirrors the FortiAnalyzer activity log: color-coded
        lines fed from a queue, showing live stdout/stderr of report runs."""
        self.tabs = ctk.CTkTabview(
            self.main,
            corner_radius=14,
            fg_color=CARD,
            segmented_button_fg_color=WELL,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT_HOVER,
            segmented_button_unselected_color=WELL,
            segmented_button_unselected_hover_color=GRAY_BTN,
        )
        self.tabs.grid(row=4, column=0, sticky="nsew", padx=28, pady=(0, 28))

        log_tab = self.tabs.add("Activity Log")
        console_tab = self.tabs.add("Console Output")

        # ---- Activity Log tab ----
        log_tab.grid_columnconfigure(0, weight=1)
        log_tab.grid_rowconfigure(0, weight=1)

        self.log_box = ctk.CTkTextbox(
            log_tab,
            corner_radius=10,
            fg_color=WELL,
            font=ctk.CTkFont(size=13),
        )
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.log_box.configure(state="disabled")
        for tag, color in (("err", DANGER), ("warn", WARN), ("ok", OK), ("info", INK)):
            self.log_box.tag_config(tag, foreground=color)

        # ---- Console Output tab ----
        console_tab.grid_columnconfigure(0, weight=1)
        console_tab.grid_rowconfigure(1, weight=1)

        console_header = ctk.CTkFrame(console_tab, fg_color="transparent")
        console_header.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        console_header.grid_columnconfigure(0, weight=1)

        self.console_status = ctk.CTkLabel(
            console_header,
            text="●  Idle",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=FAINT,
            anchor="w",
        )
        self.console_status.grid(row=0, column=0, sticky="w", padx=(6, 0))

        self.stop_button = ctk.CTkButton(
            console_header,
            text="⏹  Stop",
            width=90,
            height=30,
            state="disabled",
            fg_color=RED_BTN,
            hover_color=RED_BTN_HOVER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.stop_report,
        )
        self.stop_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        clear_console_button = ctk.CTkButton(
            console_header,
            text="Clear",
            width=70,
            height=30,
            fg_color=GRAY_BTN,
            hover_color=GRAY_BTN_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.clear_console,
        )
        clear_console_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

        self.console_box = ctk.CTkTextbox(
            console_tab,
            corner_radius=10,
            fg_color=CONSOLE_BG,
            text_color="#CDDBEA",
            font=ctk.CTkFont(family="Consolas", size=12),
        )
        self.console_box.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))
        self.console_box.configure(state="disabled")
        for tag, color in (("err", DANGER), ("warn", WARN), ("ok", OK),
                           ("info", "#CDDBEA"), ("sys", ACCENT_LIGHT)):
            self.console_box.tag_config(tag, foreground=color)

    def status_card(self, parent, column, icon, title):
        card = ctk.CTkFrame(parent, corner_radius=14, fg_color=CARD)
        card.grid(row=0, column=column, sticky="nsew", padx=8)
        card.grid_columnconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(
            card,
            text=icon,
            width=48,
            height=48,
            corner_radius=24,
            fg_color=ACCENT,
            font=ctk.CTkFont(size=22),
        )
        icon_label.grid(row=0, column=0, rowspan=3, padx=18, pady=22)

        title_label = ctk.CTkLabel(
            card,
            text=title,
            font=ctk.CTkFont(size=17, weight="bold"),
        )
        title_label.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=(20, 4))

        status_label = ctk.CTkLabel(
            card,
            text="●  Checking…",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        status_label.grid(row=1, column=1, sticky="w", padx=(0, 16))

        detail_label = ctk.CTkLabel(
            card,
            text="Next Run: N/A",
            font=ctk.CTkFont(size=13),
            text_color=MUTED,
        )
        detail_label.grid(row=2, column=1, sticky="w", padx=(0, 16), pady=(0, 20))

        return {
            "card": card,
            "status": status_label,
            "detail": detail_label,
        }

    def action_button(self, parent, column, icon, title, subtitle, command):
        frame = ctk.CTkButton(
            parent,
            command=command,
            height=84,
            corner_radius=12,
            text=f"{icon}   {title}\n{subtitle}",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
        )
        frame.grid(row=0, column=column, sticky="ew", padx=14, pady=(18, 10))
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
            label.grid(row=0, column=col, sticky="w", padx=14, pady=(12, 8))

    def build_task_rows(self):
        self.morning_task_labels = self.create_task_row(1, "Morning Task", MORNING_TASK_NAME)
        self.afternoon_task_labels = self.create_task_row(2, "Afternoon Task", AFTERNOON_TASK_NAME)

    def create_task_row(self, row, display_name, task_name):
        name = ctk.CTkLabel(self.task_table, text=display_name, font=ctk.CTkFont(size=14))
        name.grid(row=row, column=0, sticky="w", padx=14, pady=10)

        status = ctk.CTkLabel(self.task_table, text="Unknown", font=ctk.CTkFont(size=14))
        status.grid(row=row, column=1, sticky="w", padx=14, pady=10)

        next_run = ctk.CTkLabel(self.task_table, text="N/A", font=ctk.CTkFont(size=14))
        next_run.grid(row=row, column=2, sticky="w", padx=14, pady=10)

        last_result = ctk.CTkLabel(self.task_table, text="N/A", font=ctk.CTkFont(size=14))
        last_result.grid(row=row, column=3, sticky="w", padx=14, pady=10)

        switch = ctk.CTkSwitch(
            self.task_table,
            text="",
            progress_color=ACCENT,
            command=lambda: self.toggle_task(task_name, switch),
        )
        switch.grid(row=row, column=4, sticky="w", padx=14, pady=10)

        return {
            "status": status,
            "next_run": next_run,
            "last_result": last_result,
            "switch": switch,
        }

    # --------------------------------------------------------
    # Logging (Activity Log tab — main thread only)
    # --------------------------------------------------------

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        tag = classify_log_line(message)
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{timestamp}] {message}\n", tag)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def clear_log(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")
        self.log("Log cleared.")

    # --------------------------------------------------------
    # Console output (Console tab — fed from a queue so that
    # background reader threads never touch Tk widgets)
    # --------------------------------------------------------

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
            self.tabs.set("Console Output")
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
        self.tabs.set("Console Output")
        self.log(f"Launching {label}: {launch_target} (output in Console tab)")

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

        box.tag_config("h1", foreground=ACCENT_LIGHT)
        box.tag_config("h2", foreground=ACCENT_LIGHT)
        box.tag_config("dim", foreground=FAINT)
        box.tag_config("body", foreground=INK)
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
        self.scheduler_card["status"].configure(text="●  Checking…", text_color=MUTED)

        def worker():
            morning = get_task_status(MORNING_TASK_NAME)
            afternoon = get_task_status(AFTERNOON_TASK_NAME)
            self.after(0, lambda: self.apply_task_status(morning, afternoon))

        threading.Thread(target=worker, daemon=True).start()

    def apply_task_status(self, morning: dict, afternoon: dict):
        self._refresh_in_flight = False

        self.update_task_row(self.morning_task_labels, morning)
        self.update_task_row(self.afternoon_task_labels, afternoon)

        self.update_status_card(self.morning_card, morning)
        self.update_status_card(self.afternoon_card, afternoon)

        enabled_count = int(morning["enabled"]) + int(afternoon["enabled"])
        if enabled_count == 2:
            scheduler_color = OK
        elif enabled_count == 1:
            scheduler_color = WARN
        else:
            scheduler_color = DANGER

        self.scheduler_card["status"].configure(
            text=f"●  {enabled_count}/2 tasks enabled",
            text_color=scheduler_color,
        )
        self.scheduler_card["detail"].configure(
            text=f"Checked at {datetime.now().strftime('%H:%M:%S')}"
        )

        self.log("Scheduler status refreshed.")

    def update_status_card(self, card: dict, task_info: dict):
        if not task_info["exists"]:
            card["status"].configure(text="●  Task not found", text_color=DANGER)
            card["detail"].configure(text="Next Run: N/A")
            return

        color = OK if task_info["enabled"] else WARN
        card["status"].configure(text=f"●  {task_info['status']}", text_color=color)
        card["detail"].configure(text=f"Next Run: {task_info['next_run']}")

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
