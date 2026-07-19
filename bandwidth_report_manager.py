import os
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime
import customtkinter as ctk


# ============================================================
# Basic configuration
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent

MORNING_SCRIPT = SCRIPT_DIR / "Morning BW Reports.py"
AFTERNOON_SCRIPT = SCRIPT_DIR / "Afternoon BW Reports.py"

MORNING_BAT = SCRIPT_DIR / "Task Morning BW Reports.bat"
AFTERNOON_BAT = SCRIPT_DIR / "Task Afternoon BW Reports.bat"

MORNING_TASK_NAME = "Bandwidth Morning Reports"
AFTERNOON_TASK_NAME = "Bandwidth Afternoon Reports"

DEFAULT_REPORTS_FOLDER = SCRIPT_DIR / "reports"


# ============================================================
# Helper functions
# ============================================================

def parse_reports_folder_from_script(script_path: Path) -> Path:
    """
    Attempts to read REPORTS_FOLDER from one of the report scripts.
    Falls back to ./reports if it cannot find a patched value.
    """
    try:
        if not script_path.exists():
            return DEFAULT_REPORTS_FOLDER

        content = script_path.read_text(encoding="utf-8")
        match = re.search(r'REPORTS_FOLDER\s*=\s*r?["\'](.*?)["\']', content)

        if not match:
            return DEFAULT_REPORTS_FOLDER

        raw_path = match.group(1).strip()

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

        self.title("Bandwidth Report Manager")
        self.geometry("1180x760")
        self.minsize(1000, 680)

        self.reports_folder = parse_reports_folder_from_script(MORNING_SCRIPT)

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.build_sidebar()
        self.build_main_area()
        self.refresh_task_status()
        self.log("Application started.")

    # --------------------------------------------------------
    # Layout
    # --------------------------------------------------------

    def build_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=250, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand_frame.pack(fill="x", padx=22, pady=(28, 22))

        logo = ctk.CTkLabel(
            brand_frame,
            text="▮▮▮",
            font=ctk.CTkFont(size=34, weight="bold"),
            text_color="#3B82F6",
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
            text_color="#9CA3AF",
        )
        subtitle.pack(anchor="w")

        self.btn_morning = self.sidebar_button("▶  Run Morning Report", self.run_morning_report)
        self.btn_afternoon = self.sidebar_button("▶  Run Afternoon Report", self.run_afternoon_report)
        self.btn_folder = self.sidebar_button("📁  Open Reports Folder", self.open_reports_folder)
        self.btn_refresh = self.sidebar_button("🔄  Refresh Scheduler", self.refresh_task_status)
        self.btn_options = self.sidebar_button("⚙  Options", self.open_options_window, color="gray")
        self.btn_logs = self.sidebar_button("🧹  Clear Log", self.clear_log, color="gray")
        self.btn_exit = self.sidebar_button("⎋  Exit", self.destroy, color="red")

        bottom_label = ctk.CTkLabel(
            self.sidebar,
            text="Version 1.0.0",
            font=ctk.CTkFont(size=12),
            text_color="#6B7280",
        )
        bottom_label.pack(side="bottom", anchor="w", padx=24, pady=24)

    def sidebar_button(self, text, command, color="blue"):
        if color == "red":
            fg_color = "#7F1D1D"
            hover_color = "#991B1B"
        elif color == "gray":
            fg_color = "#374151"
            hover_color = "#4B5563"
        else:
            fg_color = "#1D4ED8"
            hover_color = "#2563EB"

        button = ctk.CTkButton(
            self.sidebar,
            text=text,
            command=command,
            height=46,
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=fg_color,
            hover_color=hover_color,
        )
        button.pack(fill="x", padx=22, pady=7)
        return button

    def build_main_area(self):
        self.main = ctk.CTkFrame(self, corner_radius=0, fg_color="#0B1120")
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(4, weight=1)

        header = ctk.CTkFrame(self.main, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=28, pady=(26, 12))
        header.grid_columnconfigure(0, weight=1)

        title = ctk.CTkLabel(
            header,
            text="Bandwidth Report Manager",
            font=ctk.CTkFont(size=32, weight="bold"),
        )
        title.grid(row=0, column=0, sticky="w")

        description = ctk.CTkLabel(
            header,
            text="Generate reports, open output folders, and manage scheduled automation.",
            font=ctk.CTkFont(size=15),
            text_color="#CBD5E1",
        )
        description.grid(row=1, column=0, sticky="w", pady=(6, 0))

        self.status_row = ctk.CTkFrame(self.main, fg_color="transparent")
        self.status_row.grid(row=1, column=0, sticky="ew", padx=28, pady=(8, 12))
        self.status_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.morning_card = self.status_card(self.status_row, 0, "☀", "Morning Report")
        self.afternoon_card = self.status_card(self.status_row, 1, "🌤", "Afternoon Report")
        self.scheduler_card = self.status_card(self.status_row, 2, "📅", "Scheduler Status")

        self.action_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color="#111827")
        self.action_frame.grid(row=2, column=0, sticky="ew", padx=28, pady=(0, 14))
        self.action_frame.grid_columnconfigure((0, 1), weight=1)

        self.action_button(
            self.action_frame,
            0,
            "▶",
            "Run Morning Report Now",
            "Launch the morning bandwidth report script.",
            self.run_morning_report,
        )
        self.action_button(
            self.action_frame,
            1,
            "▶",
            "Run Afternoon Report Now",
            "Launch the afternoon bandwidth report script.",
            self.run_afternoon_report,
        )

        self.scheduler_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color="#111827")
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
            text_color="#9CA3AF",
        )
        scheduler_subtitle.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 12))

        self.task_table = ctk.CTkFrame(self.scheduler_frame, fg_color="#0F172A", corner_radius=10)
        self.task_table.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        self.task_table.grid_columnconfigure(0, weight=2)
        self.task_table.grid_columnconfigure(1, weight=2)
        self.task_table.grid_columnconfigure(2, weight=2)
        self.task_table.grid_columnconfigure(3, weight=2)
        self.task_table.grid_columnconfigure(4, weight=1)

        self.build_task_table_header()
        self.build_task_rows()

        self.log_frame = ctk.CTkFrame(self.main, corner_radius=14, fg_color="#111827")
        self.log_frame.grid(row=4, column=0, sticky="nsew", padx=28, pady=(0, 28))
        self.log_frame.grid_columnconfigure(0, weight=1)
        self.log_frame.grid_rowconfigure(1, weight=1)

        log_header = ctk.CTkFrame(self.log_frame, fg_color="transparent")
        log_header.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        log_header.grid_columnconfigure(0, weight=1)

        log_title = ctk.CTkLabel(
            log_header,
            text="Activity Log",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        log_title.grid(row=0, column=0, sticky="w")

        self.log_box = ctk.CTkTextbox(
            self.log_frame,
            corner_radius=10,
            fg_color="#0F172A",
            font=ctk.CTkFont(size=13),
        )
        self.log_box.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

    def status_card(self, parent, column, icon, title):
        card = ctk.CTkFrame(parent, corner_radius=14, fg_color="#111827")
        card.grid(row=0, column=column, sticky="nsew", padx=8)
        card.grid_columnconfigure(1, weight=1)

        icon_label = ctk.CTkLabel(
            card,
            text=icon,
            width=48,
            height=48,
            corner_radius=24,
            fg_color="#1D4ED8",
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
            text="Status: Unknown",
            font=ctk.CTkFont(size=13),
            text_color="#CBD5E1",
        )
        status_label.grid(row=1, column=1, sticky="w", padx=(0, 16))

        detail_label = ctk.CTkLabel(
            card,
            text="Next Run: N/A",
            font=ctk.CTkFont(size=13),
            text_color="#9CA3AF",
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
            text=f"{icon}   {title}\n{subtitle}",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
            fg_color="#1D4ED8",
            hover_color="#2563EB",
        )
        frame.grid(row=0, column=column, sticky="ew", padx=14, pady=18)
        return frame

    def build_task_table_header(self):
        headers = ["Task Name", "Status", "Next Run", "Last Result", "Enabled"]
        for col, text in enumerate(headers):
            label = ctk.CTkLabel(
                self.task_table,
                text=text,
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#CBD5E1",
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
    # Logging
    # --------------------------------------------------------

    def log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.log_box.insert("end", f"[{timestamp}] {message}\n")
        self.log_box.see("end")

    def clear_log(self):
        self.log_box.delete("1.0", "end")
        self.log("Log cleared.")

    # --------------------------------------------------------
    # Options window
    # --------------------------------------------------------

    def open_options_window(self):
        username, password = parse_credentials_from_script(MORNING_SCRIPT)

        window = ctk.CTkToplevel(self)
        window.title("Options")
        window.geometry("620x520")
        window.minsize(560, 480)
        window.grab_set()
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
            text_color="#CBD5E1",
        )
        subtitle.grid(row=1, column=0, sticky="w", padx=28, pady=(0, 20))

        credentials_card = ctk.CTkFrame(window, corner_radius=14, fg_color="#111827")
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

        credentials_note = ctk.CTkLabel(
            credentials_card,
            text="Note: this updates the constants inside both Morning and Afternoon report scripts.",
            font=ctk.CTkFont(size=12),
            text_color="#9CA3AF",
        )
        credentials_note.grid(row=3, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 18))

        folder_card = ctk.CTkFrame(window, corner_radius=14, fg_color="#111827")
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
            text_color="#9CA3AF",
        )
        folder_note.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(6, 18))

        status_label = ctk.CTkLabel(
            window,
            text="",
            font=ctk.CTkFont(size=13),
            text_color="#9CA3AF",
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
                    text_color="#F87171",
                )
                return

            if not new_reports_folder_raw:
                status_label.configure(
                    text="Reports folder cannot be blank.",
                    text_color="#F87171",
                )
                return

            new_reports_folder = Path(new_reports_folder_raw).expanduser()

            try:
                new_reports_folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                status_label.configure(
                    text=f"Could not create/use reports folder: {error}",
                    text_color="#F87171",
                )
                return

            credentials_success, credentials_message = update_all_report_credentials(new_username, new_password)
            if not credentials_success:
                status_label.configure(text=credentials_message, text_color="#F87171")
                self.log(f"ERROR updating credentials: {credentials_message}")
                return

            folder_success, folder_message = update_all_report_folders(new_reports_folder)
            if not folder_success:
                status_label.configure(text=folder_message, text_color="#F87171")
                self.log(f"ERROR updating reports folder: {folder_message}")
                return

            self.reports_folder = new_reports_folder
            status_label.configure(
                text="Options saved successfully.",
                text_color="#34D399",
            )
            self.log("Options updated successfully.")

        save_button = ctk.CTkButton(
            button_row,
            text="Save Options",
            command=save_options,
            width=160,
            height=40,
        )
        save_button.grid(row=0, column=1, sticky="e", padx=(8, 0))

        close_button = ctk.CTkButton(
            button_row,
            text="Close",
            command=window.destroy,
            width=120,
            height=40,
            fg_color="#374151",
            hover_color="#4B5563",
        )
        close_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    # --------------------------------------------------------
    # Script launching
    # --------------------------------------------------------

    def launch_bat_or_script(self, bat_path: Path, script_path: Path, label: str):
        try:
            if bat_path.exists():
                command = ["cmd.exe", "/c", str(bat_path)]
                launch_target = bat_path.name
            elif script_path.exists():
                command = [sys.executable, str(script_path)]
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

            self.log(f"{label} launched successfully.")

        except Exception as error:
            self.log(f"ERROR launching {label}: {error}")

    def run_morning_report(self):
        self.launch_bat_or_script(MORNING_BAT, MORNING_SCRIPT, "Morning report")

    def run_afternoon_report(self):
        self.launch_bat_or_script(AFTERNOON_BAT, AFTERNOON_SCRIPT, "Afternoon report")

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
        morning = get_task_status(MORNING_TASK_NAME)
        afternoon = get_task_status(AFTERNOON_TASK_NAME)

        self.update_task_row(self.morning_task_labels, morning)
        self.update_task_row(self.afternoon_task_labels, afternoon)

        self.morning_card["status"].configure(text=f"Status: {morning['status']}")
        self.morning_card["detail"].configure(text=f"Next Run: {morning['next_run']}")

        self.afternoon_card["status"].configure(text=f"Status: {afternoon['status']}")
        self.afternoon_card["detail"].configure(text=f"Next Run: {afternoon['next_run']}")

        enabled_count = int(morning["enabled"]) + int(afternoon["enabled"])
        self.scheduler_card["status"].configure(text=f"Status: {enabled_count}/2 enabled")
        self.scheduler_card["detail"].configure(text="Task Scheduler checked")

        self.log("Scheduler status refreshed.")

    def update_task_row(self, row_labels, task_info):
        if not task_info["exists"]:
            row_labels["status"].configure(text="Not found", text_color="#F87171")
            row_labels["next_run"].configure(text="N/A")
            row_labels["last_result"].configure(text="N/A")
            row_labels["switch"].deselect()
            return

        status_text = task_info["status"]
        enabled = task_info["enabled"]

        row_labels["status"].configure(
            text=status_text,
            text_color="#34D399" if enabled else "#FBBF24",
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


if __name__ == "__main__":
    app = BandwidthReportManager()
    app.mainloop()