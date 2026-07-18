"""
Main Somneo class, represents the state of the Somneo wake-up light
and provides methods to interact with it.
"""
from __future__ import annotations

import time
import logging
import datetime
import uuid
from typing import Any

from .api import SomneoClient
from .const import DAYS_TYPE, SOUND_SOURCE_ALARM, STATUS
from .util import (
    alarms_to_dict,
    get_next_alarm,
    days_list_to_int,
    sunset_to_dict,
    player_to_dict,
)

_LOGGER = logging.getLogger(__name__)


class Somneo:
    """Represents the Somneo wake-up light."""

    def __init__(
        self,
        host: str | None = None,
        use_session: bool = True,
        fast_interval: int = 5,
        slow_interval: int = 60,
    ) -> None:
        """Initialize Somneo instance.

        Args:
            host: IP address or hostname of the Somneo device
            use_session: Whether to use persistent session for connection pooling
            fast_interval: Refresh interval for sensor data in seconds (default: 5)
            slow_interval: Refresh interval for other data in seconds (default: 60)
        """
        self._host = host
        self._client = SomneoClient(host=host, use_session=use_session)
        # The fastest refresh interval is only relevant for sensor data and is 5 seconds by default
        self.fast_interval = fast_interval
        # The slowest refresh interval is relevant for all other data and is 15 minutes by default
        self.slow_interval = slow_interval

        self._last_sensor_fetch = 0
        self._last_slow_fetch = 0

        self.data: dict[str, Any] = {}

        self.alarm_status: dict[str, Any] | None = None
        self.light_data: dict[str, Any] | None = None
        self.sensor_data: dict[str, Any] | None = None
        self.sunset_data: dict[str, Any] | None = None
        self.enabled_alarms: dict[str, Any] | None = None
        self.time_alarms: dict[str, Any] | None = None
        self.snoozetime: dict[str, Any] | None = None
        self.player: dict[str, Any] | None = None
        self._wake_light_themes: dict[str, int] = {}
        self._dusk_light_themes: dict[str, int] = {}
        self._wake_sound_themes: dict[str, int] = {}
        self._dusk_sound_themes: dict[str, int] = {}

    @property
    def wake_light_themes(self) -> dict[str, int]:
        """Get valid light curves for this light."""
        if len(self._wake_light_themes) == 0:
            self._fetch_themes()
            _LOGGER.debug(self._wake_light_themes)
        return self._wake_light_themes

    @property
    def dusk_light_themes(self) -> dict[str, int]:
        """Get valid dusk curves for this light."""
        if len(self._dusk_light_themes) == 0:
            self._fetch_themes()
            _LOGGER.debug(self._dusk_light_themes)
        return self._dusk_light_themes

    @property
    def wake_sound_themes(self) -> dict[str, int]:
        """Get valid wake-up sounds for this light."""
        if len(self._wake_sound_themes) == 0:
            self._fetch_themes()
            _LOGGER.debug(self._wake_sound_themes)
        return self._wake_sound_themes

    @property
    def dusk_sound_themes(self) -> dict[str, int]:
        """Get valid winddown sounds for this light."""
        if len(self._dusk_sound_themes) == 0:
            self._fetch_themes()
            _LOGGER.debug(self._dusk_sound_themes)
        return self._dusk_sound_themes

    def _fetch_themes(self) -> None:
        """Get themes."""
        themes = self._client.get_themes()
        self._wake_light_themes = themes["wake_light"]
        self._dusk_light_themes = themes["dusk_light"]
        self._wake_sound_themes = themes["wake_sound"]
        self._dusk_sound_themes = themes["dusk_sound"]
        self._fetch_sunset_data()

    def get_device_info(self) -> dict[str, str]:
        """Get device information via SomneoClient, fallback to defaults if unavailable.

        Returns:
            Dictionary containing manufacturer, model, modelnumber, and serial
        """
        # Default values if XML fetch fails
        device_info: dict[str, str] = {
            "manufacturer": "Royal Philips Electronics",
            "model": "Wake-up Light",
            "modelnumber": "Unknown",
            "serial": str(uuid.uuid1()),
        }

        # Use the client to get the XML as an ElementTree root
        root = self._client.get_description_xml()
        if root is not None:
            try:
                # Map XML elements to device_info
                device_info["manufacturer"] = root[1][2].text
                device_info["model"] = root[1][3].text
                device_info["modelnumber"] = root[1][4].text
                device_info["serial"] = root[1][6].text
            except (IndexError, AttributeError) as e:
                _LOGGER.warning(
                    "Failed to parse XML elements, using default device info: %s", e
                )

        _LOGGER.debug("Device info: %s", device_info)
        return device_info

    def fetch_data(self, force_slow_refresh: bool = False) -> dict[str, Any]:
        """Retrieve information from Somneo.

        Args:
            force_slow_refresh: Force refresh of all data, not just fast interval

        Returns:
            Dictionary with all collected data
        """
        _LOGGER.debug("Calling Somneo.fetch_data()")
        now = time.time()

        # Sensor data is useful to fetch more often
        if now - self._last_sensor_fetch >= self.fast_interval:
            self._fetch_sensor_data()
            self._fetch_alarm_status()
            self._last_sensor_fetch = now

        if now - self._last_slow_fetch >= self.slow_interval or force_slow_refresh:
            self._fetch_light_data()
            self._fetch_sunset_data()
            self._fetch_alarm_data()
            self._fetch_snooze_time()
            self._fetch_player_data()
            self._last_slow_fetch = now

        return self.data

    def _update_sensor_data(self, sensor_data: dict[str, Any]) -> None:
        """Update sensor data in data object.

        Args:
            sensor_data: Dictionary with temperature, humidity, luminance, and noise
        """
        self.data["temperature"] = sensor_data["temperature"]
        self.data["humidity"] = sensor_data["humidity"]
        self.data["luminance"] = sensor_data["luminance"]
        self.data["noise"] = sensor_data["noise"]

    def _fetch_sensor_data(self) -> None:
        """Fetch only the sensor data from Somneo."""
        sensor_data = self._client.get_sensor_data()
        _LOGGER.debug("Fetched sensor data: %s", sensor_data)
        self._update_sensor_data(sensor_data)

    def _update_light_data(self) -> None:
        """Update light data in data object."""
        self.data["light_is_on"] = bool(self.light_data["onoff"])
        self.data["light_brightness"] = int(int(self.light_data["ltlvl"]) / 25 * 255)
        self.data["nightlight_is_on"] = bool(self.light_data["ngtlt"])

    def _fetch_light_data(self) -> None:
        """Fetch only the light data from Somneo."""
        self.light_data = self._client.get_light_data()
        _LOGGER.debug("Fetched light data: %s", self.light_data)
        self._update_light_data()

    def _update_alarm_status(self) -> None:
        """Update alarm status in data object."""
        self.data["somneo_status"] = STATUS.get(self.alarm_status["wusts"], "unknown")
        self.data["display_always_on"] = bool(self.alarm_status["dspon"])
        self.data["display_brightness"] = int(self.alarm_status["brght"])

    def _fetch_alarm_status(self) -> None:
        """Fetch only the alarm status from Somneo."""
        self.alarm_status = self._client.get_alarm_status()
        _LOGGER.debug("Fetched alarm status: %s", self.alarm_status)
        self._update_alarm_status()

    def _update_sunset_data(self) -> None:
        """Update sunset data in data object."""
        self.data["sunset"] = sunset_to_dict(
            self.sunset_data, self.dusk_light_themes, self.dusk_sound_themes
        )

    def _fetch_sunset_data(self) -> None:
        """Fetch only the sunset data from Somneo."""
        self.sunset_data = self._client.get_sunset_data()
        _LOGGER.debug("Fetched sunset data: %s", self.sunset_data)
        self._update_sunset_data()

    def _update_alarm_data(self) -> None:
        """Update alarm data in data object."""
        self.data["alarms"] = alarms_to_dict(self.enabled_alarms, self.time_alarms)
        self.data["next_alarm"] = get_next_alarm(self.data["alarms"])

    def _fetch_alarm_data(self) -> None:
        """Fetch only the alarm data from Somneo."""
        self.enabled_alarms = self._client.get_enabled_alarms()
        self.time_alarms = self._client.get_time_alarms()
        _LOGGER.debug("Fetched enabled alarms: %s", self.enabled_alarms)
        _LOGGER.debug("Fetched time alarms: %s", self.time_alarms)
        self._update_alarm_data()

    def _update_snooze_time(self) -> None:
        """Update snooze time in data object."""
        self.data["snooze_time"] = self.snoozetime["snztm"]

    def _fetch_snooze_time(self) -> None:
        """Fetch only the snooze time from Somneo."""
        self.snoozetime = self._client.get_snooze_time()
        _LOGGER.debug("Fetched snooze time: %s", self.snoozetime)
        self._update_snooze_time()

    def _update_player_data(self) -> None:
        """Update player data in data object."""
        self.data["player"] = player_to_dict(self.player, self.dusk_sound_themes)

    def _fetch_player_data(self) -> None:
        """Fetch only the player data from Somneo."""
        self.player = self._client.get_player_status()
        _LOGGER.debug("Fetched player status: %s", self.player)
        self._update_player_data()

    def toggle_light(self, state: bool, brightness: int | None = None) -> None:
        """Toggle the light on or off.

        Args:
            state: True to turn on, False to turn off
            brightness: Optional brightness level 0-255
        """
        if not self.light_data:
            self._fetch_light_data()

        payload = dict(self.light_data)
        payload["onoff"] = state
        payload["ngtlt"] = False
        if brightness:
            payload["ltlvl"] = int(brightness / 255 * 25)

        _LOGGER.debug("PUT toggle_light payload=%s", payload)
        response = self._client.modify_light(payload=payload)
        _LOGGER.debug("PUT toggle_light response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_light_data()
        self._fetch_sensor_data()

    def toggle_night_light(self, state: bool) -> None:
        """Toggle the night light on or off.

        Args:
            state: True to turn on, False to turn off
        """
        if not self.light_data:
            self._fetch_light_data()

        payload = dict(self.light_data)
        payload["onoff"] = False
        payload["ngtlt"] = state

        _LOGGER.debug("PUT toggle_night_light payload=%s", payload)
        response = self._client.modify_light(payload=payload)
        _LOGGER.debug("PUT toggle_night_light response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_light_data()
        self._fetch_sensor_data()

    def dismiss_alarm(self) -> None:
        """Dismiss a running alarm."""
        payload = {"disms": True}
        _LOGGER.debug("PUT dismiss_alarm payload=%s", payload)
        response = self._client.modify_running_alarm(payload=payload)
        _LOGGER.debug("PUT dismiss_alarm response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def snooze_alarm(self) -> None:
        """Snooze a running alarm."""
        payload = {"tapsz": True}
        _LOGGER.debug("PUT snooze_alarm payload=%s", payload)
        response = self._client.modify_running_alarm(payload=payload)
        _LOGGER.debug("PUT snooze_alarm response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()
        self._fetch_snooze_time()

    def get_alarm_details(self, alarm: str) -> dict[str, Any]:
        """Get the alarm settings.

        Args:
            alarm: Alarm identifier

        Returns:
            Alarm details dictionary
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_pos = self.data["alarms"][alarm]["position"]
        payload = {"prfnr": alarm_pos}
        _LOGGER.debug("PUT get_alarm_details payload=%s", payload)
        response = self._client.modify_alarm_details(payload=payload)
        _LOGGER.debug("PUT get_alarm_details response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()
        return response

    def toggle_alarm(self, alarm: str, status: bool) -> None:
        """Toggle the alarm on or off.

        Args:
            alarm: Alarm identifier
            status: True to enable, False to disable
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        payload = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "prfvs": True,
            "prfen": status,
        }
        _LOGGER.debug("PUT toggle_alarm payload=%s", payload)
        response = self._client.modify_alarm_wake_up_configuration(payload=payload)
        _LOGGER.debug("PUT toggle_alarm response=%s", response)

        self.data["alarms"][alarm]["enabled"] = status
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def set_alarm(
        self,
        alarm: str,
        v_time: datetime.time | None = None,
        days: list[str] | str | None = None,
    ) -> None:
        """Set the time and day of an alarm.

        Args:
            alarm: Alarm identifier
            v_time: Time to set for alarm
            days: Days to set alarm (list of day names or single type string)
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_settings: dict[str, Any] = {"prfnr": self.data["alarms"][alarm]["position"]}
        if v_time is not None:
            alarm_settings["almhr"] = v_time.hour
            alarm_settings["almmn"] = v_time.minute
            self.data["alarms"][alarm]["time"] = v_time
        if days is not None:
            if isinstance(days, list):
                days_int = days_list_to_int(days)
            elif days in DAYS_TYPE.values():
                days_int = next(k for k, v in DAYS_TYPE.items() if v == days)
            else:
                days_int = int(self.time_alarms["daynm"][alarm])
            alarm_settings["daynm"] = days_int
            self.data["alarms"][alarm]["days"] = days
            self.data["alarms"][alarm]["days_type"] = DAYS_TYPE.get(days_int, "custom")

        if self.data["alarms"][alarm]["powerwake"]:
            alarm_dt = datetime.datetime.strptime(
                self.data["alarms"][alarm]["time"].isoformat(), "%H:%M:%S"
            )
            pw_dt = alarm_dt + datetime.timedelta(
                minutes=self.data["alarms"][alarm]["powerwake_delta"]
            )
            alarm_settings["pszhr"] = pw_dt.hour
            alarm_settings["pszmn"] = pw_dt.minute

        _LOGGER.debug("PUT set_alarm payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT set_alarm response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def set_alarm_light(
        self, alarm: str, curve: str = "sunny day", level: int = 20, duration: int = 30
    ) -> None:
        """Adjust the light curve of the wake-up light.

        Args:
            alarm: Alarm identifier
            curve: Light curve name (default: "sunny day")
            level: Brightness level (default: 20)
            duration: Duration in minutes (default: 30)
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()
        if not self.wake_light_themes:
            self._fetch_themes()

        alarm_settings: dict[str, Any] = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "ctype": self.wake_light_themes[curve],
            "curve": level,
            "durat": duration,
        }

        _LOGGER.debug("PUT set_alarm_light payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT set_alarm_light response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()
        self._fetch_light_data()
        self._fetch_sensor_data()

    def set_alarm_sound(
        self,
        alarm: str,
        source: str = "wake-up",
        channel: str = "forest birds",
        level: int = 12,
    ) -> None:
        """Adjust the alarm sound of the wake-up light.

        Args:
            alarm: Alarm identifier
            source: Sound source type (default: "wake-up")
            channel: Sound channel name (default: "forest birds")
            level: Sound level (default: 12)
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()
        if not self.wake_sound_themes:
            self._fetch_themes()

        alarm_settings: dict[str, Any] = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "snddv": SOUND_SOURCE_ALARM[source],
            "sndch": (
                self.wake_sound_themes[channel]
                if source == "wake-up"
                else (" " if source == "off" else channel)
            ),
            "sndlv": level,
        }

        _LOGGER.debug("PUT set_alarm_sound payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT set_alarm_sound response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()
        self._fetch_player_data()
        self._fetch_sensor_data()

    def set_alarm_powerwake(self, alarm: str, onoff: bool = False, delta: int = 0) -> None:
        """Set power wake.

        Args:
            alarm: Alarm identifier
            onoff: Enable (True) or disable (False) power wake
            delta: Minutes before alarm to wake display (default: 0)
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_datetime = datetime.datetime.strptime(
            self.data["alarms"][alarm]["time"].isoformat(), "%H:%M:%S"
        )
        powerwake_datetime = alarm_datetime + datetime.timedelta(minutes=delta)

        alarm_settings: dict[str, Any] = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "pwrsz": 1 if onoff else 0,
            "pszhr": powerwake_datetime.hour if onoff else 0,
            "pszmn": powerwake_datetime.minute if onoff else 0,
        }

        self.data["alarms"][alarm]["powerwake"] = onoff
        self.data["alarms"][alarm]["powerwake_delta"] = delta if onoff else 0

        _LOGGER.debug("PUT set_alarm_powerwake payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT set_alarm_powerwake response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def set_snooze_time(self, snooze_time: int = 9) -> None:
        """Adjust the snooze time (minutes) of all alarms.

        Args:
            snooze_time: Snooze time in minutes (default: 9)
        """
        payload = {"snztm": snooze_time}
        _LOGGER.debug("PUT set_snooze_time payload=%s", payload)
        response = self._client.modify_alarm_details(payload=payload)
        _LOGGER.debug("PUT set_snooze_time response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_snooze_time()

    def add_alarm(self, alarm: str) -> None:
        """Add alarm to the list.

        Args:
            alarm: Alarm identifier
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_settings: dict[str, Any] = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "prfvs": True,
        }

        _LOGGER.debug("PUT add_alarm payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT add_alarm response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def remove_alarm(self, alarm: str) -> None:
        """Remove alarm from the list.

        Args:
            alarm: Alarm identifier
        """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_settings: dict[str, Any] = {
            "prfnr": self.data["alarms"][alarm]["position"],
            "prfen": False,
            "prfvs": False,
            "almhr": 7,
            "almmn": 30,
            "pwrsz": 0,
            "pszhr": 0,
            "pszmn": 0,
            "ctype": 0,
            "curve": 20,
            "durat": 30,
            "daynm": 254,
            "snddv": "wus",
            "sndch": "1",
            "sndlv": 12,
        }

        _LOGGER.debug("PUT remove_alarm payload=%s", alarm_settings)
        response = self._client.modify_alarm_wake_up_configuration(
            payload=alarm_settings
        )
        _LOGGER.debug("PUT remove_alarm response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_data()

    def toggle_sunset(self, status: bool) -> None:
        """Toggle the sunset feature on or off.

        Args:
            status: True to enable, False to disable
        """
        if not self.sunset_data:
            self._fetch_sunset_data()

        payload = {"onoff": status}
        _LOGGER.debug("PUT toggle_sunset payload=%s", payload)
        response = self._client.modify_sunset(payload=payload)
        _LOGGER.debug("PUT toggle_sunset response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_sunset_data()
        self._fetch_player_data()
        self._fetch_alarm_status()
        self._fetch_sensor_data()

    def set_sunset(
        self,
        curve: str | None = None,
        level: int | None = None,
        duration: int | None = None,
        sound: str | None = None,
        volume: int | None = None,
    ) -> None:
        """Adjust the sunset settings.

        Args:
            curve: Light curve name
            level: Brightness level
            duration: Duration in minutes
            sound: Sound name
            volume: Volume level
        """
        if (
            not self.dusk_light_themes
            or not self.dusk_sound_themes
            or not self.sunset_data
        ):
            self._fetch_themes()

        sunset_settings = dict(self.sunset_data)

        if duration:
            sunset_settings["durat"] = duration
        if curve:
            sunset_settings["ctype"] = self.dusk_light_themes[curve.lower()]
        if level:
            sunset_settings["curve"] = level
        if sound:
            if sound == "off":
                sunset_settings["snddv"] = "off"
            elif sound.upper().startswith("FM"):
                sunset_settings["snddv"] = "fmr"
                sunset_settings["sndch"] = sound[3:]
            elif sound.lower() in self.dusk_sound_themes:
                sunset_settings["snddv"] = "dus"
                sunset_settings["sndch"] = self.dusk_sound_themes[sound.lower()]
            else:
                _LOGGER.error("Invalid sound specified: %s", sound)
                raise ValueError(f"Unsupported sunset sound: {sound}")
        if volume:
            sunset_settings["sndlv"] = volume

        if bool(sunset_settings["onoff"]):
            _LOGGER.debug(
                "Sunset is already on, to modify it "
                "we need to turn it off first otherwise changes are ignored"
            )
            self.toggle_sunset(False)
            time.sleep(1)  # short delay to allow the device to process

        _LOGGER.debug("PUT set_sunset payload=%s", sunset_settings)
        response = self._client.modify_sunset(payload=sunset_settings)
        _LOGGER.debug("PUT set_sunset response=%s", response)
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        time.sleep(0.1)  # Short delay to allow the device to process
        self._fetch_sunset_data()
        self._fetch_player_data()
        self._fetch_alarm_status()
        self._fetch_sensor_data()

    def toggle_player(self, state: bool) -> None:
        """Toggle the audio player.

        Args:
            state: True to turn on, False to turn off
        """
        if not self.player:
            self._fetch_player_data()

        data = dict(self.player)
        data["onoff"] = state

        _LOGGER.debug("PUT toggle_player payload=%s", data)
        response = self._client.modify_player(payload=data)
        _LOGGER.debug("PUT toggle_player response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_player_data()
        # It might also affect the sunset state
        self._fetch_sunset_data()
        self._fetch_alarm_status()
        self._fetch_sensor_data()

    def set_player_volume(self, volume: float) -> None:
        """Set the volume of the player (0..1).

        Args:
            volume: Volume level between 0.0 and 1.0
        """
        volume = min(max(volume, 0), 1)

        payload = {"sdvol": int(volume * 24 + 1)}
        _LOGGER.debug("PUT set_player_volume payload=%s", payload)
        response = self._client.modify_player(payload=payload)
        _LOGGER.debug("PUT set_player_volume response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_player_data()
        self._fetch_sensor_data()

    def set_player_source(self, source: str | int) -> None:
        """Set the source of the player.

        Args:
            source: Player source - either 'aux', preset 1-5 (int or 'FM N' string),
                    or one of the dusk sound theme names
        """
        if not self.player:
            self._fetch_player_data()

        # Support legacy int sources (1..5 = FM presets)
        if isinstance(source, int):
            if source in range(1, 6):
                source = f"FM {source}"
            else:
                raise ValueError(f"Unsupported player source: {source}")

        previous_sndch = self.player["sndch"]
        sunset_settings = dict(self.sunset_data)

        snddv = None
        sndch = None

        if source.upper() == "AUX":
            snddv = "aux"
            sndch = "1"
        elif source.upper().startswith("FM "):
            snddv = "fmr"
            sndch = source.split(" ")[1]
        elif source.lower() in self.dusk_sound_themes:
            snddv = "dus"
            sndch = self.dusk_sound_themes[source.lower()]
        else:
            _LOGGER.error("Invalid source specified: %s", source)
            raise ValueError(f"Unsupported player source: {source}")

        payload: dict[str, Any] = {
            "snddv": snddv,
            "sndch": sndch,
            "sndss": 0,
            "onoff": True,
            "tempy": False,
        }

        _LOGGER.debug("PUT set_player_source payload=%s", payload)
        response = self._client.modify_player(payload=payload)
        _LOGGER.debug("PUT set_player_source response=%s", response)

        if bool(sunset_settings["onoff"]) and previous_sndch != sndch:
            _LOGGER.debug(
                "Sunset is already on and we modified the sound, "
                "to apply these we need to modify sunset endpoint"
            )
            self.set_sunset(sound=source)

        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_player_data()
        # It might also affect the sunset state
        self._fetch_sunset_data()
        self._fetch_alarm_status()
        self._fetch_sensor_data()

    def set_display(
        self, state: bool | None = None, brightness: int | None = None
    ) -> None:
        """Adjust the display.

        Args:
            state: Display always on (True/False)
            brightness: Display brightness level (0-255)
        """
        if not self.alarm_status:
            self._fetch_alarm_status()

        payload = {
            "dspon": state if state is not None else self.data["display_always_on"],
            "brght": (
                brightness
                if brightness is not None
                else self.data["display_brightness"]
            ),
        }

        _LOGGER.debug("PUT set_display payload=%s", payload)
        response = self._client.modify_alarm_status(payload=payload)
        _LOGGER.debug("PUT set_display response=%s", response)
        time.sleep(0.1)  # Short delay to allow the device to process
        # The response of the put command is incomplete, so sent a new request
        # before updating internal state
        self._fetch_alarm_status()
        self._fetch_sensor_data()
