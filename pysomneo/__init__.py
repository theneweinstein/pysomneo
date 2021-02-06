import requests
import urllib3
import json
import xmltodict
import logging
import datetime

_LOGGER = logging.getLogger('pysomneo')

class Somneo(object):
    """
    Class represents the SmartSleep Wake-Up Light.
    """

    def __init__(self, host = None):
        """Initialize."""
        urllib3.disable_warnings()
        self.host = host
        self._base_url = 'https://' + host + '/di/v1/products/1/'
        self._session = requests.Session()

        self.light_data = None
        self.sensor_data = None
        self.sunset_data = None
        self.sunset_timer_data = None
        self.alarm_data = dict()

    def get_device_info(self):
        """ Get Device information """
        try:
            response = self._session.request('GET','https://' + self.host + '/upnp/description.xml', verify=False, timeout=20)
        except requests.Timeout:
            _LOGGER.error('Connection to SmartSleep timed out.')
        except requests.RequestException:
            _LOGGER.error('Error connecting to SmartSleep.')

        """ Convert description.xml response to dict """
        root = xmltodict.parse(response.content)

        """ Extract the device node and parse """
        device_info = dict()
        device_info['manufacturer'] = root['root']['device']['manufacturer']
        device_info['model'] = root['root']['device']['modelName']
        device_info['modelNumber'] = root['root']['device']['modelNumber']
        device_info['friendlyName'] = root['root']['device']['friendlyName']
        device_info['serial'] = root['root']['device']['cppId']
        device_info['udn'] = root['root']['device']['UDN']

        return device_info

    def _internal_call(self, method, url, headers, payload):
        """Call to the API."""
        args = dict()
        url = self._base_url + url

        if payload:
            args['data'] = json.dumps(payload)

        if headers:
            args['headers'] = headers

        try:
            r = self._session.request(method, url, verify=False, timeout=20, **args)
        except requests.Timeout:
            _LOGGER.error('Connection to SmartSleep timed out.')
        except requests.RequestException:
            _LOGGER.error('Error connecting to SmartSleep.')
        else:
            if r.status_code == 422:
                _LOGGER.error('Invalid URL.')
                raise Exception("Invalid URL.")

        if method == 'GET':
            return r.json()
        else:
            return

    def _get(self, url, args=None, payload=None):
        return self._internal_call('GET', url, None, payload)

    def _put(self, url, args=None, payload=None):
        return self._internal_call('PUT', url, {"Content-Type": "application/json"}, payload)

    def toggle_light(self, state, brightness = None):
        """ Toggle the light on or off """
        payload = self.light_data
        payload['onoff'] = state
        payload['ngtlt'] = False
        if brightness:
            payload['ltlvl'] = int(brightness/255 * 25)
        self._put('wulgt', payload = payload)

    def toggle_night_light(self, state):
        """ Toggle the light on or off """
        payload = self.light_data
        payload['onoff'] = False
        payload['ngtlt'] = state
        self._put('wulgt', payload = payload)

    def toggle_sunset(self, state, brightness = None):
        """ Toggle the sunset mode on or off """
        payload = self.sunset_data
        payload['onoff'] = state
        if brightness:
            payload['curve'] = int(brightness/255 * 25)
        self._put('wudsk', payload = payload)

    def update(self):
        """Get the latest update from Somneo."""

        # Get light information
        self.light_data = self._get('wulgt')

        # Get sunset (dusk) information:
        self.sunset_data = self._get('wudsk')

        # Get sunset current timer information:
        self.sunset_timer_data = self._get('wutmr')

        # Get sensor data
        self.sensor_data = self._get('wusrd')

        # Get alarm data
        enabled_alarms = self._get('wualm/aenvs')
        time_alarms = self._get('wualm/aalms')
        for alarm, enabled in enumerate(enabled_alarms['prfen']):
            alarm_name = 'alarm' + str(alarm)
            self.alarm_data[alarm_name] = dict()
            self.alarm_data[alarm_name]['enabled'] = bool(enabled)
            self.alarm_data[alarm_name]['time'] = datetime.time(int(time_alarms['almhr'][alarm]), int(time_alarms['almmn'][alarm]))
            self.alarm_data[alarm_name]['days'] = int(time_alarms['daynm'][alarm])

    def light_status(self):
        """Return the status of the light."""
        return self.light_data['onoff'], int(int(self.light_data['ltlvl'])/25*255)

    def night_light_status(self):
        """Return the status of the night light."""
        return self.light_data['ngtlt']

    def sunset_status(self):
        """Return the status of sunset (dusk) mode."""
        return self.sunset_data['onoff'], int(int(self.sunset_data['curve'])/25*255)

    def sunset_timer_status(self):
        """Return the current sunset timer status."""
        return int(self.sunset_timer_data['dskmn']), int(self.sunset_timer_data['dsksc'])

    def alarms(self):
        """Return the list of alarms."""
        alarms = dict()
        for alarm in list(self.alarm_data):
            alarms[alarm] = self.alarm_data[alarm]['enabled']

        return alarms

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
                    elif alarm_time_full + datetime.timedelta(days=1) > nu_tijd:
                        new_next_alarm = alarm_time_full
                else:
                    for d in range(0,7):
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

    def sunset(self):
        """Return the current sunset mode status (last start time, time remaining)."""
        return self.sunset_timer_data['wutmr']

    def temperature(self):
        """Return the current room temperature."""
        return self.sensor_data['mstmp']

    def humidity(self):
        """Return the current room humidity."""
        return self.sensor_data['msrhu']

    def luminance(self):
        """Return the current room luminance."""
        return self.sensor_data['mslux']

    def noise(self):
        """Return the current room noise level."""
        return self.sensor_data['mssnd']
