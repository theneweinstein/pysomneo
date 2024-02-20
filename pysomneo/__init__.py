import requests
import urllib3
import xml.etree.ElementTree as ET
import logging
import datetime
import uuid

_LOGGER = logging.getLogger('pysomneo')

from .api import get, put, SomneoSession
from .const import *
from .util import alarms_to_dict, next_alarm, days_list_to_int, sunset_to_dict, player_to_dict

class Somneo(object):
    """ 
    Class represents the Somneo wake-up light.
    """

    alarm_status = None
    light_data = None
    sensor_data = None
    sunset_data = None
    enabled_alarms = None
    time_alarms = None
    snoozetime = None
    player = None
    data = None
    _wake_light_themes = {}
    _dusk_light_themes = {}
    _wake_sound_themes = {}
    _dusk_sound_themes = {}
    

    def __init__(self, host=None):
        """Initialize."""
        urllib3.disable_warnings()
        self._host = host
        self._session = SomneoSession(base_url='https://' + host + '/di/v1/products/1/')
        self.version = None
        
    @property
    def wake_light_themes(self):
        """Get valid light curves for this light."""
        if len(self._wake_light_themes) == 0:
            self._get_themes()
        _LOGGER.debug(self._wake_light_themes)
        return self._wake_light_themes
    
    @property
    def dusk_light_themes(self):
        """Get valid dusk curves for this light."""
        if len(self._dusk_light_themes) == 0:
            self._get_themes()
        _LOGGER.debug(self._dusk_light_themes)
        return self._dusk_light_themes
    
    @property
    def wake_sound_themes(self):
        """Get valid wake-up sounds for this light."""
        if len(self._wake_sound_themes) == 0:
            self._get_themes()
        _LOGGER.debug(self._wake_sound_themes)
        return self._wake_sound_themes
    
    @property
    def dusk_sound_themes(self):
        """Get valid winddown sounds for this light."""
        if len(self._dusk_sound_themes) == 0:
            self._get_themes()
        _LOGGER.debug(self._dusk_sound_themes)
        return self._dusk_sound_themes

    def _get(self, url):
        return get(self._session, url)
    
    def _put(self, url, payload=None):
        return put(self._session, url, payload=payload)
    
    def _get_themes(self):
        """Get themes."""
        response = self._get('files/lightthemes')
        for idx, item in enumerate(response.values()):
            if item['name']:
                self._wake_light_themes.update({item['name'].lower(): idx})

        response = self._get('files/dusklightthemes')
        for idx, item in enumerate(response.values()):
            if item['name']:
                self._dusk_light_themes.update({item['name'].lower(): idx})

        response = self._get('files/wakeup')
        for idx, item in enumerate(response.values()):
            if item['name']:
                self._wake_sound_themes.update({item['name'].lower(): idx+1})

        response = self._get('files/winddowndusk')
        for idx, item in enumerate(response.values()):
            if item['name']:
                self._dusk_sound_themes.update({item['name'].lower(): idx+1})

        _LOGGER.debug("Retrieve themes.")

    def get_device_info(self):
        """ Get Device information """
        try:
            response = self._session.request('GET', 'https://' + self._host + '/upnp/description.xml', verify=False, 
                                             timeout=20)
            
            # Check if HTTPS gave valid response, otherwise probe http
            try:
                ET.fromstring(response.content)
            except:
                response = self._session.request('GET', 'http://' + self._host + '/upnp/description.xml', verify=False, 
                                                 timeout=20)
        except requests.Timeout:
            _LOGGER.error('Connection to Somneo timed out.')
            raise
        except requests.RequestException:
            _LOGGER.error('Error connecting to Somneo.')
            raise

        _LOGGER.debug(response.content)

        # If no valid xml obtained from https and http, use default values.
        try:
            root = ET.fromstring(response.content)

            device_info = dict()
            device_info['manufacturer'] = root[1][2].text
            device_info['model'] = root[1][3].text
            device_info['modelnumber'] = root[1][4].text
            device_info['serial'] = root[1][6].text
        except:
            device_info = dict()
            device_info['manufacturer'] = 'Royal Philips Electronics'
            device_info['model'] = 'Wake-up Light'
            device_info['modelnumber'] = 'Unknown'
            device_info['serial'] = str(uuid.uuid1())

        return device_info

    def fetch_data(self):
        """Retrieve information from Somneo"""
        
        self.alarm_status = self._get('wusts')
        self.light_data = self._get('wulgt')
        self.sensor_data = self._get('wusrd')
        self.sunset_data = self._get('wudsk')
        self.enabled_alarms = self._get('wualm/aenvs')
        self.time_alarms = self._get('wualm/aalms')
        self.snoozetime = self._get('wualm')
        self.player = self._get("wuply")

        self.data = dict()
    
        # Somneo status
        self.data['somneo_status'] = STATUS.get(self.alarm_status['wusts'], 'unknown')

        # Light status
        self.data['light_is_on'] = bool(self.light_data['onoff'])
        self.data['light_brightness'] = int(int(self.light_data['ltlvl']) / 25 * 255)
        self.data['nightlight_is_on'] = bool(self.light_data['ngtlt'])

        # Alarms information
        self.data['alarms'] = alarms_to_dict(self.enabled_alarms, self.time_alarms)
        self.data['snooze_time'] = self.snoozetime['snztm']
        self.data['next_alarm'] = next_alarm(self.data['alarms'])

        # Sunset information
        self.data['sunset'] = sunset_to_dict(self.sunset_data, self.dusk_light_themes, self.dusk_sound_themes)

        # Get player information
        self.data['player'] = player_to_dict(self.player) 

        # Sensor information
        self.data['temperature'] = self.sensor_data['mstmp']
        self.data['humidity'] = self.sensor_data['msrhu']
        self.data['luminance'] = self.sensor_data['mslux']
        self.data['noise'] = self.sensor_data['mssnd']

        return self.data
    
    def toggle_light(self, state, brightness = None):
        """ Toggle the light on or off """
        if not self.light_data:
            self.fetch_data()
        
        payload = self.light_data
        payload['onoff'] = state
        payload['ngtlt'] = False
        if brightness:
            payload['ltlvl'] = int(brightness/255 * 25)

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self.light_data = self._put('wulgt', payload = payload)

    def toggle_night_light(self, state):
        """ Toggle the light on or off """
        if not self.light_data:
            self.fetch_data()

        payload = self.light_data
        payload['onoff'] = False
        payload['ngtlt'] = state

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self.light_data = self._put('wulgt', payload=payload)

    def dismiss_alarm(self):
        """ Dismiss a running alarm. """
        self._put('wualm/alctr', payload={'disms':True})

    def snooze_alarm(self):
        """ Snooze a running alarm. """
        self._put('wualm/alctr', payload={'tapsz':True})

    def get_alarm_details(self, alarm):
        """ Get the alarm settings. """
        if not self.data:
            self.fetch_data()

        # Get alarm position
        alarm_pos = self.data['alarms'][alarm]['position']

        # Get current alarm settings
        return self._put('wualm',payload={'prfnr':alarm_pos})
    
    def toggle_alarm(self, alarm, status):
        """ Toggle the alarm on or off """
        if not self.data:
            self.fetch_data()
    
        # Send command to Somneo
        payload = dict()
        payload['prfnr'] = self.data['alarms'][alarm]['position']
        payload['prfvs'] = True
        payload['prfen'] = status
        self._put('wualm/prfwu', payload=payload)

        # Update data
        self.data['alarms'][alarm]['enabled'] = status

    def set_alarm(self, alarm, time = None, days = None):
        """ Set the time and day of an alarm. """
        if not self.data:
            self.fetch_data()

        # Adjust alarm settings
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']    # Alarm number
        if time is not None: 
            alarm_settings['almhr'] = time.hour                             # Alarm hour
            alarm_settings['almmn'] = time.minute                           # Alarm min
            self.data['alarms'][alarm]['time'] = time
        if days is not None:
            if type(days) == list:                                          # If a list of specific days
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
        self._put('wualm/prfwu', payload=alarm_settings)
    
    def set_alarm_light(self, alarm, curve = 'sunny day', level = 20, duration = 30):
        """Adjust the lightcurve of the wake-up light"""
        if not self.data:
            self.fetch_data()

        alarm_settings = dict()
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']    # Alarm number
        alarm_settings['ctype'] = self.wake_light_themes[curve]                   # Light curve type
        alarm_settings['curve'] = level                                 # Light level (0 - 25, 0 is no light)
        alarm_settings['durat'] = duration                              # Duration in minutes (5 - 40)

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings)

    def set_alarm_sound(self, alarm, source = 'wake-up', channel = 'forest birds', level = 12):
        """Adjust the alarm sound of the wake-up light"""
        if not self.data:
            self.fetch_data()

        alarm_settings = dict()
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']                                # Alarm number
        alarm_settings['snddv'] = SOUND_SOURCE_ALARM[source]                                            # Source (radio of wake-up)
        alarm_settings['sndch'] = self.wake_sound_themes[channel] if source == 'wake-up' else (' ' if source == 'off' else channel)    # Channel
        alarm_settings['sndlv'] = level                                                                 # Sound level (1 - 25)

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def set_alarm_powerwake(self, alarm, onoff = False, delta=0):
        """Set power wake"""
        if not self.data:
            self.fetch_data()

        alarm_datetime = datetime.datetime.strptime(self.data['alarms'][alarm]['time'].isoformat(),'%H:%M:%S')
        powerwake_datetime = alarm_datetime + datetime.timedelta(minutes=delta)

        alarm_settings = dict()
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']
        alarm_settings['pwrsz'] = 1 if onoff else 0
        alarm_settings['pszhr'] = powerwake_datetime.hour if onoff else 0
        alarm_settings['pszmn'] = powerwake_datetime.minute if onoff else 0

        self.data['alarms'][alarm]['powerwake'] = onoff
        self.data['alarms'][alarm]['powerwake_delta'] = delta if onoff else 0

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def set_snooze_time(self, snooze_time = 9):
        """Adjust the snooze time (minutes) of all alarms"""
        self.snoozetime = self._put('wualm', payload={'snztm': snooze_time})

    def add_alarm(self, alarm):
        """Add alarm to the list"""
        if not self.data:
            self.fetch_data()

        alarm_settings = dict()
        alarm_settings['prfnr'] = self.data['alarms'][alarm]['position']
        alarm_settings['prfvs'] = True  # Add alarm

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def remove_alarm(self, alarm):
        """Remove alarm from the list"""
        if not self.data:
            self.fetch_data()

        # Set default settings
        alarm_settings = dict()
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
        self._put('wualm/prfwu', payload=alarm_settings) 

    def toggle_sunset(self, status):
        """ Toggle the sunset feature on or off """
        payload = dict()
        payload['onoff'] = status
        self.sunset_data = self._put('wudsk', payload=payload)

    def set_sunset(self, curve = None, level = None, duration = None, sound = None, volume = None):
        """Adjust the sunset settings of the wake-up light"""
        if not self.sensor_data:
            self.fetch_data()

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
        self.sunset_data = self._put('wudsk', payload=sunset_settings)
    
    def toggle_player(self, state: bool):
        """Toggle the audio player"""
        if not self.player:
            self.fetch_data()

        data = self.player
        data['onoff'] = state
        self.player = self._put('wuply', payload=data)

    def set_player_volume(self, volume: float):
        """Set the volume of the player (0..1)"""
        if volume < 0:
            volume = 0
        if volume > 1:
            volume = 1

        self.player = self._put('wuply', payload={'sdvol': int(volume * 24 + 1)})

    def set_player_source(self, source: str | int):
        """Set the source of the player, either 'aux' or preset 1..5"""
        if not self.player:
            self.fetch_data()

        previous_state = self.player['onoff']
        if source == 'aux' or source == 'AUX':
            self.player = self._put('wuply', payload=
                      {'snddv': 'aux', 
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )
            # Repeat command for some unknown reason
            self.player = self._put('wuply', payload=
                      {'snddv': 'aux', 
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )

        elif source in range(1,6):
            self.player = self._put('wuply', payload=
                      {'snddv': 'fmr', 
                       'sndch': str(source),
                       'sndss': 0,
                       'onoff': self.player['onoff'],
                       'tempy': False
                       }
                )
