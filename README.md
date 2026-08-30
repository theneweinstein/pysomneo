# pysomneo

An async Python library to communicate with the API of Philips Somneo wake-up lights.

## Features

- Async-first design using `aiohttp` for optimal Home Assistant integration
- Automatic session management with connection pooling
- Exponential backoff with jitter for transient errors
- Automatic session recovery on connection errors
- Full support for all Somneo API endpoints:
  - Light control (main light, night light)
  - Alarm management (create, modify, delete, enable/disable)
  - Sunset simulation (dusk mode)
  - Audio player control (FM radio, AUX, nature sounds)
  - Sensor data (temperature, humidity, luminance, noise level)
  - Display settings
  - Snooze configuration

## Installation

```bash
pip install pysomneo
```

## Usage

```python
import asyncio
from pysomneo import Somneo


async def main():
    somneo = Somneo("192.168.1.100")

    # Fetch all data
    data = await somneo.fetch_data()
    print(data)

    # Get device info
    dev_info = await somneo.get_device_info()
    print(dev_info)

    # Control the light
    await somneo.toggle_light(True, brightness=128)

    # Get current data
    data = await somneo.fetch_data()
    print(f"Temperature: {data['temperature']}")
    print(f"Light is on: {data['light_is_on']}")


asyncio.run(main())
```

## Development

```bash
pip install -e .