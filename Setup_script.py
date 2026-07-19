import subprocess
import sys
import socket
import getpass
#import os
import re
from pathlib import Path

# Configuration #
# Replace path to whichever folder you would like the reports to be saved into.
# Default is the same folder as the script, in a subfolder called "reports". If the folder does not exist, it will be created.
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_REPORTS_FOLDER = SCRIPT_DIR / "reports"
MORNING_TEMPLATE_PATH = SCRIPT_DIR / "Daily Morning Reports yy-mm-dd.oft"
AFTERNOON_TEMPLATE_PATH = SCRIPT_DIR / "Daily Afternoon Reports yy-mm-dd.oft"

# URL in question, replace with the actual URL you want to test against.
EHEALTH_URL = "ehealth-gonet.telus.com"

# Template files for Daily Reports; manually prepped for this specific task for now.
REQUIRED_TEMPLATES = [
    "Daily Morning Reports yy-mm-dd.oft",
    "Daily Afternoon Reports yy-mm-dd.oft"
]

# Necessary packages #
REQUIRED_PACKAGES = [
    "pywin32",
    "aiohttp",
    "pdfplumber",
    "playwright",
    "customtkinter"
]

SCHEDULED_TASKS = [
    {
        "task_name": "Bandwidth Morning Reports",
        "bat_name": "Task Morning BW Reports.bat",
        "script_name": "Morning BW Reports.py",
        "time": "10:58",
    },
    {
        "task_name": "Bandwidth Afternoon Reports",
        "bat_name": "Task Afternoon BW Reports.bat",
        "script_name": "Afternoon BW Reports.py",
        "time": "14:58",
    },
]

# Helper functions #
# Command runner
def run_cmd(command): # runs a command in the terminal and prints it out for visibility
    print(f"\n>> {' '.join(command)}")
    subprocess.check_call(command, shell=False) # runs the command and raises an error if it fails

# Reports folder
def get_reports_folder():
    while True:
        user_input = input(
            f"Where should reports be saved?\n"
            f"Press Enter to use default: {DEFAULT_REPORTS_FOLDER}\n"
            f"> "
        ).strip()

        if user_input:
            reports_folder = Path(user_input).expanduser()
        else:
            reports_folder = DEFAULT_REPORTS_FOLDER

        try:
            reports_folder.mkdir(parents=True, exist_ok=True)

            if not reports_folder.is_dir():
                print("Error: That path exists, but it is not a folder.")
                continue

            return reports_folder

        except OSError as error:
            print(f"Error: Could not use that folder path.")
            print(f"Reason: {error}")
            print("Please enter a different folder path.\n")

# Template checking
def check_templates():
    missing_templates = []
    for template in REQUIRED_TEMPLATES:
        template_path = SCRIPT_DIR / template
        if not template_path.exists():
            missing_templates.append(template)
    return missing_templates

def create_task_batch_file(bat_name, script_name):
    bat_path = SCRIPT_DIR / bat_name
    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        print(f"Error: Cannot create {bat_name} because {script_name} was not found.")
        return False
    
    bat_content = f"""@echo off
    cd /d "{SCRIPT_DIR}"
    "{sys.executable}" "{script_path}"
    """

    bat_path.write_text(bat_content, encoding="utf-8")
    print(f"Created/updated batch file: {bat_path}")
    return True

def create_scheduled_task(task_name, bat_name, time_24h):
    bat_path = SCRIPT_DIR / bat_name

    if not bat_path.exists():
        print(f"Error: Batch file not found: {bat_path}")
        return False
    
    command = [
        "schtasks",
        "/Create",
        "/TN", task_name,
        "/TR", f'cmd.exe /c ""{bat_path}""',
        "/SC", "DAILY",
        "/ST", time_24h,
        "/F",
    ]

    try:
        run_cmd(command)
        print(f"Created/updated Windows scheduled task: {task_name} at {time_24h}")
        return True
    
    except subprocess.CalledProcessError:
        print(f"Error: Failed to create/update scheduled task: {task_name}")
        return False

def ask_yes_no(prompt, default="n"):
    default = default.lower()

    while True:
        answer = input(f"{prompt} [{'Y/n' if default == 'y' else 'y/N'}]: ").strip().lower()
    
        if not answer:
            answer = default
        
        if answer in ("y", "yes"):
            return True

        if answer in ("n", "no"):
            return False
        
        print("Please enter y or n.")

def update_scheduled_task_settings(task_name):
    powershell_script = f"""
$ErrorActionPreference = 'Stop'

$task = Get-ScheduledTask -TaskName "{task_name}"
$settings = $task.Settings

$settings.DisallowStartIfOnBatteries = $false

$settings.StopIfGoingOnBatteries = $false

$settings.StartWhenAvailable = $true

Set-ScheduledTask -TaskName "{task_name}" -Settings $settings
    """
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", powershell_script,
    ]

    try:
        run_cmd(command)
        print(f"Updated Task Scheduler settings for: {task_name}")
        return True
    except subprocess.CalledProcessError:
        print(f"Error: Failed to update Task Scheduler settings for: {task_name}")
        return False

# Credential Patching
def prompt_credentials():
    print("\nPlease enter your credentials for the eHealth portal.")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ").strip()
    return username, password

def patch_credentials_in_script(script_name, username, password):
    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        print(f"Error: Script file '{script_path}' not found.")
        return False

    content = script_path.read_text(encoding="utf-8")

    content, username_replacements = re.subn(
        r'(EHEALTH_USERNAME\s*=\s*)["\'].*?["\']',
        lambda match: f'{match.group(1)}"{username}"',
        content,
        flags=re.IGNORECASE
    )

    content, password_replacements = re.subn(
        r'(EHEALTH_PASSWORD\s*=\s*)["\'].*?["\']',
        lambda match: f'{match.group(1)}"{password}"',
        content,
        flags=re.IGNORECASE
    )

    if username_replacements == 0:
        print(f"Error: Could not find EHEALTH_USERNAME in '{script_path.name}'.")
        return False

    if password_replacements == 0:
        print(f"Error: Could not find EHEALTH_PASSWORD in '{script_path.name}'.")
        return False

    script_path.write_text(content, encoding="utf-8")

    print(f"Credentials patched successfully in '{script_path.name}'.")
    return True

def patch_reports_folder_in_script(script_name, reports_folder):
    script_path = SCRIPT_DIR / script_name

    if not script_path.exists():
        print(f"Error: Script file '{script_path}' not found.")
        return False

    content = script_path.read_text(encoding="utf-8")

    new_content, replacements = re.subn(
        r'REPORTS_FOLDER\s*=\s*r?["\'].*?["\']',
        lambda match: f'REPORTS_FOLDER = {repr(str(reports_folder))}',
        content
    )

    if replacements == 0:
        print(f"Error: Could not find REPORTS_FOLDER in '{script_path.name}'.")
        return False

    script_path.write_text(new_content, encoding="utf-8")

    print(f"Reports folder patched successfully in '{script_path.name}'.")
    return True

# Setup Steps #
def main():
    print("Starting setup...")

    script_dir = SCRIPT_DIR
    print(f"Script directory: {script_dir}")

    reports_folder = get_reports_folder() # If user has a desired path for reports
    print(f"Reports will be saved to: {reports_folder}")

    for script in ["Morning BW Reports.py", "Afternoon BW Reports.py"]:
        if not patch_reports_folder_in_script(script, reports_folder):
            return
        
    # verify templates are present
    missing_templates = check_templates()
    if missing_templates:
        print("\nError: The following required template files are missing:")
        for template in missing_templates:
            print(f"- {template}")
        print("Please ensure these files are in the same directory as this setup script and try again.")
        return
    else:
        print("\nAll required template files are present.")

    try:
        socket.gethostbyname(EHEALTH_URL)
        print(f"Successfully resolved {EHEALTH_URL}. Internet connection is working.")

    except socket.gaierror:
        print(f"Error: Could not resolve {EHEALTH_URL}. Please check your internet connection and DNS settings and try again later.")
        return

    try:
        run_cmd([sys.executable, "-m", "pip", "--version"])
        print("Python and pip are installed.")
    except subprocess.CalledProcessError:
        print("Error: Seems pip is not installed... Please install pip and ensure it is available in your PATH.")
        return
    
    # Install required packages
    print("\nInstalling required packages...")
    for package in REQUIRED_PACKAGES:
        run_cmd([sys.executable, "-m", "pip", "install", package])

    try:
        run_cmd([sys.executable, "-m", "playwright", "install"])
        print("Playwright browsers installed successfully.")
    except subprocess.CalledProcessError:
        print("Error: Failed to install Playwright browsers. Please check the error message above and try installing manually with 'playwright install'.")
        return

    username, password = prompt_credentials() # Prompt for credentials early on to ensure they are ready for patching later
    
    for script in ["Morning BW Reports.py", "Afternoon BW Reports.py"]:
        if not patch_credentials_in_script(script, username, password):
            return
    
    print("\nCreating/updating Task Scheduler batch files...")

    for task in SCHEDULED_TASKS:
        if not create_task_batch_file(task["bat_name"], task["script_name"]):
            return
    
    enable_scheduled_tasks = ask_yes_no(
        "\nWould you like Setup_script.py to add these reports to Windows Task Scheduler?", default="n"
    )

    if enable_scheduled_tasks:
        for task in SCHEDULED_TASKS:
            if not create_scheduled_task(task["task_name"], task["bat_name"], task["time"]):
                return
            if not update_scheduled_task_settings(task["task_name"]):
                return
    else:
        print("Skipped Windows Task Scheduler setup.")
    
    print("\nSetup completed successfully! You can now generate and run your reports.")

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nUnexpected error: {error}")
    
    input("\nPress Enter to close...")