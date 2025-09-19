import time
import logging
import datetime
import uuid

_LOGGER = logging.getLogger('pysomneo')

from .api import SomneoClient
from .const import *
from .util import alarms_to_dict, next_alarm, days_list_to_int, sunset_to_dict, player_to_dict

class Somneo(object):
    """ 
    Class represents the Somneo wake-up light.
    """

    def __init__(self, host=None, use_session = True, fast_interval = 5, slow_interval = 60):
        """Initialize."""
        self._host = host
        self._client = SomneoClient(host=host, use_session=use_session)
        # The fastest refresh interval is only relevant for sensor data and is 5 seconds by default
        self.fast_interval = fast_interval
        # The slowest refresh interval is relevant for all other data and is 15 minutes by default
        self.slow_interval = slow_interval

        self._last_sensor_fetch = 0
        self._last_slow_fetch = 0

        self.data = {}

        self.alarm_status = None
        self.light_data = None
        self.sensor_data = None
        self.sunset_data = None
        self.enabled_alarms = None
        self.time_alarms = None
        self.snoozetime = None
        self.player = None
        self._wake_light_themes = {}
        self._dusk_light_themes = {}
        self._wake_sound_themes = {}
        self._dusk_sound_themes = {}
        self.fetch_data()

    @property
    def wake_light_themes(self):
        """Get valid light curves for this light."""
        if len(self._wake_light_themes) == 0:
            self._fetch_themes()
        _LOGGER.debug(self._wake_light_themes)
        return self._wake_light_themes

    @property
    def dusk_light_themes(self):
        """Get valid dusk curves for this light."""
        if len(self._dusk_light_themes) == 0:
            self._fetch_themes()
        _LOGGER.debug(self._dusk_light_themes)
        return self._dusk_light_themes

    @property
    def wake_sound_themes(self):
        """Get valid wake-up sounds for this light."""
        if len(self._wake_sound_themes) == 0:
            self._fetch_themes()
        _LOGGER.debug(self._wake_sound_themes)
        return self._wake_sound_themes

    @property
    def dusk_sound_themes(self):
        """Get valid winddown sounds for this light."""
        if len(self._dusk_sound_themes) == 0:
            self._fetch_themes()
        _LOGGER.debug(self._dusk_sound_themes)
        return self._dusk_sound_themes

    def _fetch_themes(self):
        """Get themes."""
        themes = self._client.get_themes()
        self._wake_light_themes = themes["wake_light"]
        self._dusk_light_themes = themes["dusk_light"]
        self._wake_sound_themes = themes["wake_sound"]
        self._dusk_sound_themes = themes["dusk_sound"]
        self._fetch_sunset_data()

    def get_device_info(self):
        """Get device information via SomneoClient, fallback to defaults if unavailable."""
        # Default values if XML fetch fails
        device_info = {
            'manufacturer': 'Royal Philips Electronics',
            'model': 'Wake-up Light',
            'modelnumber': 'Unknown',
            'serial': str(uuid.uuid1())
        }

        # Use the client to get the XML as an ElementTree root
        root = self._client.get_description_xml()
        if root is not None:
            try:
                # Map XML elements to device_info
                device_info['manufacturer'] = root[1][2].text
                device_info['model'] = root[1][3].text
                device_info['modelnumber'] = root[1][4].text
                device_info['serial'] = root[1][6].text
            except (IndexError, AttributeError) as e:
                _LOGGER.warning("Failed to parse XML elements, using default device info: %s", e)

        _LOGGER.debug("Device info: %s", device_info)
        return device_info

    def fetch_data(self, force_slow_refresh = False):
        """Retrieve information from Somneo"""

        now = time.time()

        # Sensor data is usefull to fetch more often
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

    def _update_sensor_data(self, sensor_data):
        """ Update sensor data in data object"""
        self.data['temperature'] = sensor_data["temperature"]
        self.data['humidity'] = sensor_data["humidity"]
        self.data['luminance'] = sensor_data["luminance"]
        self.data['noise'] = sensor_data["noise"]

    def _fetch_sensor_data(self):
        """Fetch only the sensor data from Somneo"""
        sensor_data = self._client.get_sensor_data()
        self._update_sensor_data(sensor_data)

    def _update_light_data(self):
        """ Update light data in data object"""
        self.data['light_is_on'] = bool(self.light_data['onoff'])
        self.data['light_brightness'] = int(int(self.light_data['ltlvl']) / 25 * 255)
        self.data['nightlight_is_on'] = bool(self.light_data['ngtlt'])

    def _fetch_light_data(self):
        """Fetch only the light data from Somneo"""
        self.light_data = self._client.get_light_data()
        self._update_light_data()

    def _update_alarm_status(self):
        """ Update alarm status in data object"""
        self.data['somneo_status'] = STATUS.get(self.alarm_status['wusts'], 'unknown')
        self.data['display_always_on'] = bool(self.alarm_status['dspon'])
        self.data['display_brightness'] = int(self.alarm_status['brght'])

    def _fetch_alarm_status(self):
        """Fetch only the alarm status from Somneo"""
        self.alarm_status = self._client.get_alarm_status()
        self._update_alarm_status()

    def _update_sunset_data(self):
        """ Update sunset data in data object"""
        self.data['sunset'] = sunset_to_dict(self.sunset_data, self.dusk_light_themes, self.dusk_sound_themes)

    def _fetch_sunset_data(self):
        """Fetch only the sunset data from Somneo"""
        self.sunset_data = self._client.get_sunset_data()
        self._update_sunset_data()

    def _update_alarm_data(self):
        """ Update alarm data in data object"""
        self.data['alarms'] = alarms_to_dict(self.enabled_alarms, self.time_alarms)
        self.data['next_alarm'] = next_alarm(self.data['alarms'])

    def _fetch_alarm_data(self):
        """Fetch only the alarm data from Somneo"""
        self.enabled_alarms = self._client.get_enabled_alarms()
        self.time_alarms = self._client.get_time_alarms()
        self._update_alarm_data()

    def _update_snooze_time(self):
        """ Update snooze time in data object"""
        self.data['snooze_time'] = self.snoozetime['snztm']

    def _fetch_snooze_time(self):
        """Fetch only the snooze time from Somneo"""
        self.snoozetime = self._client.get_snooze_time()
        self._update_snooze_time()

    def _update_player_data(self):
        """ Update player data in data object"""
        self.data['player'] = player_to_dict(self.player)

    def _fetch_player_data(self):
        """Fetch only the player data from Somneo"""
        self.player = self._client.get_player_status()
        self._update_player_data()

    def toggle_light(self, state, brightness = None):
        """ Toggle the light on or off """
        if not self.light_data:
            self._fetch_light_data()

        payload = dict(self.light_data)
        payload['onoff'] = state
        payload['ngtlt'] = False
        if brightness:
            payload['ltlvl'] = int(brightness/255 * 25)

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self.light_data = self._client.put('wulgt', payload=payload)
        self._update_light_data()

    def toggle_night_light(self, state):
        """ Toggle the night light on or off """
        if not self.light_data:
            self._fetch_light_data()

        payload = dict(self.light_data)
        payload['onoff'] = False
        payload['ngtlt'] = state

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self.light_data = self._client.put('wulgt', payload=payload)
        self._update_light_data()

    def dismiss_alarm(self):
        """ Dismiss a running alarm. """
        self._client.put('wualm/alctr', payload={'disms':True})
        self._fetch_alarm_data()

    def snooze_alarm(self):
        """ Snooze a running alarm. """
        self._client.put('wualm/alctr', payload={'tapsz':True})
        self._fetch_alarm_data()

    def get_alarm_details(self, alarm):
        """ Get the alarm settings. """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        # Get alarm position
        alarm_pos = self.data['alarms'][alarm]['position']

        # Get current alarm settings
        return self._client.put('wualm',payload={'prfnr':alarm_pos})

    def toggle_alarm(self, alarm, status):
        """ Toggle the alarm on or off """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        # Send command to Somneo
        payload = {}
        payload['prfnr'] = self.data['alarms'][alarm]['position']
        payload['prfvs'] = True
        payload['prfen'] = status
        self._client.put('wualm/prfwu', payload=payload)

        # Update data
        self.data['alarms'][alarm]['enabled'] = status

    def set_alarm(self, alarm, time = None, days = None):
        """ Set the time and day of an alarm. """
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        # Adjust alarm settings
        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']    # Alarm number
        if time is not None:
            alarm_settings['almhr'] = time.hour                             # Alarm hour
            alarm_settings['almmn'] = time.minute                           # Alarm min
            self.data['alarms'][alarm]['time'] = time
        if days is not None:
            if isinstance(days, list):                                      # If a list of specific days
                days_int = days_list_to_int(days)
            elif days in DAYS_TYPE.values():                                # If predefined day
                days_int = [k for k in DAYS_TYPE if DAYS_TYPE[k]==days][0]
            else:                                                           # If not-defined, keep the same
                days_int = int(self.time_alarms['daynm'][alarm])
            alarm_settings['daynm'] = days_int                              # Set days to repeat the alarm
            self.data['alarms'][alarm]['days'] = days
            self.data['alarms'][alarm]['days_type'] = DAYS_TYPE.get(days_int,'custom')

        # Update powerwake
        if self.data['alarms'][alarm]['powerwake']:
            alarm_datetime = datetime.datetime.strptime(self.data['alarms'][alarm]['time'].isoformat(),'%H:%M:%S')
            powerwake_datetime = alarm_datetime + datetime.timedelta(minutes = self.data['alarms'][alarm]['powerwake_delta'])

            alarm_settings['pszhr'] = powerwake_datetime.hour
            alarm_settings['pszmn'] = powerwake_datetime.minute

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)
        self._update_alarm_data()

    def set_alarm_light(self, alarm, curve = 'sunny day', level = 20, duration = 30):
        """Adjust the lightcurve of the wake-up light"""
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()
        if not self.wake_light_themes:
            self._fetch_themes()

        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']  # Alarm number
        alarm_settings['ctype'] = self.wake_light_themes[curve]           # Light curve type
        alarm_settings['curve'] = level                                   # Light level (0 - 25, 0 is no light)
        alarm_settings['durat'] = duration                                # Duration in minutes (5 - 40)

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)

    def set_alarm_sound(self, alarm, source = 'wake-up', channel = 'forest birds', level = 12):
        """Adjust the alarm sound of the wake-up light"""
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()
        if not self.wake_sound_themes:
            self._fetch_themes()

        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']                                                               # Alarm number
        alarm_settings['snddv'] = SOUND_SOURCE_ALARM[source]                                                                           # Source (radio of wake-up)
        alarm_settings['sndch'] = self.wake_sound_themes[channel] if source == 'wake-up' else (' ' if source == 'off' else channel)    # Channel
        alarm_settings['sndlv'] = level                                                                                                # Sound level (1 - 25)

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)

    def set_alarm_powerwake(self, alarm, onoff = False, delta=0):
        """Set power wake"""
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_datetime = datetime.datetime.strptime(self.data['alarms'][alarm]['time'].isoformat(),'%H:%M:%S')
        powerwake_datetime = alarm_datetime + datetime.timedelta(minutes=delta)

        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']
        alarm_settings['pwrsz'] = 1 if onoff else 0
        alarm_settings['pszhr'] = powerwake_datetime.hour if onoff else 0
        alarm_settings['pszmn'] = powerwake_datetime.minute if onoff else 0

        self.data['alarms'][alarm]['powerwake'] = onoff
        self.data['alarms'][alarm]['powerwake_delta'] = delta if onoff else 0

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)
        self._update_alarm_data()

    def set_snooze_time(self, snooze_time = 9):
        """Adjust the snooze time (minutes) of all alarms"""
        self.snoozetime = self._client.put('wualm', payload={'snztm': snooze_time})
        self._update_snooze_time()

    def add_alarm(self, alarm):
        """Add alarm to the list"""
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']
        alarm_settings['prfvs'] = True  # Add alarm

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)
        self._update_alarm_data()

    def remove_alarm(self, alarm):
        """Remove alarm from the list"""
        if not self.enabled_alarms or not self.time_alarms:
            self._fetch_alarm_data()

        # Set default settings
        alarm_settings = {}
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']
        alarm_settings['prfen'] = False  # Alarm  disabled
        alarm_settings['prfvs'] = False  # Remove alarm from alarm list
        alarm_settings['almhr'] = int(7)  # Alarm hour
        alarm_settings['almmn'] = int(30)  # Alarm Min
        alarm_settings['pwrsz'] = 0  # disable PowerWake
        alarm_settings['pszhr'] = 0  # set power wake (hour)
        alarm_settings['pszmn'] = 0  # set power wake (min)
        alarm_settings['ctype'] = 0  # set the default sunrise ("Sunny day" if curve > 0 or "No light" if curve == 0) (0 sunyday, 1 island red, 2 nordic white)
        alarm_settings['curve'] = 20  # set light level (0-25)
        alarm_settings['durat'] = 30  # set sunrise duration (5-40)
        alarm_settings['daynm'] = 254 # set days to repeat the alarm
        alarm_settings['snddv'] = 'wus' # set the wake_up sound (fmr is radio)
        alarm_settings['sndch'] = '1'    # set sound channel (should be a string)
        alarm_settings['sndlv'] = 12   # set sound level

        # Send alarm settings
        self._client.put('wualm/prfwu', payload=alarm_settings)
        self._update_alarm_data()

    def toggle_sunset(self, status):
        """ Toggle the sunset feature on or off """
        if not self.sunset_data:
            self._fetch_sunset_data()
        payload = {}
        payload['onoff'] = status
        self.sunset_data = self._client.put('wudsk', payload=payload)
        self._update_sunset_data()

    def set_sunset(self, curve = None, level = None, duration = None, sound = None, volume = None):
        """Adjust the sunset settings of the wake-up light"""
        if not self.dusk_light_themes or not self.dusk_sound_themes or not self.sunset_data:
            self._fetch_themes()

        sunset_settings = self.sunset_data

        if duration:
            sunset_settings['durat'] = duration
        if curve:
            sunset_settings['ctype'] = self.dusk_light_themes[curve.lower()]
        if level:
            sunset_settings['curve'] = level
        if sound:
            if sound == 'off':
                sunset_settings['snddv'] = 'off'
            if sound[0:2] == 'fm':
                sunset_settings['snddv'] = 'fmr'
                sunset_settings['sndch'] = sound[3:]
            else:
                sunset_settings['snddv'] = 'dus'
                sunset_settings['sndch'] = self.dusk_sound_themes[sound.lower()]
        if volume:
            sunset_settings['sndlv'] = volume

        # Send alarm settings
        self.sunset_data = self._client.put('wudsk', payload=sunset_settings)
        self._update_sunset_data()

    def toggle_player(self, state: bool):
        """Toggle the audio player"""
        if not self.player:
            self._fetch_player_data()

        data = self.player
        data['onoff'] = state
        self.player = self._client.put('wuply', payload=data)
        self._update_player_data()

    def set_player_volume(self, volume: float):
        """Set the volume of the player (0..1)"""
        if volume < 0:
            volume = 0
        if volume > 1:
            volume = 1

        self.player = self._client.put('wuply', payload={'sdvol': int(volume * 24 + 1)})
        self._update_player_data()

    def set_player_source(self, source: str | int):
        """Set the source of the player, either 'aux' or preset 1..5"""
        if not self.player:
            self._fetch_player_data()

        previous_state = self.player['onoff']
        if source == 'aux' or source == 'AUX':
            self.player = self._client.put('wuply', payload=
                      {'snddv': 'aux',
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )
            # Repeat command for some unknown reason
            self.player = self._client.put('wuply', payload=
                      {'snddv': 'aux',
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )

        elif source in range(1,6):
            self.player = self._client.put('wuply', payload=
                      {'snddv': 'fmr',
                       'sndch': str(source),
                       'sndss': 0,
                       'onoff': self.player['onoff'],
                       'tempy': False
                       }
                )
        self._update_player_data()

    def set_display(self, state=None, brightness=None):
        """ Toggle the light on or off """
        if not self.alarm_status:
            self._fetch_alarm_status()

        payload = {}
        payload['dspon'] = state if state is not None else self.data['display_always_on']
        payload['brght'] = brightness if brightness is not None else self.data['display_brightness']

        self.alarm_status = self._client.put('wusts', payload=payload)
        self._update_alarm_status()

__all__ = ["Somneo", "SomneoClient"]
