"""
pysomneo - An async Python library to interact with Philips Somneo devices.
"""
from __future__ import annotations

from .somneo import Somneo
from .api import SomneoClientError, SomneoConnectionError, SomneoInvalidURLError
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
    "SomneoClientError",
    "SomneoConnectionError",
    "SomneoInvalidURLError",
    "SOUND_SOURCE_ALARM",
    "SOUND_SOURCE_DUSK",
    "FM_PRESETS",
    "SOURCES",
    "DAYS",
    "DAYS_TYPE",
    "STATUS",
]