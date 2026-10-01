"""Async client for the FX Luminaire Luxor controller local JSON API.

The controller exposes ``POST http://<host>/<Method>.json`` with a JSON body and
answers with JSON containing a numeric ``Status`` (0 = OK). It is a small embedded
device that copes poorly with concurrent requests, so every call is serialized
through a lock with a short gap between requests.

This module has no Home Assistant imports so it can be split into its own
PyPI package later.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import aiohttp

DEFAULT_TIMEOUT = 5.0
DEFAULT_ATTEMPTS = 3  # the Wi-Fi module drops the odd request; retry before giving up
RETRY_DELAY = 0.5  # seconds, doubled after each failed attempt
MIN_REQUEST_GAP = 0.1  # seconds between requests

COLOR_NONE = 0
COLOR_SLOT_MIN = 1
COLOR_SLOT_MAX = 250
COLOR_WHEEL_MIN = 251
COLOR_WHEEL_MAX = 260
COLOR_DMX = 65535

THEME_INDEX_MAX = 25  # themes A-Z
MAX_NAME_LENGTH = 19  # bytes; the controller truncates longer names

STATUS_TEXT: dict[int, str] = {
    0: "OK",
    1: "Unknown method",
    101: "Unparseable request",
    102: "Invalid request",
    151: "Color value out of range",
    201: "Precondition failed",
    202: "Group name in use",
    205: "Group number in use",
    241: "Item does not exist",
    242: "Bad group number",
    243: "Theme index out of range",
    251: "Bad theme index",
    252: "Theme changes restricted",
}


class LuxorError(Exception):
    """Base error."""


class LuxorConnectionError(LuxorError):
    """Controller could not be reached or returned garbage."""


class LuxorStatusError(LuxorError):
    """Controller answered with a non-zero Status."""

    def __init__(self, method: str, status: int) -> None:
        self.method = method
        self.status = status
        super().__init__(f"{method} failed: {STATUS_TEXT.get(status, 'Unknown status')} ({status})")


class ControllerType(StrEnum):
    """Controller generations, detected from the controller name prefix."""

    ZD = "ZD"  # Gen 1, dimming only
    ZDC = "ZDC"  # Gen 1, dimming + color
    ZDTWO = "ZDTWO"  # Gen 2, dimming + color + color wheels

    @classmethod
    def from_name(cls, name: str) -> ControllerType:
        prefix = name[:5].lower()
        if prefix == "luxor":
            return cls.ZD
        if prefix == "lxzdc":
            return cls.ZDC
        return cls.ZDTWO  # "lxtwo" and anything newer

    @property
    def supports_color(self) -> bool:
        return self is not ControllerType.ZD


@dataclass(slots=True)
class ControllerInfo:
    name: str
    type: ControllerType
    connection: str | None = None
    rssi: int | None = None


@dataclass(slots=True)
class Group:
    number: int
    name: str
    intensity: int
    color: int | None = None  # color slot; None on ZD controllers

    @property
    def is_on(self) -> bool:
        return self.intensity > 0

    @property
    def color_wheel(self) -> int | None:
        """Color wheel number (1-10) if the group is on a color wheel."""
        if self.color is not None and COLOR_WHEEL_MIN <= self.color <= COLOR_WHEEL_MAX:
            return self.color - COLOR_WHEEL_MIN + 1
        return None


@dataclass(slots=True)
class Theme:
    index: int
    name: str
    on: bool


@dataclass(slots=True)
class ThemeGroup:
    group: int
    intensity: int
    color: int | None = None


@dataclass(slots=True)
class Color:
    slot: int
    hue: int  # 0-359
    saturation: int  # 0-100


@dataclass(slots=True)
class LuxorState:
    """Everything one poll returns."""

    info: ControllerInfo
    groups: dict[int, Group] = field(default_factory=dict)
    themes: dict[int, Theme] = field(default_factory=dict)
    colors: dict[int, Color] = field(default_factory=dict)
    themes_restricted: bool = False


def theme_letter(index: int) -> str:
    """Facepack letter for a theme index (0 -> 'A')."""
    return chr(ord("A") + index) if 0 <= index <= THEME_INDEX_MAX else str(index)


def clean_name(name: str) -> str:
    """Trim a name to what the controller stores, without splitting a UTF-8 character."""
    name = name.strip()
    raw = name.encode()[:MAX_NAME_LENGTH]
    return raw.decode(errors="ignore")


def dedicated_color_slot(group: int) -> int:
    """Color slot reserved for a group so its color is independent of others.

    Counts down from the top of the palette (group 1 -> 250) to stay clear of
    user presets, which the app fills from slot 1 up.
    """
    return COLOR_SLOT_MAX - group + 1


class LuxorClient:
    """Serialized client for one controller."""

    def __init__(
        self,
        host: str,
        session: aiohttp.ClientSession,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        attempts: int = DEFAULT_ATTEMPTS,
        min_gap: float = MIN_REQUEST_GAP,
    ) -> None:
        self.host = host
        self._session = session
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._attempts = max(1, attempts)
        self._min_gap = min_gap
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """Call a controller method and return the decoded response."""
        url = f"http://{self.host}/{method}.json"
        body = json.dumps(payload or {})
        async with self._lock:
            delay = RETRY_DELAY
            for attempt in range(1, self._attempts + 1):
                wait = self._min_gap - (time.monotonic() - self._last)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    text = await self._post(url, body, method)
                    break
                except LuxorConnectionError:
                    if attempt == self._attempts:
                        raise
                    await asyncio.sleep(delay)
                    delay *= 2
                finally:
                    self._last = time.monotonic()
        try:
            data = json.loads(text)
        except ValueError as err:
            raise LuxorConnectionError(f"{method}: invalid JSON") from err
        status = int(data.get("Status", -1))
        if status != 0:
            raise LuxorStatusError(method, status)
        return data

    async def _post(self, url: str, body: str, method: str) -> str:
        try:
            async with self._session.post(
                url,
                data=body,
                # The controller's tiny web server misbehaves with keep-alive: a reused
                # socket can hang until timeout. Ask for a fresh connection every time.
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "Connection": "close",
                },
                timeout=self._timeout,
            ) as resp:
                if resp.status != 200:
                    raise LuxorConnectionError(f"{method}: HTTP {resp.status}")
                return await resp.text(errors="replace")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise LuxorConnectionError(f"{method}: {err!r}") from err

    # ---- reads -----------------------------------------------------------

    async def controller_info(self) -> ControllerInfo:
        data = await self.call("ControllerName")
        name = data["Controller"]
        return ControllerInfo(
            name=name,
            type=ControllerType.from_name(name),
            connection=data.get("ConnType"),
            rssi=data.get("RSSI"),
        )

    async def groups(self) -> dict[int, Group]:
        data = await self.call("GroupListGet")
        groups: dict[int, Group] = {}
        for g in data.get("GroupList") or []:
            num = g.get("Grp", g.get("GroupNumber"))
            if num is None:
                continue
            groups[num] = Group(
                number=num,
                name=g.get("Name", f"Group {num}"),
                intensity=int(g.get("Inten", g.get("Intensity", 0))),
                color=g.get("Colr", g.get("Color")),
            )
        return groups

    async def themes(self) -> tuple[dict[int, Theme], bool]:
        data = await self.call("ThemeListGet")
        themes = {
            t["ThemeIndex"]: Theme(index=t["ThemeIndex"], name=t.get("Name", ""), on=bool(t.get("OnOff")))
            for t in data.get("ThemeList") or []
        }
        return themes, bool(data.get("Restricted"))

    async def theme_groups(self, index: int) -> list[ThemeGroup]:
        data = await self.call("ThemeGet", {"ThemeIndex": index})
        return [
            ThemeGroup(group=g["GroupNumber"], intensity=g.get("Intensity", 0), color=g.get("Color"))
            for g in data.get("Groups") or []
        ]

    async def colors(self) -> dict[int, Color]:
        data = await self.call("ColorListGet")
        return {
            c["C"]: Color(slot=c["C"], hue=int(c.get("Hue", 0)) % 360, saturation=int(c.get("Sat", 0)))
            for c in data.get("ColorList") or []
        }

    async def color_wheels(self) -> list[dict[str, Any]]:
        """Raw color wheel list (Gen 2). Entry format not yet documented."""
        data = await self.call("ColorWheelListGet")
        return list(data.get("CWList") or [])

    async def state(self, info: ControllerInfo | None = None) -> LuxorState:
        """Fetch a full snapshot."""
        info = info or await self.controller_info()
        state = LuxorState(info=info)
        state.groups = await self.groups()
        state.themes, state.themes_restricted = await self.themes()
        if info.type.supports_color:
            state.colors = await self.colors()
        return state

    # ---- writes ----------------------------------------------------------

    async def illuminate_group(self, group: int, intensity: int) -> None:
        await self.call("IlluminateGroup", {"GroupNumber": group, "Intensity": max(0, min(100, intensity))})

    async def illuminate_theme(self, index: int, on: bool) -> None:
        await self.call("IlluminateTheme", {"ThemeIndex": index, "OnOff": 1 if on else 0})

    async def illuminate_all(self) -> None:
        await self.call("IlluminateAll")

    async def extinguish_all(self) -> None:
        await self.call("ExtinguishAll")

    async def set_color(self, slot: int, hue: float, saturation: float) -> None:
        if not COLOR_SLOT_MIN <= slot <= COLOR_SLOT_MAX:
            raise ValueError(f"color slot {slot} out of range")
        await self.call(
            "ColorListSet",
            {"C": slot, "Hue": int(round(hue)) % 360, "Sat": max(0, min(100, int(round(saturation))))},
        )

    async def assign_group_color(self, group: Group, slot: int) -> None:
        """Point a group at a color slot (keeps its name)."""
        await self.call("GroupListEdit", {"Name": group.name, "GroupNumber": group.number, "Color": slot})

    # ---- theme management ------------------------------------------------

    async def add_theme(self, index: int, name: str) -> None:
        """Create an empty theme in slot ``index`` (0-25 = A-Z)."""
        if not 0 <= index <= THEME_INDEX_MAX:
            raise ValueError(f"theme index {index} out of range")
        await self.call("ThemeListAdd", {"ThemeIndex": index, "Name": clean_name(name)})

    async def set_theme_groups(
        self, index: int, groups: list[ThemeGroup], *, include_color: bool = False
    ) -> None:
        """Replace the (group, intensity[, color]) list of a theme."""
        entries: list[dict[str, Any]] = []
        for g in groups:
            entry: dict[str, Any] = {"GroupNumber": g.group, "Intensity": max(0, min(100, g.intensity))}
            if include_color:
                entry["Color"] = g.color or COLOR_NONE
            entries.append(entry)
        await self.call("ThemeSet", {"ThemeIndex": index, "Groups": entries})

    async def rename_theme(self, old_name: str, new_name: str) -> None:
        await self.call("ThemeListRename", {"OldName": old_name, "NewName": clean_name(new_name)})

    async def delete_theme(self, name: str) -> None:
        await self.call("ThemeListDelete", {"Name": name})
