import time
from requests import Session, request, exceptions
from requests.adapters import HTTPAdapter
import urllib3
from urllib.parse import urljoin
from urllib3.util.retry import Retry
import xml.etree.ElementTree as ET
import json
import logging

from .const import *

_LOGGER = logging.getLogger('pysomneo')

class SomneoInvalidURLError(exceptions.RequestException):
    """Raised when the Somneo device responds with 422 Invalid URL."""
    pass

class SomneoSession(Session):
    """
    requests.Session subclass that:
      - supports a base_url,
      - mounts a pool adapter for connection reuse,
      - will reset its internal session/pool once on ConnectionError to recover stale sockets,
      - exposes a short retry/backoff strategy for transient errors.
    """

    def __init__(
        self,
        base_url: str | None = None,
        use_session: bool = True,
        request_timeout: float = 8.0,
        pool_connections: int = 1,
        pool_maxsize: int = 3,
        adapter_retries: int = 0,
        adapter_backoff_factor: float = 0.1,
    ):
        super().__init__()
        self.base_url = base_url
        self._use_session = use_session
        self._pool_connections = pool_connections
        self._pool_maxsize = pool_maxsize
        self._adapter_retries = adapter_retries
        self._adapter_backoff_factor = adapter_backoff_factor
        self._request_timeout = request_timeout

        self._mount_adapter()

    def _make_retry_strategy(self):
        # Minimal adapter retry strategy — keep low because we do request-level retries too
        return Retry(
            total=self._adapter_retries,
            backoff_factor=self._adapter_backoff_factor,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET", "PUT", "DELETE", "OPTIONS"]),
        )

    def _mount_adapter(self):
        adapter = HTTPAdapter(
            pool_connections=self._pool_connections,
            pool_maxsize=self._pool_maxsize,
            max_retries=self._make_retry_strategy(),
            pool_block=False,
        )
        # (re)mount adapters for both http and https
        self.mount("http://", adapter)
        self.mount("https://", adapter)

    def _reset_session_pool(self):
        """Close the session and reinitialize internals and adapters."""
        try:
            # close underlying connections (releases pools)
            self.close()
        except Exception as exc:
            _LOGGER.debug("Error while closing session: %s", exc)

        # Re-init Session internals
        super().__init__()
        # Re-mount adapters after re-init
        self._mount_adapter()

    def request(self, method: str, url: str, *args, **kwargs):
        """
        Override request to:
          - join base_url,
          - try a quick reset-and-retry on ConnectionError,
          - perform a few retries with backoff for other transient errors.
        Returns a requests.Response (not .json()) — keep same semantics as requests.Session.request.
        """
        if self.base_url:
            full_url = urljoin(self.base_url, url)
        else:
            full_url = url

        # Use provided timeout if present, otherwise the session default
        if "timeout" not in kwargs:
            kwargs["timeout"] = self._request_timeout

        max_attempts = 3
        last_exc = None

        for attempt in range(1, max_attempts + 1):
            try:
                if self._use_session:
                    resp = super().request(method, full_url, *args, **kwargs)
                else:
                    resp = request(method, full_url, *args, **kwargs)
                if resp.status_code == 422:
                    raise SomneoInvalidURLError(f"Invalid URL: {full_url}", response=resp)
                return resp

            except exceptions.ConnectionError as e:
                # This is the important case: remote refused or underlying socket invalid
                _LOGGER.warning(
                    "ConnectionError (attempt %d/%d) to %s: %s",
                    attempt,
                    max_attempts,
                    full_url,
                    e,
                )
                last_exc = e

                # On first ConnectionError attempt, try resetting the session pool immediately and retry.
                if attempt < max_attempts and self._use_session:
                    _LOGGER.info("Resetting session pool (attempt %d) for %s", attempt, full_url)
                    try:
                        self._reset_session_pool()
                    except Exception as exc:
                        _LOGGER.debug("Session reset failed: %s", exc)
                    # immediate retry loop continues
                    continue

                # otherwise fall through to backoff and retry

            except exceptions.Timeout as e:
                _LOGGER.warning(
                    "Timeout (attempt %d/%d) when calling %s: %s",
                    attempt,
                    max_attempts,
                    full_url,
                    e,
                )
                last_exc = e

            except exceptions.RequestException as e:
                # Generic requests exceptions (HTTPError will be raised after response)
                _LOGGER.warning(
                    "RequestException (attempt %d/%d) when calling %s: %s",
                    attempt,
                    max_attempts,
                    full_url,
                    e,
                )
                last_exc = e

            # If not returned, apply exponential backoff before next attempt
            if attempt < max_attempts:
                sleep = 0.75 * (2 ** (attempt - 1))  # 0.75s, 1.5s, 3s ...
                _LOGGER.debug("Sleeping %.2fs before next attempt to %s", sleep, full_url)
                time.sleep(sleep)

        # All attempts failed — raise last exception to caller
        _LOGGER.error("All %d attempts failed for %s", max_attempts, full_url)
        raise last_exc if last_exc is not None else exceptions.RequestException("Unknown error in SomneoSession.request")


class SomneoClient:
    """High-level client for interacting with the Philips Somneo API."""

    def __init__(self, host: str, use_session: bool = True):
        urllib3.disable_warnings()
        self.request_timeout = 6.0
        self.host = host
        self.session = SomneoSession(
            base_url=f"https://{host}/di/v1/products/1/",
            use_session=use_session,
            request_timeout=self.request_timeout,
        )

    def _internal_call(self, method: str, path: str, headers: dict | None = None, payload: dict | None = None):
        """Internal call to the device reusing SomneoSession"""
        args = {}
        if payload:
            args["data"] = json.dumps(payload)
        if headers:
            args["headers"] = headers

        r = None
        try:
            r = self.session.request(method, path, verify=False, timeout=self.request_timeout, **args)
            r.raise_for_status()
            return r.json()
        finally:
            if r is not None:
                r.close()

    def _get(self, path: str):
        """Perform a GET request."""
        return self._internal_call("GET", path)

    def put(self, path: str, payload: dict):
        """Perform a PUT request with JSON payload."""
        return self._internal_call("PUT", path, headers={"Content-Type": "application/json"}, payload=payload)

    def get_description_xml(self):
        """
        Fetch the device description XML from the Somneo device.
        Tries HTTPS first, then HTTP as fallback.
        Returns raw XML content.
        """
        urls = [
            f'https://{self.host}/upnp/description.xml',
            f'http://{self.host}/upnp/description.xml'
        ]

        for url in urls:
            response = None
            try:
                response = self.session.request('GET', url, verify=False, timeout=self.request_timeout)
                response.raise_for_status()
                # Try parsing immediately to ensure it's valid XML
                root = ET.fromstring(response.content)
                return root
            except exceptions.RequestException as e:
                _LOGGER.warning("Connection failed for %s: %s", url, e)
            except ET.ParseError as e:
                _LOGGER.warning("XML parsing failed for %s: %s", url, e)
            finally:
                if response is not None:
                    response.close()

        # Return None if all attempts failed
        return None

    def get_themes(self) -> dict[str, dict[str, int]]:
        """Get available light and sound themes as a dictionary."""

        return {
            "wake_light": {
                item["name"].lower(): idx
                for idx, item in enumerate(self._get("files/lightthemes").values())
                if item["name"]
            },
            "dusk_light": {
                item["name"].lower(): idx
                for idx, item in enumerate(self._get("files/dusklightthemes").values())
            },
            "wake_sound": {
                item["name"].lower(): idx + 1
                for idx, item in enumerate(self._get("files/wakeup").values())
                if item["name"]
            },
            "dusk_sound": {
                item["name"].lower(): idx + 1
                for idx, item in enumerate(self._get("files/winddowndusk").values())
                if item["name"]
            },
        }

    def get_sensor_data(self):
        """Get sensor data as a dictionary."""
        data = self._get("wusrd")
        return {
            "temperature": data.get("mstmp"),
            "humidity": data.get("msrhu"),
            "luminance": data.get("mslux"),
            "noise": data.get("mssnd"),
        }

    def get_alarm_status(self):
        """Get alarm status"""
        return self._get("wusts")

    def get_light_data(self):
        """Get light data"""
        return self._get("wulgt")

    def get_sunset_data(self):
        """Get sunset data"""
        return self._get("wudsk")

    def get_enabled_alarms(self):
        """Get enabled alarms"""
        return self._get("wualm/aenvs")

    def get_time_alarms(self):
        """Get time alarms"""
        return self._get("wualm/aalms")

    def get_snooze_time(self):
        """Get snooze time"""
        return self._get("wualm")

    def get_player_status(self):
        """Get player status"""
        return self._get("wuply")
