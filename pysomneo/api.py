"""
Philips Somneo API client using requests with connection pooling, retries, and session management.
"""

import time
import logging
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin
import urllib3
from urllib3.util.retry import Retry
from urllib3.exceptions import NewConnectionError

from requests import Session, request
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ConnectTimeout,
    ReadTimeout,
    RequestException,
    Timeout,
    ConnectionError,
)

_LOGGER = logging.getLogger("pysomneo")


class SomneoInvalidURLError(RequestException):
    """Raised when the Somneo device responds with 422 Invalid URL."""


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
        connect_timeout: float = 2.0,
        read_timeout: float = 8.0,
        timeout: tuple[float, float] | None = None,
        pool_connections: int = 1,
        pool_maxsize: int = 1,
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
        self._timeout = (connect_timeout, read_timeout) if timeout is None else timeout

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

    def _get_sleep_time(self, weight: float, attempt: int) -> float:
        """Calculate exponential backoff sleep time."""
        return min(weight * (2**(attempt - 1)), 10)

    def _classify_error(self, e):
        """
        Classify exceptions for logging, pool reset, and backoff.
        Returns: (err_type: str, reset_pool: bool, weight: float)
        """
        if isinstance(e, ConnectTimeout):
            return "ConnectTimeout", True, 1.5
        elif isinstance(e, ReadTimeout):
            return "ReadTimeout", False, 2.0
        elif isinstance(e, ConnectionError):
            if isinstance(e.__cause__, NewConnectionError):
                return "NewConnectionError", True, 0.25
            else:
                return "ConnectionError", True, 1.0
        elif isinstance(e, Timeout):
            return "Timeout", False, 0.5
        else:  # fallback for other RequestExceptions
            return "RequestException", False, 0.75

    def request(self, method, url, **kwargs):
        if self.base_url:
            full_url = urljoin(self.base_url, url)
        else:
            full_url = url

        if "timeout" not in kwargs:
            kwargs["timeout"] = self._timeout

        max_attempts = 3
        last_exc = None
        has_reset_pool = False

        for attempt in range(1, max_attempts + 1):
            try:
                if self._use_session:
                    resp = super().request(method, full_url, **kwargs)
                else:
                    resp = request(method, full_url, timeout=self._timeout, **kwargs)

                if resp.status_code == 422:
                    raise SomneoInvalidURLError(
                        f"Invalid URL: {full_url}", response=resp
                    )
                return resp

            except (
                ConnectTimeout,
                ReadTimeout,
                ConnectionError,
                Timeout,
                RequestException,
            ) as e:
                err_type, reset_pool, weight = self._classify_error(e)

                _LOGGER.debug(
                    "%s (attempt %d/%d) when calling %s: %s",
                    err_type,
                    attempt,
                    max_attempts,
                    full_url,
                    e,
                )
                last_exc = e

                # Reset pool if necessary
                if (
                    reset_pool
                    and attempt <= max_attempts
                    and self._use_session
                    and not has_reset_pool
                ):
                    _LOGGER.info(
                        "Resetting session pool (attempt %d) for %s due to %s",
                        attempt,
                        full_url,
                        err_type,
                    )
                    try:
                        self._reset_session_pool()
                        has_reset_pool = True
                    except (OSError, RuntimeError) as exc:
                        _LOGGER.debug("Session reset failed: %s", exc)

                # Backoff
                sleep = self._get_sleep_time(weight, attempt)

                if attempt < max_attempts:
                    _LOGGER.debug(
                        "Sleeping %.2fs before retrying %s (attempt %d/%d)",
                        sleep,
                        full_url,
                        attempt,
                        max_attempts,
                    )
                    time.sleep(sleep)

        _LOGGER.error("All %d attempts failed for %s", max_attempts, full_url)
        if last_exc is not None:
            raise last_exc
        raise RequestException("Unknown error in SomneoSession.request")


class SomneoClient:
    """High-level client for interacting with the Philips Somneo API."""

    def __init__(self, host: str, use_session: bool = True):
        urllib3.disable_warnings()
        self.host = host
        self.timeout = (2.0, 8.0)  # (connect, read) timeouts in seconds
        self.session = SomneoSession(
            base_url=f"https://{host}/di/v1/products/1/",
            use_session=use_session,
            timeout=self.timeout,
        )

    def _internal_call(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ):
        """Internal call to the device reusing SomneoSession"""
        args: dict[str, Any] = {}
        if payload:
            args["json"] = payload
        if headers:
            args["headers"] = headers

        r = None
        try:
            r = self.session.request(
                method, path, verify=False, timeout=self.timeout, **args
            )
            r.raise_for_status()
            return r.json()
        finally:
            if r is not None:
                r.close()

    def _get(self, path: str):
        """Perform a GET request."""
        return self._internal_call("GET", path)

    def put(self, path: str, payload: dict[str, Any]) -> Any:
        """Perform a PUT request with JSON payload."""
        return self._internal_call("PUT", path, payload=payload)

    def get_description_xml(self):
        """
        Fetch the device description XML from the Somneo device.
        Tries HTTPS first, then HTTP as fallback.
        Returns raw XML content.
        """
        urls = [
            f"https://{self.host}/upnp/description.xml",
            f"http://{self.host}/upnp/description.xml",
        ]

        last_exc = None
        for url in urls:
            response = None
            try:
                response = self.session.request(
                    "GET", url, verify=False, timeout=self.timeout
                )
                response.raise_for_status()
                # Try parsing immediately to ensure it's valid XML
                root = ET.fromstring(response.content)
                return root

            except RequestException as e:
                _LOGGER.debug("Connection failed for %s: %s", url, e)
                last_exc = e
            except ET.ParseError as e:
                _LOGGER.debug("XML parsing failed for %s: %s", url, e)
                last_exc = e
            finally:
                if response is not None:
                    response.close()

        if last_exc is not None:
            raise last_exc

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

    def modify_light(self, payload: dict) -> dict:
        """Set light data"""
        return self.put("wulgt", payload=payload)

    def modify_sunset(self, payload: dict) -> dict:
        """Set sunset data"""
        return self.put("wudsk", payload=payload)

    def modify_player(self, payload: dict) -> dict:
        """Set player control data"""
        return self.put("wuply", payload=payload)

    def modify_alarm_details(self, payload: dict) -> dict:
        """Set alarm control data"""
        return self.put("wualm", payload=payload)

    def modify_running_alarm(self, payload: dict) -> dict:
        """Set alarm control data"""
        return self.put("wualm/alctr", payload=payload)

    def modify_alarm_wake_up_configuration(self, payload: dict) -> dict:
        """Set alarm wake up data"""
        return self.put("wualm/prfwu", payload=payload)

    def modify_alarm_status(self, payload: dict) -> dict:
        """Set alarm wake up status"""
        return self.put("wusts", payload=payload)
