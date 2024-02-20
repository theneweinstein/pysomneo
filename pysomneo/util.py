import calendar
from datetime import time, date, timedelta, datetime 

from .const import DAYS, DAYS_TYPE

def days_int_to_list(days_int):
    """Convert integer to list of days."""
    if days_int == 0:
        return ['tomorrow']
    else:
        return [v for k, v in DAYS.items() if k & days_int]
    
def days_list_to_int(days):
    """Convert list of days to integer."""
    return sum([k for k, v in DAYS.items() if (v in days)])

def days_int_to_type(days_int):
    """Convert integer to predefined days."""
    if days_int in DAYS_TYPE.keys():
        return DAYS_TYPE[days_int]
    else:
        return 'custom'

def alarms_to_dict(enabled_alarms, time_alarms):
    """Construct alarm data dictionary."""
    
    alarms = dict()
    for alarm, enabled in enumerate(enabled_alarms['prfen']):
        alarms[alarm] = dict()
        alarms[alarm]['position'] = alarm + 1
        alarms[alarm]['name'] = 'alarm' + str(alarm)
        alarms[alarm]['enabled'] = bool(enabled)
        alarms[alarm]['time'] = time(int(time_alarms['almhr'][alarm]),
                                                            int(time_alarms['almmn'][alarm]))
        alarms[alarm]['days'] = days_int_to_list(int(time_alarms['daynm'][alarm]))
        alarms[alarm]['days_type'] = DAYS_TYPE.get(int(time_alarms['daynm'][alarm]),'custom')
        alarms[alarm]['powerwake'] = bool(enabled_alarms['pwrsv'][3*alarm])
        if bool(enabled_alarms['pwrsv'][3*alarm]):
            alarms[alarm]['powerwake_delta'] = max(0, 60 * int(enabled_alarms['pwrsv'][3*alarm+1]) + int(enabled_alarms['pwrsv'][3*alarm+2])
                                                            - 60 * int(time_alarms['almhr'][alarm]) - int(time_alarms['almmn'][alarm]))
        else:
            alarms[alarm]['powerwake_delta'] = 0

    return alarms

def sunset_to_dict(sunset_data, light_curves, sounds):
    """Construct sunset data dictionary."""
    data = dict()
    data['is_on'] = bool(sunset_data['onoff'])
    data['duration'] = int(sunset_data['durat'])
    data['curve'] = list(light_curves.keys())[list(light_curves.values()).index(int(sunset_data['ctype']))]
    data['level'] = sunset_data['curve']
    if sunset_data['snddv'] == 'dus':
        data['sound'] = list(sounds.keys())[list(sounds.values()).index(int(sunset_data['sndch']))]
    elif sunset_data['snddv'] == 'fmr':
        data['sound'] = 'fm ' + str(sunset_data['sndch'])
    elif sunset_data['snddv'] == 'off':
        data['sound'] = 'off'
    else:
        data['sound'] = sunset_data['sndch']
    data['volume'] = sunset_data['sndlv']

    return data

def player_to_dict(player):
    """Construct player data dictionary."""
    data = dict()
    data['state'] = bool(player['onoff'])
    data['volume'] = (float(player['sdvol']) - 1) / 24
    if player['snddv'] == 'aux':
        data['source'] = 'AUX'
    elif player['snddv'] == 'fmr':
        data['source'] = 'FM ' + player['sndch']
    else:
        data['source'] = 'Other' 

    return data

def next_alarm(alarms):
    """Get the next alarm that is set."""
    next_alarm = None
    new_next_alarm = None
    for alarm in alarms:
        if alarms[alarm]['enabled'] == True:
            # Get current time and day.
            now_time = datetime.now()
            now_day = date.today()

            # Get time and day of alarm
            alarm_time = alarms[alarm]['time']
            alarm_days = alarms[alarm]['days']

            # If alarm goes of tomorrow
            if alarm_days == ['tomorrow']:
                alarm_time_full = datetime.combine(now_day, alarm_time)
                if alarm_time_full > now_time:
                    new_next_alarm = alarm_time_full
                else:
                    new_next_alarm = alarm_time_full + timedelta(days=1)
            # If days are specified
            else:
                # Find first following day that the alarm is set.
                for d in range(0,7):
                    test_day = now_time.isoweekday() + d
                    if test_day > 7:
                        test_day -= 7
                    if calendar.day_abbr[test_day-1].lower() in alarm_days:
                        alarm_time_full = datetime.combine(now_day, alarm_time) + timedelta(days=d)
                        if alarm_time_full > now_time:
                            new_next_alarm = alarm_time_full
                            break

            if next_alarm:
                if new_next_alarm < next_alarm:
                    next_alarm = new_next_alarm
            else:
                next_alarm = new_next_alarm

    if next_alarm:
        return next_alarm.astimezone()
    else:
        return None
