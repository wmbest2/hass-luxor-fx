# Luxor local protocol

`POST http://<controller>/<Method>.json` with a JSON body. Response is JSON with `Status` (0 = OK). No auth. GET returns 404. The controller handles one request at a time; responses take ~80–250 ms.

Controller generation comes from the `ControllerName` prefix: `luxor` = ZD, `lxzdc` = ZDC, `lxtwo` = ZDTWO (Gen 2).

The firmware matches method names loosely: `ThemeColorListGet` returns `ColorListGet`'s data and `ColorGroupListGet` returns `GroupListGet`'s.

## Reads (observed on a ZDTWO)

| Method | Request | Response |
|---|---|---|
| ControllerName | – | `Controller, ConnType, RSSI` |
| GroupListGet | – | `GroupList: [{Name, Grp, Inten, Colr}]` |
| ThemeListGet | – | `Restricted, ThemeList: [{Name, ThemeIndex, OnOff}]` |
| GetValidThemes | – | `ThemeIndexes: [..]` |
| ThemeGet | `ThemeIndex` | `Groups: [{GroupNumber, Intensity, Color}]` |
| ColorListGet | – | `ListSize: 250, ColorList: [{C, Hue, Sat}]` (defined slots only) |
| ColorWheelListGet | – | `ListSize: 10, CWList: [..]` (entry shape TBD) |

## Writes

| Method | Request |
|---|---|
| IlluminateGroup | `GroupNumber, Intensity (0–100)` |
| IlluminateTheme | `ThemeIndex, OnOff` |
| IlluminateAll / ExtinguishAll | – |
| ColorListSet | `C (1–250), Hue (0–359), Sat (0–100)` |
| GroupListEdit | `Name, GroupNumber, Color` |
| GroupListAdd / Delete / Rename / Reorder / Clear | see scottlamb/luxor |
| ThemeSet, ThemeListAdd / Delete / Rename / Reorder / Clear, ThemeClear | see scottlamb/luxor |
| FlashLights | `OnOff` |

## Color slots

`Colr` / `Color`: 0 none, 1–250 palette, 251–260 color wheels CW1–CW10, 65535 DMX.

## Status codes

0 OK, 1 unknown method, 101 unparseable, 102 invalid, 151 color out of range, 201 precondition failed, 202 group name in use, 205 group number in use, 241 item does not exist, 242 bad group number, 243 theme index out of range, 251 bad theme index, 252 theme changes restricted.

## Discovery

The Luxor app checks the last-known IP, then scans the subnet (about a minute). No mDNS advertisement has been confirmed yet; `tools/luxor_discovery.py` checks. The integration uses DHCP hostname matching instead.
