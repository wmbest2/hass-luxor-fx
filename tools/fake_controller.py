#!/usr/bin/env python3
"""In-memory fake Luxor ZDTWO controller for tests and local development.

Run standalone:  python tools/fake_controller.py --port 8080
Then add the integration in a dev Home Assistant with host "127.0.0.1:8080".

Seeded from a real lxtwo controller's responses (3 groups, 1 theme, 10 colors).
"""

from __future__ import annotations

import argparse
import copy
import json
from typing import Any

from aiohttp import web

SEED: dict[str, Any] = {
    "name": "lxtwo-000000001",
    "rssi": 44,
    "groups": [
        {"Name": "Group 1", "Grp": 1, "Inten": 10, "Colr": 0},
        {"Name": "Group 2", "Grp": 2, "Inten": 10, "Colr": 0},
        {"Name": "Group 3", "Grp": 3, "Inten": 100, "Colr": 0},
    ],
    "themes": [{"Name": "Nighttime", "ThemeIndex": 0, "OnOff": 1}],
    "theme_groups": {
        0: [
            {"GroupNumber": 1, "Intensity": 10, "Color": 0},
            {"GroupNumber": 2, "Intensity": 10, "Color": 0},
            {"GroupNumber": 3, "Intensity": 100, "Color": 0},
        ]
    },
    "colors": [
        {"C": 1, "Hue": 43, "Sat": 38},
        {"C": 2, "Hue": 35, "Sat": 21},
        {"C": 3, "Hue": 180, "Sat": 0},
        {"C": 4, "Hue": 0, "Sat": 100},
        {"C": 5, "Hue": 120, "Sat": 100},
        {"C": 6, "Hue": 235, "Sat": 100},
        {"C": 7, "Hue": 0, "Sat": 25},
        {"C": 8, "Hue": 120, "Sat": 25},
        {"C": 9, "Hue": 200, "Sat": 25},
        {"C": 10, "Hue": 275, "Sat": 25},
    ],
}


class FakeLuxor:
    def __init__(self, seed: dict[str, Any] | None = None) -> None:
        s = copy.deepcopy(seed or SEED)
        self.name: str = s["name"]
        self.rssi: int = s["rssi"]
        self.groups: dict[int, dict] = {g["Grp"]: g for g in s["groups"]}
        self.themes: dict[int, dict] = {t["ThemeIndex"]: t for t in s["themes"]}
        self.theme_groups: dict[int, list[dict]] = s["theme_groups"]
        self.colors: dict[int, dict] = {c["C"]: c for c in s["colors"]}
        self.calls: list[tuple[str, dict]] = []
        self.fail_next: int | None = None  # force a Status on the next call

    # each handler returns (status, extra)
    def handle(self, method: str, body: dict) -> dict:
        self.calls.append((method, body))
        if self.fail_next is not None:
            status, self.fail_next = self.fail_next, None
            return {"Status": status}
        fn = getattr(self, f"m_{method}", None)
        if fn is None:
            return {"Status": 1}
        return {"Status": 0, **(fn(body) or {})}

    def m_ControllerName(self, b):
        return {"Controller": self.name, "ConnType": "WiFi", "RSSI": self.rssi}

    def m_GroupListGet(self, b):
        return {"GroupList": list(self.groups.values())}

    def m_ThemeListGet(self, b):
        return {"Restricted": 0, "ThemeList": list(self.themes.values())}

    def m_GetValidThemes(self, b):
        return {"ThemeIndexes": sorted(self.themes)}

    def m_ThemeGet(self, b):
        idx = b.get("ThemeIndex")
        if idx not in self.themes:
            raise _Status(243)
        return {"Groups": self.theme_groups.get(idx, [])}

    def m_ColorListGet(self, b):
        return {"ListSize": 250, "ColorList": [self.colors[k] for k in sorted(self.colors)]}

    def m_ColorWheelListGet(self, b):
        return {"ListSize": 10, "CWList": []}

    def m_IlluminateGroup(self, b):
        g = self.groups.get(b.get("GroupNumber"))
        if g is None:
            raise _Status(242)
        g["Inten"] = int(b["Intensity"])
        for t in self.themes.values():
            t["OnOff"] = 0

    def m_IlluminateTheme(self, b):
        idx = b.get("ThemeIndex")
        if idx not in self.themes:
            raise _Status(243)
        on = bool(b.get("OnOff"))
        for tg in self.theme_groups.get(idx, []):
            g = self.groups.get(tg["GroupNumber"])
            if g:
                g["Inten"] = tg["Intensity"] if on else 0
        self.themes[idx]["OnOff"] = int(on)

    def m_IlluminateAll(self, b):
        for g in self.groups.values():
            g["Inten"] = 75

    def m_ExtinguishAll(self, b):
        for g in self.groups.values():
            g["Inten"] = 0
        for t in self.themes.values():
            t["OnOff"] = 0

    def m_ColorListSet(self, b):
        c, hue, sat = b.get("C"), b.get("Hue"), b.get("Sat")
        if not (1 <= c <= 250 and 0 <= hue <= 360 and 0 <= sat <= 100):
            raise _Status(151)
        self.colors[c] = {"C": c, "Hue": hue, "Sat": sat}

    def m_GroupListEdit(self, b):
        g = self.groups.get(b.get("GroupNumber"))
        if g is None:
            raise _Status(201)
        g["Name"], g["Colr"] = b.get("Name", g["Name"]), b.get("Color", g["Colr"])


class _Status(Exception):
    def __init__(self, status: int) -> None:
        self.status = status


def make_app(fake: FakeLuxor) -> web.Application:
    async def handler(request: web.Request) -> web.Response:
        method = request.match_info["method"]
        raw = await request.text()
        try:
            body = json.loads(raw) if raw.strip() else {}
        except ValueError:
            return web.json_response({"Status": 101})
        try:
            data = fake.handle(method, body)
        except _Status as s:
            data = {"Status": s.status}
        return web.json_response(data)

    async def not_found(request: web.Request) -> web.Response:
        return web.Response(status=404, text="404: File not found")

    app = web.Application()
    app.router.add_post("/{method}.json", handler)
    app.router.add_get("/{tail:.*}", not_found)
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    web.run_app(make_app(FakeLuxor()), port=args.port)
