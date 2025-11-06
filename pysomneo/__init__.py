"""
pysomneo - A Python library to interact with Philips Somneo devices.
"""

from .somneo import Somneo
from .const import (
    SOUND_SOURCE_ALARM,
    SOUND_SOURCE_DUSK,
    FM_PRESETS,
    SOURCES,
    DAYS,
    DAYS_TYPE,
    STATUS,
)

__all__ = [
    "Somneo",
    "SOUND_SOURCE_ALARM",
    "SOUND_SOURCE_DUSK",
    "FM_PRESETS",
    "SOURCES",
    "DAYS",
    "DAYS_TYPE",
    "STATUS",
]
