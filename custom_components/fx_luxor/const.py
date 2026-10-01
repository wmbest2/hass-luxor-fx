"""Constants for the FX Luminaire Luxor integration."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "fx_luxor"
MANUFACTURER: Final = "FX Luminaire"

CONF_COLOR_GROUPS: Final = "color_groups"
CONF_SCAN_INTERVAL: Final = "scan_interval"

DEFAULT_SCAN_INTERVAL: Final = 15  # seconds
MIN_SCAN_INTERVAL: Final = 5

# Theme definitions (group/intensity/color lists) change rarely; refresh them
# every N polls instead of every poll.
THEME_DETAIL_REFRESH_POLLS: Final = 40

DEFAULT_TURN_ON_INTENSITY: Final = 100

UPDATE_INTERVAL: Final = timedelta(seconds=DEFAULT_SCAN_INTERVAL)
