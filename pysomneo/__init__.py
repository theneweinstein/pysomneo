import requests
import urllib3
import json
import xml.etree.ElementTree as ET
import logging
import datetime
import uuid

_LOGGER = logging.getLogger('pysomneo')

WORKDAYS_BINARY_MASK = 62
WEEKEND_BINARY_MASK = 192

LIGHT_CURVES = {'sunny day': 0, 'island red': 1,'nordic white': 2}
SOUND_SOURCE = {'wake-up': 'wus', 'radio': 'fmr', 'off': 'off'}
SOUND_CHANNEL = {'forest birds': '1', 
                    'summer birds': '2',
                    'buddha wakeup': '3',
                    'morning alps': '4',
                    'yoga harmony': '5',
                    'nepal bowls': '6',
                    'summer lake': '7',
                    'ocean waves': '8',
                    }
SOURCES = {'AUX': 'aux', 'FM 1': 1,'FM 2': 2,'FM 3': 3,'FM 4': 4,'FM 5': 5, 'Other': 'other'}

DAYS = {0: 'tomorrow', 2: 'mon', 4: 'tue', 8: 'wed', 16: 'thu', 32: 'fri', 64: 'sat', 128: 'sun'}

class Somneo(object):
    """ 
    Class represents the Somneo wake-up light.
    """

    def __init__(self, host=None, use_session=True):
        """Initialize."""
        urllib3.disable_warnings()
        self.host = host
        self._base_url = 'https://' + host + '/di/v1/products/1/'
        self._requests_session = None
        self._use_session = use_session

        self.light_data = None
        self.sensor_data = None
        self.sunset_data = None
        self.alarm_data = dict()
        self.snoozetime = None
        self.player = None

    @property
    def _session(self):
        if self._use_session:
            if self._requests_session is None:
                self._requests_session = requests.Session()
            return self._requests_session
        else:
            return requests

    def get_device_info(self):
        """ Get Device information """
        try:
            response = self._session.request('GET', 'https://' + self.host + '/upnp/description.xml', verify=False, 
                                             timeout=20)
            
            # Check if HTTPS gave valid response, otherwise probe http
            try:
                ET.fromstring(response.content)
            except:
                response = self._session.request('GET', 'http://' + self.host + '/upnp/description.xml', verify=False, 
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

    def _internal_call(self, method, url, headers, payload):
        """Call to the API."""
        args = dict()
        url = self._base_url + url

        if payload:
            args['data'] = json.dumps(payload)

        if headers:
            args['headers'] = headers

        while True:
            try:
                r = self._session.request(method, url, verify=False, timeout=20, **args)
            except requests.Timeout:
                _LOGGER.error('Connection to Somneo timed out.')
                raise
            except requests.ConnectionError:
                continue
            except requests.RequestException:
                _LOGGER.error('Error connecting to Somneo.')
                raise
            else:
                if r.status_code == 422:
                    _LOGGER.error('Invalid URL.')
                    raise Exception("Invalid URL.")
            break

        return r.json()

    def _get(self, url, args=None, payload=None):
        """Get request."""
        return self._internal_call('GET', url, None, payload)

    def _put(self, url, args=None, payload=None):
        """Put request."""
        return self._internal_call('PUT', url, {"Content-Type": "application/json"}, payload)

    def update(self):
        """Get the latest update from Somneo."""

        # Get alarm status
        alarm_status = self._get('wusts')
        if alarm_status['wusts'] == 1:
            self.alarm_status = 'off'
        elif alarm_status['wusts'] == 2321:
            self.alarm_status = 'snooze'
        elif alarm_status['wusts'] == 2309:
            self.alarm_status = 'wake-up'
        elif alarm_status['wusts'] == 2817:
            self.alarm_status = 'on'
        else:
            self.alarm_status = 'unknown'

        # Get light information
        self.light_data = self._get('wulgt')

        # Get sensor data
        self.sensor_data = self._get('wusrd')
        
        # Get sunset data
        self.sunset_data = self._get('wudsk')

        # Get enabled alarm data
        enabled_alarms = self._get('wualm/aenvs')
        time_alarms = self._get('wualm/aalms')

        # Get snoozetime
        self.snoozetime = self.get_snooze_time()

        for alarm, enabled in enumerate(enabled_alarms['prfen']):
            alarm_name = 'alarm' + str(alarm)
            #alarm_settings = self._put('wualm',payload={'prfnr': alarm + 1})
            self.alarm_data[alarm_name] = dict()
            self.alarm_data[alarm_name]['position'] = alarm + 1
            self.alarm_data[alarm_name]['enabled'] = bool(enabled)
            self.alarm_data[alarm_name]['time'] = datetime.time(int(time_alarms['almhr'][alarm]),
                                                                int(time_alarms['almmn'][alarm]))
            self.alarm_data[alarm_name]['days'] = int(time_alarms['daynm'][alarm])
            self.alarm_data[alarm_name]['powerwake'] = bool(enabled_alarms['pwrsv'][3*alarm])
            if bool(enabled_alarms['pwrsv'][3*alarm]):
                self.alarm_data[alarm_name]['powerwake_delta'] = max(0, 60 * int(enabled_alarms['pwrsv'][3*alarm+1]) + int(enabled_alarms['pwrsv'][3*alarm+2])
                                                                - 60 * int(time_alarms['almhr'][alarm]) - int(time_alarms['almmn'][alarm]))
            else:
                self.alarm_data[alarm_name]['powerwake_delta'] = 0

        # Get player information
        self.player = self._get("wuply")
        

    def fetch_data(self):
        """Fetch the latest data from Somneo."""
        
        # Perform update
        self.update()

        # Store info in data structure compatible with home assistant coordinator.
        data = dict()
        data['light_is_on'], data['light_brightness'] = self.light_status()
        data['nightlight_is_on'] = self.night_light_status()
        data['alarms'] = self.alarms()

        data['alarm_status'] = self.alarm_status

        data['alarms_hour'] = dict()
        data['alarms_minute'] = dict()
        data['alarms_day'] = dict()
        data['alarm_day_list'] = dict()
        data['powerwake'] = dict()
        data['powerwake_delta'] = dict()
        for alarm in data['alarms']:
            alarm_datetime = datetime.datetime.strptime(self.alarm_data[alarm]['time'].isoformat(),'%H:%M:%S')
            data['alarms_hour'][alarm] = alarm_datetime.hour
            data['alarms_minute'][alarm] = alarm_datetime.minute
            if self.is_everyday(alarm):
                data['alarms_day'][alarm] = 'daily'
            elif self.is_workday(alarm):
                data['alarms_day'][alarm] = 'workdays'
            elif self.is_weekend(alarm):
                data['alarms_day'][alarm] = 'weekend'
            elif self.is_tomorrow(alarm):
                data['alarms_day'][alarm] = 'tomorrow'
            else:
                data['alarms_day'][alarm] = 'custom'
            data['alarm_day_list'][alarm] = self.get_alarm_days(alarm)
            data['powerwake'][alarm] = self.alarm_data[alarm]['powerwake']
            data['powerwake_delta'][alarm] = self.alarm_data[alarm]['powerwake_delta']

        data['snooze_time'] = self.snoozetime
        data['next_alarm'] = datetime.datetime.fromisoformat(self.next_alarm()).astimezone() if self.next_alarm() else None

        data['temperature'] = self.temperature()
        data['humidity'] = self.humidity()
        data['luminance'] = self.luminance()
        data['noise'] = self.noise()

        data['player'] = dict()
        data['player']['state'] = bool(self.player['onoff'])
        data['player']['volume'] = (float(self.player['sdvol']) - 1) / 24
        if self.player['snddv'] == 'aux':
            data['player']['source'] = 'AUX'
        elif self.player['snddv'] == 'fmr':
            data['player']['source'] = 'FM ' + self.player['sndch']
        else:
            data['player']['source'] = 'Other'


        return data
    
    def toggle_light(self, state, brightness = None):
        """ Toggle the light on or off """
        payload = self.light_data
        payload['onoff'] = state
        payload['ngtlt'] = False
        if brightness:
            payload['ltlvl'] = int(brightness/255 * 25)

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self._put('wulgt', payload = payload)

    def dismiss_alarm(self):
        """ Dismiss a running alarm. """
        self._put('wualm/alctr', payload={'disms':True})

    def snooze_alarm(self):
        """ Snooze a running alarm. """
        self._put('wualm/alctr', payload={'tapsz':True})

    def get_alarm_settings(self, alarm):
        """ Get the alarm settings. """
        # Get alarm position
        alarm_pos = self.alarm_data[alarm]['position']

        # Get current alarm settings
        return self._put('wualm',payload={'prfnr':alarm_pos})

    def set_alarm(self, alarm, hour = None, minute = None, days = None):
        """ Set the time and day of an alarm. """

        # Adjust alarm settings
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']    # Alarm number
        if hour is not None: 
            alarm_settings['almhr'] = int(hour)                         # Alarm hour
            self.alarm_data[alarm]['time'] = datetime.time(int(hour), int(self.alarm_data[alarm]['time'].minute))
        if minute is not None: 
            alarm_settings['almmn'] = int(minute)                # Alarm min
            self.alarm_data[alarm]['time'] = datetime.time(int(self.alarm_data[alarm]['time'].hour), int(minute))
        if days is not None: 
            alarm_settings['daynm'] = int(days)                    # set days to repeat the alarm
            self.alarm_data[alarm]['days'] = days

        # Update powerwake
        if self.alarm_data[alarm]['powerwake']:
            alarm_datetime = datetime.datetime.strptime(self.alarm_data[alarm]['time'].isoformat(),'%H:%M:%S')
            powerwake_datetime = alarm_datetime + datetime.timedelta(minutes = self.alarm_data[alarm]['powerwake_delta'])

            alarm_settings['pszhr'] = powerwake_datetime.hour
            alarm_settings['pszmn'] = powerwake_datetime.minute

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings)

    def set_alarm_workdays(self, alarm):
        """ Set alarm on workday. """
        self.set_alarm(alarm, days=WORKDAYS_BINARY_MASK)

    def set_alarm_everyday(self, alarm):
        """ Set alarm on everyday. """
        self.set_alarm(alarm, days=WORKDAYS_BINARY_MASK + WEEKEND_BINARY_MASK)

    def set_alarm_weekend(self, alarm):
        """ Set alarm on weekends. """
        self.set_alarm(alarm, days=WEEKEND_BINARY_MASK)
    
    def set_alarm_tomorrow(self, alarm):
        """ Set alarm tomorrow. """
        self.set_alarm(alarm, days=0)

    def set_alarm_days(self, alarm, days):
        """ Set the alarm days. """
        days_int = sum([k for k, v in DAYS.items() if (v in days)])
        
        self.set_alarm(alarm, days=days_int)
    
    def set_light_alarm(self, alarm, curve = 'sunny day', level = 20, duration = 30):
        """Adjust the lightcurve of the wake-up light"""
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']    # Alarm number
        alarm_settings['ctype'] = LIGHT_CURVES[curve]                   # Light curve type
        alarm_settings['curve'] = level                                 # Light level (0 - 25, 0 is no light)
        alarm_settings['durat'] = duration                              # Duration in minutes (5 - 40)

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings)

    def set_sound_alarm(self, alarm, source = 'wake-up', channel = 'forest birds', level = 12):
        """Adjust the alarm sound of the wake-up light"""
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']                            # Alarm number
        alarm_settings['snddv'] = SOUND_SOURCE[source]                                          # Source (radio of wake-up)
        alarm_settings['sndch'] = SOUND_CHANNEL[channel] if source == 'wake-up' else (' ' if source == 'off' else channel)    # Channel
        alarm_settings['sndlv'] = level                                                         # Sound level (1 - 25)

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def set_snooze_time(self, snooze_time = 9):
        """Adjust the snooze time (minutes) of all alarms"""
        self._put('wualm', payload={'snztm': snooze_time})

    def get_snooze_time(self):
        """Get the snooze time (minutes) of all alarms"""
        response = self._get('wualm')
        return response['snztm']

    def set_powerwake(self, alarm, onoff = False, delta=0):
        """Set power wake"""

        alarm_datetime = datetime.datetime.strptime(self.alarm_data[alarm]['time'].isoformat(),'%H:%M:%S')
        powerwake_datetime = alarm_datetime + datetime.timedelta(minutes=delta)

        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']
        alarm_settings['pwrsz'] = 1 if onoff else 0
        alarm_settings['pszhr'] = powerwake_datetime.hour if onoff else 0
        alarm_settings['pszmn'] = powerwake_datetime.minute if onoff else 0

        self.alarm_data[alarm]['powerwake'] = onoff
        self.alarm_data[alarm]['powerwake_delta'] = delta if onoff else 0

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def add_alarm(self, alarm):
        """Add alarm to the list"""
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']
        alarm_settings['prfvs'] = True  # Add alarm

        # Send alarm settings
        self._put('wualm/prfwu', payload=alarm_settings) 

    def remove_alarm(self, alarm):
        """Remove alarm from the list"""
        # Set default settings
        alarm_settings = dict()
        alarm_settings['prfnr'] = self.alarm_data[alarm]['position']
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

    def toggle_alarm(self, alarm, status):
        """ Toggle the light on or off """
        self.alarm_data[alarm]['enabled'] = status
        payload = dict()
        payload['prfnr'] = self.alarm_data[alarm]['position']
        payload['prfvs'] = True
        payload['prfen'] = status
        self._put('wualm/prfwu', payload=payload)

    def toggle_night_light(self, state):
        """ Toggle the light on or off """
        payload = self.light_data
        payload['onoff'] = False
        payload['ngtlt'] = state

        # Some Wake-ups lights don't work with wucrv, remove key if exists
        if 'wucrv' in payload:
            payload.pop('wucrv')

        self._put('wulgt', payload=payload)

    def light_status(self):
        """Return the status of the light."""
        return bool(self.light_data['onoff']), int(int(self.light_data['ltlvl']) / 25 * 255)

    def night_light_status(self):
        """Return the status of the night light."""
        return bool(self.light_data['ngtlt'])

    def alarms(self):
        """Return the list of alarms."""
        alarms = dict()
        for alarm in list(self.alarm_data):
            alarms[alarm] = self.alarm_data[alarm]['enabled']

        return alarms

    def day_int(self, mon, tue, wed, thu, fri, sat, sun):
        return mon * 2 + tue * 4 + wed * 8 + thu * 16 + fri * 32 + sat * 64 + sun * 128

    def is_workday(self, alarm):
        days_int = self.alarm_data[alarm]['days']
        return days_int == 62

    def is_weekend(self, alarm):
        days_int = self.alarm_data[alarm]['days']
        return days_int == 192

    def is_everyday(self, alarm):
        days_int = self.alarm_data[alarm]['days']
        return days_int == 254

    def is_tomorrow(self, alarm):
        days_int = self.alarm_data[alarm]['days']
        return days_int == 0
    
    def get_alarm_days(self, alarm):
        days_int = self.alarm_data[alarm]['days']
        if days_int == 0:
            return ['tomorrow']
        else:
            return [v for k, v in DAYS.items() if k & days_int]

    def alarm_settings(self, alarm):
        """Return the time and days alarm is set."""
        alarm_time = self.alarm_data[alarm]['time'].isoformat()

        alarm_days = []
        days_int = self.alarm_data[alarm]['days']
        if days_int & 2:
            alarm_days.append('mon')
        if days_int & 4:
            alarm_days.append('tue')
        if days_int & 8:
            alarm_days.append('wed')
        if days_int & 16:
            alarm_days.append('thu')
        if days_int & 32:
            alarm_days.append('fri')
        if days_int & 64:
            alarm_days.append('sat')
        if days_int & 128:
            alarm_days.append('sun')

        return alarm_time, alarm_days

    def next_alarm(self):
        """Get the next alarm that is set."""
        next_alarm = None
        new_next_alarm = None
        for alarm in list(self.alarm_data):
            if self.alarm_data[alarm]['enabled'] == True:
                nu_tijd = datetime.datetime.now()
                nu_dag = datetime.date.today()
                alarm_time = self.alarm_data[alarm]['time']
                alarm_days_int = self.alarm_data[alarm]['days']
                alarm_days = []
                if alarm_days_int & 2:
                    alarm_days.append(1)
                if alarm_days_int & 4:
                    alarm_days.append(2)
                if alarm_days_int & 8:
                    alarm_days.append(3)
                if alarm_days_int & 16:
                    alarm_days.append(4)
                if alarm_days_int & 32:
                    alarm_days.append(5)
                if alarm_days_int & 64:
                    alarm_days.append(6)
                if alarm_days_int & 128:
                    alarm_days.append(7)

                day_today = nu_tijd.isoweekday()

                if not alarm_days:
                    alarm_time_full = datetime.datetime.combine(nu_dag, alarm_time)
                    if alarm_time_full > nu_tijd:
                        new_next_alarm = alarm_time_full
                    else:
                        new_next_alarm = alarm_time_full + datetime.timedelta(days=1)
                else:
                    for d in range(0, 7):
                        test_day = day_today + d
                        if test_day > 7:
                            test_day -= 7
                        if test_day in alarm_days:
                            alarm_time_full = datetime.datetime.combine(nu_dag, alarm_time) + datetime.timedelta(days=d)
                            if alarm_time_full > nu_tijd:
                                new_next_alarm = alarm_time_full
                                break

                if next_alarm:
                    if new_next_alarm < next_alarm:
                        next_alarm = new_next_alarm
                else:
                    next_alarm = new_next_alarm

        if next_alarm:
            return next_alarm.isoformat()
        else:
            return None

    def temperature(self):
        """Return the temperature."""
        return self.sensor_data['mstmp']

    def humidity(self):
        """Return the temperature."""
        return self.sensor_data['msrhu']

    def luminance(self):
        """Return the temperature."""
        return self.sensor_data['mslux']

    def noise(self):
        """Return the temperature."""
        return self.sensor_data['mssnd']

    def toggle_sunset(self, status):
        """ Toggle the sunset feature on or off """
        payload = dict()
        payload['onoff'] = status
        self._put('wudsk', payload=payload)
        
    def sunset_status(self):
        """Return the status of the sunset light."""
        return bool(self.sunset_data['onoff']), int(int(self.sunset_data['sndlv']) / 25 * 255)
    
    def toggle_player(self, state: bool):
        """Toggle the audio player"""
        data = self.player
        data['onoff'] = state
        self._put('wuply', payload=data)

    def set_volume_player(self, volume: float):
        """Set the volume of the player (0..1)"""
        if volume < 0:
            volume = 0
        if volume > 1:
            volume = 1

        self._put('wuply', payload={'sdvol': int(volume * 24 + 1)})

    def set_source_player(self, source: str | int):
        """Set the source of the player, either 'aux' or preset 1..5"""
        previous_state = self.player['onoff']
        if source == 'aux' or source == 'AUX':
            self._put('wuply', payload=
                      {'snddv': 'aux', 
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )
            # Repeat command for some unknown reason
            self._put('wuply', payload=
                      {'snddv': 'aux', 
                       'sndss': 0,
                       'onoff': previous_state,
                       'tempy': False
                    }
                )

        elif source in range(1,6):
            self._put('wuply', payload=
                      {'snddv': 'fmr', 
                       'sndch': str(source),
                       'sndss': 0,
                       'onoff': self.player['onoff'],
                       'tempy': False
                       }
                )