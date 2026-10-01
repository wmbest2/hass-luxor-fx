#!/usr/bin/env python3
"""Read-only probe for an FX Luminaire Luxor controller.

Usage:  python luxor_probe.py 192.168.20.160
Writes luxor_probe.json next to this script. Standard library only.

Only "get"-style methods are called; nothing on the controller is changed
and no lights turn on or off.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = sys.argv[1] if len(sys.argv) > 1 else "192.168.20.160"
TIMEOUT = 5

KNOWN = ["ControllerName", "GroupListGet", "ThemeListGet", "ColorListGet", "GetValidThemes"]

# Guesses at getters the 4.x app might use. An unknown method just returns Status 1.
CANDIDATES = [
    "ColorWheelListGet",
    "ColorWheelGet",
    "WheelListGet",
    "ControllerInfo",
    "ControllerInfoGet",
    "ControllerVersion",
    "VersionGet",
    "FirmwareVersion",
    "FirmwareVersionGet",
    "ScheduleListGet",
    "ScheduleGet",
    "ProgramListGet",
    "EventListGet",
    "GroupGet",
    "ControllerStatus",
    "StatusGet",
    "DMXListGet",
    "ControllerSetupGet",
    "SetupGet",
    "ThemeColorListGet",
    "ColorGroupListGet",
    "ColorNameListGet",
    "GroupListGetColor",
    "TimeGet",
    "ClockGet",
    "CloudStatus",
    "NetworkGet",
]


def post(method, body=None):
    data = json.dumps(body if body is not None else {}).encode()
    req = urllib.request.Request(
        f"http://{HOST}/{method}.json", data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "replace")
            out = {"http": r.status}
    except urllib.error.HTTPError as e:
        raw, out = e.read().decode("utf-8", "replace"), {"http": e.code}
    except Exception as e:  # noqa: BLE001
        return {"error": repr(e), "ms": round((time.monotonic() - t0) * 1000)}
    out["ms"] = round((time.monotonic() - t0) * 1000)
    try:
        out["json"] = json.loads(raw)
    except ValueError:
        out["raw"] = raw[:4000]
    time.sleep(0.25)  # the controller dislikes back-to-back requests
    return out


def main():
    results = {}
    for m in KNOWN:
        print("->", m)
        results[m] = post(m)

    themes = (results.get("ThemeListGet", {}).get("json") or {}).get("ThemeList") or []
    for t in themes:
        idx = t.get("ThemeIndex")
        print("-> ThemeGet", idx)
        results[f"ThemeGet[{idx}]"] = post("ThemeGet", {"ThemeIndex": idx})

    found = []
    for m in CANDIDATES:
        r = post(m)
        status = (r.get("json") or {}).get("Status")
        if r.get("http") == 200 and status not in (1, None):
            found.append(m)
            results[m] = r
        else:
            results.setdefault("_unknown", {})[m] = (
                status if status is not None else r.get("http", r.get("error"))
            )
    print("Extra methods that responded:", found or "none")

    path = Path(__file__).with_name("luxor_probe.json")
    path.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
