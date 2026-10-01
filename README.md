# FX Luminaire Luxor for Home Assistant

Local control of FX Luminaire Luxor landscape lighting controllers (ZD, ZDC and Gen 2 / ZDTWO) using the same local JSON API the Luxor app uses in Network Mode. No cloud.

Inspired by [dcramer/hass-luxor](https://github.com/dcramer/hass-luxor), with color and full theme support.

## Features

- **Light groups** → `light` entities with brightness (0–100% on the controller).
- **Per-group color** (ZDC / ZDTWO with color fixtures) → full hue/saturation control. Opt in per group in the integration options.
- **Themes** → `switch` entities with real on/off state, plus the theme's group/intensity/color list as attributes.
- **Illuminate all / Extinguish all** buttons.
- **Wi-Fi signal** diagnostic sensor.
- **Discovery**: controllers advertise themselves over mDNS (`lxtwo-*._http._tcp`) and show up automatically; DHCP hostname matching is a fallback. HA follows the controller if its IP changes. Across VLANs, mDNS needs a reflector on your router (or add the controller by IP).
- Reconfigure flow, diagnostics download.

## Install

HACS → Integrations → ⋮ → Custom repositories → add this repo as an *Integration* → install **FX Luminaire Luxor** → restart → Settings → Devices & services → Add integration → *FX Luminaire Luxor*.

Manual: copy `custom_components/fx_luxor` into your HA `config/custom_components/`.

## How color works

The controller doesn't store a color per group. Each group points at one of 250 color *slots* (hue + saturation); slots 251–260 are color wheels. Changing a slot recolors every group that uses it.

For groups you mark as color in the options, the integration gives each its own slot counting down from the top (group 1 → slot 250, group 2 → 249, …) so they can be colored independently. The low slots, where the app saves your presets, are left alone.

## Migrating from dcramer/hass-luxor

This integration uses a different domain (`fx_luxor`), so both can run side by side while you switch. Theme *scenes* become theme *switches* (`switch.turn_on` instead of `scene.turn_on`). Remove the old integration once your automations are updated.

## Development

```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
python tools/fake_controller.py --port 8080   # fake ZDTWO for a dev HA instance
```

`tools/luxor_probe.py` (read-only API dump) and `tools/luxor_discovery.py` (DHCP hostname / mDNS check) help with protocol research. Protocol notes are in [docs/protocol.md](docs/protocol.md).
