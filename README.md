# FX Luminaire Luxor for Home Assistant

Local control of FX Luminaire Luxor landscape lighting controllers (ZD, ZDC and Gen 2 / ZDTWO) using the same local JSON API the Luxor app uses in Network Mode. No cloud.

Inspired by [dcramer/hass-luxor](https://github.com/dcramer/hass-luxor), with color and full theme support.

Not affiliated with or endorsed by FX Luminaire. FX Luminaire and Luxor are trademarks of their respective owner; the brand icon is the one published in the [Home Assistant brands repository](https://github.com/home-assistant/brands).

## Features

- **Light groups** → one device per group (under the controller device) with a `light` entity, so each group can be placed in its own area. Renames in the Luxor app carry over.
- **Controller device** → themes, all-on/all-off buttons and diagnostics.
- **Per-group color** (ZDC / ZDTWO with color fixtures) → full hue/saturation control. Opt in per group in the integration options.
- **Themes** → one **Theme** selector on the controller device: `Off` plus every theme. Picking a theme applies it; `Off` runs Extinguish all. It shows a theme only while the lights match it, so changing a light by hand clears the selection. Attributes list each theme's groups and levels.
- **Illuminate all / Extinguish all** buttons.
- **Wi-Fi signal** diagnostic sensor.
- **Discovery**: controllers advertise themselves over mDNS (`lxtwo-*._http._tcp`) and show up automatically; DHCP hostname matching is a fallback. HA follows the controller if its IP changes. Across VLANs, mDNS needs a reflector on your router (or add the controller by IP).
- **Theme actions**: create, save current lights as a theme, update, rename and delete themes from automations or Developer tools.
- Reconfigure flow, diagnostics download.

## Install

HACS → Integrations → ⋮ → Custom repositories → add this repo as an *Integration* → install **FX Luminaire Luxor** → restart → Settings → Devices & services → Add integration → *FX Luminaire Luxor*.

Manual: copy `custom_components/fx_luxor` into your HA `config/custom_components/`.

## How color works

The controller doesn't store a color per group. Each group points at one of 250 color *slots* (hue + saturation); slots 251–260 are color wheels. Changing a slot recolors every group that uses it.

For groups you mark as color in the options, the integration gives each its own slot counting down from the top (group 1 → slot 250, group 2 → 249, …) so they can be colored independently. The low slots, where the app saves your presets, are left alone.

## Theme actions

| Action | Use |
|---|---|
| `fx_luxor.create_theme` | `name`, optional `letter` (A–Z), optional `groups`: rows of group light + brightness (+ optional `color_slot`) |
| `fx_luxor.save_current_as_theme` | Snapshot every group's current level (and color) into an existing theme (`theme`: name or letter) or a new one (`name`). `lights` limits which groups are captured. |
| `fx_luxor.update_theme` | `theme` (name or letter) + `groups`: replace its groups and levels |
| `fx_luxor.rename_theme` / `fx_luxor.delete_theme` | `theme` (name or letter) |

`create_theme` and `save_current_as_theme` return the theme's index, letter and name. If theme changes are restricted in the controller's setup menu, the actions fail with a clear error.

### Why a selector and not switches

The controller keeps a separate on/off flag per theme and never clears the others: turn on A, then B, and both report "on" while the lights show B. Changing a light by hand clears nothing either. So the selector shows the theme applied last (from Home Assistant, or the only flagged theme whose levels match the lights) only while every group in it is still at the theme's level. Change a light by hand and the selection clears; put it back and the theme shows again. With every light off it shows `Off`.

```yaml
action: select.select_option
target:
  entity_id: select.luxor_lxtwo_650715048_theme
data:
  option: Nighttime
```

## Adding color fixtures later

The controller doesn't report which fixtures have color (ZDC) boards. After installing them: Settings → Devices & services → FX Luminaire Luxor → **Configure** → tick the groups under *Groups with color fixtures*. Groups the Luxor app has already given a color are pre-selected. Those groups switch from brightness-only to full color lights.

## Migrating from dcramer/hass-luxor

This integration uses a different domain (`fx_luxor`), so both can run side by side while you switch. Theme *scenes* become options of the Theme selector (`select.select_option` instead of `scene.turn_on`). Remove the old integration once your automations are updated.

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
python tools/fake_controller.py --port 8080   # fake ZDTWO for a dev HA instance
```

`tools/luxor_probe.py` (read-only API dump) and `tools/luxor_discovery.py` (DHCP hostname / mDNS check) help with protocol research. Protocol notes are in [docs/protocol.md](docs/protocol.md).
