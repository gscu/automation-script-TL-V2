"""
Shared interface configuration for the bandwidth report scripts and the
manager GUI.

The list of monitored interfaces (their MSUID names), their optional total
bandwidth limits, and which ones skip the low-bandwidth ("dipped below 1
Mbps") alert now live in a single JSON file, `interfaces.json`, instead of
being hardcoded in each report script. The GUI's Interfaces editor writes
that file; the report scripts read it at startup.

Each entry:
  name           - the interface / MSUID string typed into the portal filter.
  bandwidth_gbps - fixed total-capacity used for the % calculations. Leave as
                   null/None to read "BW:" from the report PDF (the default,
                   original behaviour).
  exclude_dip    - true to skip the "dipped below 1 Mbps" alert for this one
                   (for interfaces that are expected to idle low).

If `interfaces.json` is missing or unreadable, the built-in DEFAULT_INTERFACES
below are used, so the scripts always have something to run with.
"""

import json
import sys
from pathlib import Path

# Resolve the folder that holds interfaces.json. When the manager is frozen
# by PyInstaller, the report scripts still sit next to the .exe, so both the
# frozen GUI and the loose report scripts must agree on this location.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "interfaces.json"


# Defaults mirror the original hardcoded lists (GUELPH + KINGSTON interfaces),
# including the two that skipped the low-bandwidth alert and the one whose
# total bandwidth was pinned to 10 Gbps. Edit these in the app, or replace
# this whole set later for your real interfaces.
DEFAULT_INTERFACES = [
    {"name": "EXAMPLES-GO02EXP57WR01XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR02XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR03XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR04XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR05XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR06XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLES-GO02EXP57WR07XXPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEI-GO020IN02WR01MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEI-GO020IN02WR02MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEI-GO020IN02WR03MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": True},
    {"name": "EXAMPLEI-GO020IN02WR04MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEI-GO020IN02WR05MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEI-GO020IN02WR06MVPP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": True},
    {"name": "EXAMPLEO-GO02000F4WR01WANP-TH-10GEth0/1*", "bandwidth_gbps": None, "exclude_dip": False},
    {"name": "EXAMPLEO-GO03SGWP-TH-10GEth0/1*", "bandwidth_gbps": 10.0, "exclude_dip": False},
]


def _coerce_bandwidth(value):
    """Return a positive float, or None to mean 'read it from the PDF'."""
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def normalize(entry: dict) -> dict | None:
    """Validate/clean one raw entry. Returns None for unusable entries
    (e.g. a blank name) so a partially-corrupt file can't crash a run."""
    if not isinstance(entry, dict):
        return None

    name = str(entry.get("name", "")).strip()
    if not name:
        return None

    return {
        "name": name,
        "bandwidth_gbps": _coerce_bandwidth(entry.get("bandwidth_gbps")),
        "exclude_dip": bool(entry.get("exclude_dip", False)),
    }


def _dedupe(entries: list) -> list:
    """Keep the first occurrence of each interface name (case-sensitive)."""
    seen = set()
    result = []
    for entry in entries:
        if entry["name"] in seen:
            continue
        seen.add(entry["name"])
        result.append(entry)
    return result


def load() -> list:
    """Load interfaces from interfaces.json, falling back to the built-in
    defaults if the file is missing, empty, or malformed."""
    try:
        if not CONFIG_FILE.exists():
            return [dict(entry) for entry in DEFAULT_INTERFACES]

        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        raw = data.get("interfaces") if isinstance(data, dict) else data

        if not isinstance(raw, list):
            return [dict(entry) for entry in DEFAULT_INTERFACES]

        cleaned = [e for e in (normalize(item) for item in raw) if e]
        cleaned = _dedupe(cleaned)

        # An empty/all-invalid file shouldn't leave the run with nothing to do.
        return cleaned if cleaned else [dict(entry) for entry in DEFAULT_INTERFACES]

    except (OSError, ValueError):
        return [dict(entry) for entry in DEFAULT_INTERFACES]


def save(interfaces: list) -> None:
    """Write the interface list to interfaces.json (normalized, de-duplicated)."""
    cleaned = _dedupe([e for e in (normalize(item) for item in interfaces) if e])
    payload = {"interfaces": cleaned}
    CONFIG_FILE.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


# Convenience accessors the report scripts use.
def names(interfaces: list) -> list:
    return [entry["name"] for entry in interfaces]


def excluded_dip_names(interfaces: list) -> set:
    return {entry["name"] for entry in interfaces if entry["exclude_dip"]}


def bandwidth_overrides(interfaces: list) -> dict:
    return {
        entry["name"]: entry["bandwidth_gbps"]
        for entry in interfaces
        if entry["bandwidth_gbps"] is not None
    }
