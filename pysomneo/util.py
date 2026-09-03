"""
Utility functions for pysomneo.
"""
from __future__ import annotations

import calendar
from datetime import time, date, timedelta, datetime
from typing import Any

from .const import DAYS, DAYS_TYPE, SOURCES


def days_int_to_list(days_int: int) -> list[str]:
    """Convert integer to list of days."""
    if days_int == 0:
        return ["tomorrow"]
    return [v for k, v in DAYS.items() if k & days_int]


def days_list_to_int(days: list[str] | str) -> int:
    """Convert list of days to integer."""
    return sum(k for k, v in DAYS.items() if v in days)


def days_int_to_type(days_int: int) -> str:
    """Convert integer to predefined days type."""
    if days_int in DAYS_TYPE:
        return DAYS_TYPE[days_int]

    return "custom"


def alarms_to_dict(enabled_alarms: dict, time_alarms: dict) -> dict[int, dict[str, Any]]:
    """Construct alarm data dictionary."""

    alarms: dict[int, dict[str, Any]] = {}
    prfen = enabled_alarms.get("prfen", [])
    prfvs = enabled_alarms.get("prfvs", [])
    almhr = time_alarms.get("almhr", [])
    almmn = time_alarms.get("almmn", [])
    daynm = time_alarms.get("daynm", [])
    pwrsv = enabled_alarms.get("pwrsv", [])

    for alarm in range(len(prfen)):
        enabled = prfen[alarm] if alarm < len(prfen) else 0
        alarms[alarm] = {}
        alarms[alarm]["position"] = alarm + 1
        alarms[alarm]["name"] = "alarm" + str(alarm)
        alarms[alarm]["enabled"] = bool(enabled)
        alarms[alarm]["visible"] = bool(prfvs[alarm]) if alarm < len(prfvs) else True
        alarms[alarm]["time"] = time(
            int(almhr[alarm]) if alarm < len(almhr) else 0,
            int(almmn[alarm]) if alarm < len(almmn) else 0,
        )
        alarms[alarm]["days"] = days_int_to_list(
            int(daynm[alarm]) if alarm < len(daynm) else 0
        )
        alarms[alarm]["days_type"] = DAYS_TYPE.get(
            int(daynm[alarm]) if alarm < len(daynm) else 0,
            "custom",
        )
        pw_index = 3 * alarm
        alarms[alarm]["powerwake"] = bool(pwrsv[pw_index]) if pw_index < len(pwrsv) else False
        if alarms[alarm]["powerwake"]:
            pw_hour = int(pwrsv[pw_index + 1]) if pw_index + 1 < len(pwrsv) else 0
            pw_min = int(pwrsv[pw_index + 2]) if pw_index + 2 < len(pwrsv) else 0
            alarm_hour = int(almhr[alarm]) if alarm < len(almhr) else 0
            alarm_min = int(almmn[alarm]) if alarm < len(almmn) else 0
            alarms[alarm]["powerwake_delta"] = max(
                0,
                60 * pw_hour + pw_min - 60 * alarm_hour - alarm_min,
            )
        else:
            alarms[alarm]["powerwake_delta"] = 0

    return alarms


def sunset_to_dict(
    sunset_data: dict, light_curves: dict, sounds: dict
) -> dict[str, Any]:
    """Construct sunset data dictionary."""
    data: dict[str, Any] = {}
    data["is_on"] = bool(sunset_data.get("onoff", False))
    data["duration"] = int(sunset_data.get("durat", 0))
    ctype = sunset_data.get("ctype", None)
    if ctype is not None and light_curves:
        try:
            data["curve"] = list(light_curves.keys())[
                list(light_curves.values()).index(int(ctype))
            ]
        except (ValueError, IndexError):
            data["curve"] = "sunny day"
    else:
        data["curve"] = "sunny day"
    data["level"] = sunset_data.get("curve", 0)
    snddv = sunset_data.get("snddv", "off")
    sndch = sunset_data.get("sndch", None)
    if snddv == "dus" and sndch is not None and sounds:
        try:
            data["sound"] = list(sounds.keys())[
                list(sounds.values()).index(int(sndch))
            ]
        except (ValueError, IndexError):
            data["sound"] = "off"
    elif snddv == "fmr":
        data["sound"] = "fm " + str(sndch)
    elif snddv == "off":
        data["sound"] = "off"
    else:
        data["sound"] = str(sndch) if sndch else "off"
    data["volume"] = sunset_data.get("sndlv", 0)

    return data


def player_to_dict(player: dict, dusk_sound_themes: dict) -> dict[str, Any]:
    """Construct player data dictionary."""
    data: dict[str, Any] = {}
    data["state"] = bool(player.get("onoff", False))
    sdvol = player.get("sdvol", 1)
    data["volume"] = max(0.0, min(1.0, (float(sdvol) - 1) / 24)) if sdvol else 0.0

    snddv = player.get("snddv")
    sndch = player.get("sndch")

    if snddv == "aux":
        data["source"] = "AUX"
    elif snddv == "fmr":
        data["source"] = "FM " + (sndch if sndch else "1")
    elif snddv == "dus":
        if sndch is not None and dusk_sound_themes:
            theme_name = next(
                (k for k, v in dusk_sound_themes.items() if str(v) == str(sndch)),
                f"dusk:{sndch}",
            )
        else:
            theme_name = "soft_rain"
        data["source"] = theme_name.title()
    else:
        data["source"] = "Other"

    possible_sources = list(SOURCES.keys())
    if dusk_sound_themes:
        possible_sources += [name.title() for name in dusk_sound_themes.keys()]

    data["possible_sources"] = possible_sources

    return data


def get_next_alarm(alarms: dict[int, dict[str, Any]]) -> datetime | None:
    """Get the next alarm that is set.

    Returns a naive datetime in the server's local time (which may be UTC).
    The caller should convert to the user's timezone using the HA timezone
    configuration when needed.
    """
    next_alarm: datetime | None = None
    new_next_alarm: datetime | None = None

    now_time = datetime.now()
    now_day = now_time.date()

    for alarm in alarms:
        if alarms[alarm].get("enabled", False) is True:
            alarm_time = alarms[alarm].get("time")
            alarm_days = alarms[alarm].get("days", [])

            if alarm_time is None:
                continue

            # If alarm goes of tomorrow
            if alarm_days == ["tomorrow"]:
                alarm_time_full = datetime.combine(now_day, alarm_time)
                if alarm_time_full > now_time:
                    new_next_alarm = alarm_time_full
                else:
                    new_next_alarm = alarm_time_full + timedelta(days=1)
            # If days are specified
            else:
                # Find first following day that the alarm is set.
                for d in range(0, 7):
                    test_day = now_time.isoweekday() + d
                    if test_day > 7:
                        test_day -= 7
                    if calendar.day_abbr[test_day - 1].lower() in alarm_days:
                        alarm_time_full = datetime.combine(
                            now_day, alarm_time
                        ) + timedelta(days=d)
                        if alarm_time_full > now_time:
                            new_next_alarm = alarm_time_full
                            break

            if next_alarm is not None and new_next_alarm is not None:
                next_alarm = min(next_alarm, new_next_alarm)
            elif new_next_alarm is not None:
                next_alarm = new_next_alarm

    return next_alarm
