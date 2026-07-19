import win32com.client
import aiohttp
import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
from pathlib import Path
import os
import pdfplumber
import re
# import getpass

# Decrypts the stored eHealth password (see credential_store.py)
try:
    from credential_store import reveal
except ImportError:
    def reveal(value):
        if value.startswith("ENC:"):
            raise RuntimeError(
                "credential_store.py is missing - it must sit next to this "
                "script to decrypt the saved eHealth password."
            )
        return value

# Set static configs (unchanging information)
SCRIPT_DIR = Path(__file__).resolve().parent
MORNING_TEMPLATE_PATH = os.path.join(SCRIPT_DIR, r"Daily Morning Reports yy-mm-dd.oft")

# These three values are filled in for you by Setup_script.py or by the
# manager app's Options window. You can also edit them by hand.
# Leave the reports folder blank to use a "reports" subfolder beside this script.
REPORTS_FOLDER = ""
EHEALTH_USERNAME = "username"
EHEALTH_PASSWORD = "password"

# This is the site that redirects straight to standard reports type, if the URL changes from TELUS, change this link as well
FORM_PAGE = "https://ehealth-gonet.telus.com/cgi-bin/nhWebRpt?func=rptLaunch&report=Standard&reportType=trend&subjectType=element"

# These are the interfaces on the GUELPH and KINGSTON data centers
# You can add, remove, or replace an interface
INTERFACES = [
    "EXAMPLES-GO02EXP57WR01XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR02XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR03XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR04XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR05XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR06XXPP-TH-10GEth0/1*",
    "EXAMPLES-GO02EXP57WR07XXPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR01MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR02MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR03MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR04MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR05MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR06MVPP-TH-10GEth0/1*",
    "EXAMPLEO-GO02000F4WR01WANP-TH-10GEth0/1*",
    "EXAMPLEO-GO03SGWP-TH-10GEth0/1*"
]

# The script uniformly analyzes all interfaces if they under/over perform
# These two interfaces usually underperform, so they are excluded from being analyzed for performing under 1 Mbps
EXCLUDE_DIP = {
    "EXAMPLEI-GO020IN02WR06MVPP-TH-10GEth0/1*",
    "EXAMPLEI-GO020IN02WR03MVPP-TH-10GEth0/1*"
}

# This is to set the date for naming conventions and choosing the correct email template
DATETIME = datetime.now().strftime("%Y-%m-%d")

# Resolve the base reports folder; a blank setting falls back to ./reports beside the script
BASE_REPORTS_FOLDER = Path(REPORTS_FOLDER).expanduser() if REPORTS_FOLDER else SCRIPT_DIR / "reports"

# Sets path to where each morning reports folder will be saved in; according to const setup
FOLDER_PATH = os.path.join(
    str(BASE_REPORTS_FOLDER),
    f"Morning Reports - {DATETIME}"
)

# This function checks the folder if it doesn't exist
os.makedirs(FOLDER_PATH, exist_ok=True)

# This is where the email content will first be stored
SUMMARY_FILE = os.path.join(FOLDER_PATH, f"Bandwidth Summary - {DATETIME}.txt")

# Debug log is not being utilized at the moment, you can enable it by modifying the script
DEBUG_LOG = os.path.join(FOLDER_PATH, f"debug_log_{DATETIME}.txt")

# This function allows the bandwidth summary to be able to distinguish Gb, Mb, and Kb
def format_bandwidth_for_alert(value_gbps):
    if value_gbps >= 1:
        return f"{value_gbps:.2f} G"
    elif value_gbps >= 0.001:
        return f"{value_gbps*1000:.2f} M"
    else:
        return f"{value_gbps*1_000_000:.0f} K"

# PDF PARSING
# This function converts Gb to Mb or Kb if needed, or leaves it as is
def to_gbps(value, unit):
    value = float(value)
    unit = unit.upper()
    if unit == "G":
        return value
    if unit == "M":
        return value / 1000
    if unit == "K":
        return value / 1_000_000
    return 0

# Bits in/out line is parsed by parts
# The line is translated into a list, each word separated with a space is an item in the list
# Max value is the 7th item which is 6 (lists begin at 0)
def parse_bits_line(parts):
    try:
        max_val = parts[6]
        max_unit = parts[7]
        min_val = parts[8]
        min_unit = parts[9]
        return to_gbps(max_val, max_unit), to_gbps(min_val, min_unit)
    except (IndexError, ValueError):
        return 0, 0

def parse_bandwidth_from_pdf(pdf_path, interface=None):
    if interface and interface.startswith("EXAMPLEO-GO03SGWP-TH-10GEth0/1"):
        total_bw = 10.0
        print(f"DEBUG OVERRIDE: {interface} total BW statically set to 10 Gbps")
    else:
        total_bw = None

    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    if total_bw is None:
        bw_match = re.search(r"BW:\s*([\d.]+)\s*([GMK])", text, re.IGNORECASE)
        if bw_match:
            total_bw = to_gbps(bw_match.group(1), bw_match.group(2))
        else:
            print(f"WARNING: BW not found in {pdf_path}")
            total_bw = 0

    # Default everything to 0 so a malformed PDF cannot crash the run
    max_in = min_in = max_out = min_out = 0

    for line in text.splitlines():
        parts = line.split()
        if line.startswith("Bits In/sec") and len(parts) >= 10:
            max_in, min_in = parse_bits_line(parts)
        elif line.startswith("Bits Out/sec") and len(parts) >= 10:
            max_out, min_out = parse_bits_line(parts)

    return total_bw, max_in, min_in, max_out, min_out

def debug_print_interface(interface, total_bw, max_in, min_in, max_out, min_out):
    print(f"DEBUG {interface}")
    print(f"  Total BW : {total_bw} Gbps")

# PDF DOWNLOAD WITH RETRY
# This was added due to TELUS's portal being inaccessible on the first try. When the script has trouble accessing the site, it will attempt to do it again for 9 times (10 in total) until retry limit stops
async def download_pdf_with_retry(session, url, path, interface, retries=10, delay=10):
    for attempt in range(1, retries + 1):
        async with session.get(url) as resp:
            content_type = resp.headers.get("Content-Type", "").lower()
            body = await resp.read()

            if "application/pdf" in content_type and body.startswith(b"%PDF"):
                with open(path, "wb") as f:
                    f.write(body)
                return

        print(f"{interface}: report not ready (attempt {attempt}/{retries})")
        await asyncio.sleep(delay)

    raise RuntimeError(f"{interface}: PDF never became ready")

# EMAIL FUNCTION
def open_outlook_and_attach_files(folder_path, alerts):
    outlook = win32com.client.DispatchEx("Outlook.Application")

    # .OFT template path
    template_path = str(MORNING_TEMPLATE_PATH)
    mail = outlook.CreateItemFromTemplate(template_path)

    # Append today's date
    today_mm_dd = datetime.now().strftime("%Y-%m-%d")
    mail.Subject = f"{mail.Subject}{today_mm_dd}"

    # Attach files (skip .txt)
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        if os.path.isfile(file_path) and not filename.lower().endswith(".txt"):
            mail.Attachments.Add(file_path)

    # Base styling to force font size 12
    base_style = 'font-family:Aptos; font-size:12pt;'

    # Build alert HTML
    if alerts == ["No issues."]:
        alert_html = f'<div style="{base_style} color:black;">No issues.</div>'
    else:
        alert_html = ""
        for line in alerts:
            if "peaked" in line:
                color = "red"
            elif "dipped below" in line:
                color = "orange"
            else:
                color = "black"

            alert_html += f'<div style="{base_style} color:{color};">{line}</div>'

    # Inject into email body
    if mail.BodyFormat == 2:  # HTML
        full_body = f"""
            <html>
            <head>
            <style>
            body, p, div, span, td {{
                font-family: Aptos !important; font-size: 12pt !important;
            }}
            </style>
            </head>
            <body>
            {alert_html}<br>
            {mail.HTMLBody}
            </body>
            </html>
            """

        mail.HTMLBody = full_body
    else:
        mail.Body = "\n".join(alerts) + "\n\n" + mail.Body

    mail.Display()

# MAIN ASYNC FUNCTION
# Change login credentials before running script for the first time
async def run():
    username = EHEALTH_USERNAME
    password = reveal(EHEALTH_PASSWORD)

    # A list is initialized for alerts to be stored in for the bandwidth summary file
    final_alerts = []

    # An automated browser opens and redirects to the statically configured link of the reports
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            http_credentials={"username": username, "password": password}
        )
        page = await context.new_page()
        await page.goto(FORM_PAGE)

	# These series of lines automate the configuration on the reports
        # Select LAN/WAN
        await page.locator("#mediumType").select_option("LAN/WAN")
        # Select Bits In as a parameter
        await page.locator("option[value='bitsIn']").evaluate("o => o.selected = true")
        # Select Bits Out as a parameter
        await page.locator("option[value='bitsOut']").evaluate("o => o.selected = true")
        # Expands more options to configure other options
        await page.locator("#moreOptionsImg").click()
        # Summary Statistics must always be included or else the script will be broken
        await page.locator("input[name='showSummaryStatistics']").check()
        # Set the timezone to eastern
        await page.locator("select[name='timezone']").select_option("est5edt")
        # Duration of the performance the report will return
        await page.locator("input[type='radio'][value='prev24Hours']").check()

	# Interface text bar will be last because this field changes for each PDF file
        for interface in INTERFACES:
            print(f"Processing {interface}")
            await page.locator("#nameFilterId").fill(interface)
            await page.locator("#nameFilterId").press("Tab")
            await page.locator("input[name='validateVariables']").click()

            run_button = page.locator(
                "button[name='executeGenerateReportLbl']",
                has_text="Run in New Window"
            ).first

            async with page.expect_event("popup") as popup_info:
                await run_button.click()

            report_page = await popup_info.value

            pdf_link = report_page.locator("a:has(img[alt='Display PDF Report'])")
            await pdf_link.wait_for(state="visible", timeout=15000)
            pdf_href = await pdf_link.get_attribute("href")

            base_url = report_page.url.rsplit("/", 1)[0]
            pdf_url = f"{base_url}/{pdf_href}"
            pdf_name = pdf_href.split("/")[-1]
            pdf_path = os.path.join(FOLDER_PATH, pdf_name)

            async with aiohttp.ClientSession(
                auth=aiohttp.BasicAuth(username, password)
            ) as session:
                await download_pdf_with_retry(
                    session, pdf_url, pdf_path, interface
                )

            await report_page.close()
            await page.bring_to_front()

            with open(pdf_path, "rb") as f:
                if f.read(5) != b"%PDF-":
                    raise RuntimeError(f"{interface}: File is not a valid PDF")

            total_bw, max_in, min_in, max_out, min_out = parse_bandwidth_from_pdf(pdf_path, interface)

            debug_print_interface(interface, total_bw, max_in, min_in, max_out, min_out)

            # Guarded so a PDF with no "BW:" line (total_bw = 0) cannot crash the run
            percentages = [
                (val / total_bw * 100) if total_bw > 0 else 0
                for val in (max_in, min_in, max_out, min_out)
            ]

            print(f"  Max In %  : {percentages[0]:.1f}%")
            print(f"  Min In %  : {percentages[1]:.1f}%")
            print(f"  Max Out % : {percentages[2]:.1f}%")
            print(f"  Min Out % : {percentages[3]:.1f}%\n")

            raw_values = [
                (max_in, True, 'Bits In'),
                (min_in, False, 'Bits In'),
                (max_out, True, 'Bits Out'),
                (min_out, False, 'Bits Out')
            ]

            alerts_for_int = []
            threshold_pct = 70
            for val, is_max, label in raw_values:
                pct = (val / total_bw * 100) if total_bw > 0 else 0
                if pct >= threshold_pct:
                    val_str = f"{val:.2f} G" if is_max else format_bandwidth_for_alert(val)
                    alerts_for_int.append(f"{interface} {label} peaked at {val_str}bps")

            MIN_THRESHOLD_GBPS = 0.001

            if interface not in EXCLUDE_DIP:
                for val, label in [(min_in, 'Bits In'), (min_out, 'Bits Out')]:
                    if val < MIN_THRESHOLD_GBPS:
                        val_str = format_bandwidth_for_alert(val)
                        alerts_for_int.append(
                            f"{interface} {label} dipped below 1 Mbps: {val_str}"
                        )

            final_alerts.extend(alerts_for_int)

    if not final_alerts:
        final_alerts = ["No issues."]

    with open(SUMMARY_FILE, "w") as summary:
        summary.write("\n".join(final_alerts))

    print("Processing complete.")
    print("\nFINAL ALERTS ARRAY:")
    print(final_alerts)

    return final_alerts

# MAIN
if __name__ == "__main__":
    import traceback
    try:
        alerts = asyncio.run(run())
        open_outlook_and_attach_files(FOLDER_PATH, alerts)
    except Exception:
        print("\nError:")
        traceback.print_exc()
    finally:
        input("\nPress Enter to close...")
