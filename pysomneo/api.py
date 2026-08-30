"""
Philips Somneo async API client using aiohttp with retry logic and session management.
"""
from __future__ import annotations

import asyncio
import logging
import random
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urljoin

import aiohttp
from aiohttp.client_exceptions import (
    ClientConnectorError,
    ClientError,
    ServerTimeoutError,
)

_LOGGER = logging.getLogger(__name__)


class SomneoInvalidURLError(ClientError):
    """Raised when the Somneo device responds with 422 Invalid URL."""


class SomneoClientError(ClientError):
    """Generic Somneo client error."""


class SomneoConnectionError(SomneoClientError):
    """Raised when a connection to the Somneo device fails."""


class SomneoSession:
    """
    Async HTTP session wrapper for communicating with a Somneo device.

    Provides connection pooling, retry logic with exponential backoff,
    and automatic session recovery on connection errors.
    """

    def __init__(
        self,
        base_url: str | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
        timeout: aiohttp.ClientTimeout | None = None,
    ) -> None:
        """Initialize the SomneoSession.

        Args:
            base_url: Base URL for all requests
            connect_timeout: Connection timeout in seconds (default: 5.0)
            read_timeout: Read timeout in seconds (default: 20.0)
            timeout: Optional pre-configured aiohttp.ClientTimeout
        """
        self.base_url = base_url
        if timeout is None:
            self._timeout = aiohttp.ClientTimeout(
                total=connect_timeout + read_timeout,
                connect=connect_timeout,
                sock_read=read_timeout,
            )
        else:
            self._timeout = timeout

        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp ClientSession.

        Returns:
            An active aiohttp.ClientSession
        """
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)  # Self-signed certs
            self._session = aiohttp.ClientSession(
                timeout=self._timeout,
                connector=connector,
            )
        return self._session

    async def _reset_session(self) -> None:
        """Close the current session, forcing a new one on next request."""
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception as exc:  # noqa: BLE001
                _LOGGER.debug("Error while closing session: %s", exc)
        self._session = None

    def _get_sleep_time(self, weight: float, attempt: int) -> float:
        """Calculate exponential backoff sleep time with jitter.

        Args:
            weight: Base weight multiplier
            attempt: Current attempt number (1-based)

        Returns:
            Sleep time in seconds
        """
        base = min(weight * (2 ** (attempt - 1)), 10)
        # Add random jitter (10% of base)
        jitter = random.uniform(0, base * 0.1)
        return base + jitter

    def _classify_error(self, e: Exception) -> tuple[str, bool, float]:
        """Classify exceptions for logging, pool reset, and backoff.

        Returns:
            Tuple of (err_type: str, reset_pool: bool, weight: float)
        """
        if isinstance(e, ServerTimeoutError):
            return "ServerTimeoutError", False, 2.5
        if isinstance(e, asyncio.TimeoutError):
            return "TimeoutError", False, 2.5
        if isinstance(e, ClientConnectorError):
            return "ClientConnectorError", True, 1.5
        if isinstance(e, ClientError):
            return "ClientError", False, 0.75
        # fallback for other exceptions
        return "Exception", False, 0.5

    async def request(
        self, method: str, url: str, **kwargs: Any
    ) -> aiohttp.ClientResponse:
        """Perform an async HTTP request with retry logic and session recovery.

        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            url: Request URL
            **kwargs: Additional arguments to pass to aiohttp.ClientSession.request

        Returns:
            aiohttp.ClientResponse object

        Raises:
            SomneoInvalidURLError: When device returns 422 status
            SomneoConnectionError: When all retries are exhausted
        """
        if self.base_url:
            full_url = urljoin(self.base_url, url)
        else:
            full_url = url

        max_attempts = 3
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                session = await self._get_session()
                resp = await session.request(method, full_url, **kwargs)

                if resp.status == 422:
                    resp.close()
                    raise SomneoInvalidURLError(
                        f"Invalid URL: {full_url}"
                    )

                _LOGGER.debug(
                    "HTTP %s %s -> %s",
                    method,
                    full_url,
                    resp.status,
                )
                return resp

            except (
                ClientConnectorError,
                ServerTimeoutError,
                asyncio.TimeoutError,
                ClientError,
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

                # Reset session if needed (e.g., connection errors)
                if reset_pool and attempt <= max_attempts:
                    _LOGGER.info(
                        "Resetting session (attempt %d) for %s due to %s",
                        attempt,
                        full_url,
                        err_type,
                    )
                    await self._reset_session()
                    # longer backoff after reset to allow new connection to be established
                    weight = 8.0

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
                    await asyncio.sleep(sleep)

        _LOGGER.info("All %d attempts failed for %s", max_attempts, full_url)
        msg = f"Connection to Somneo failed after {max_attempts} attempts: {last_exc}"
        raise SomneoConnectionError(msg) from last_exc

    async def close(self) -> None:
        """Close the underlying aiohttp session."""
        await self._reset_session()


class SomneoClient:
    """High-level async client for interacting with the Philips Somneo API."""

    def __init__(self, host: str) -> None:
        """Initialize the Somneo API client.

        Args:
            host: IP address or hostname of the Somneo device
        """
        self.host = host
        self.session = SomneoSession(
            base_url=f"https://{host}/di/v1/products/1/",
        )

    async def _internal_call(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Internal call to the device reusing SomneoSession.

        Args:
            method: HTTP method (GET, PUT, POST, etc.)
            path: API endpoint path
            headers: Optional HTTP headers
            payload: Optional request payload

        Returns:
            JSON response as dict
        """
        args: dict[str, Any] = {}
        if payload:
            args["json"] = payload
        if headers:
            args["headers"] = headers

        async with await self.session.request(method, path, **args) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def _get(self, path: str) -> Any:
        """Perform a GET request.

        Args:
            path: API endpoint path

        Returns:
            JSON response
        """
        return await self._internal_call("GET", path)

    async def put(self, path: str, payload: dict[str, Any]) -> Any:
        """Perform a PUT request with JSON payload.

        Args:
            path: API endpoint path
            payload: Request payload dictionary

        Returns:
            JSON response
        """
        return await self._internal_call("PUT", path, payload=payload)

    async def get_description_xml(self) -> ET.Element | None:
        """Fetch the device description XML from the Somneo device.

        Tries HTTPS first, then HTTP as fallback.

        Returns:
            XML root element or None if all attempts failed
        """
        urls = [
            f"https://{self.host}/upnp/description.xml",
            f"http://{self.host}/upnp/description.xml",
        ]

        last_exc: Exception | None = None
        for url in urls:
            try:
                resp = await self.session.request("GET", url)
                text = await resp.text()
                resp.close()

                root = ET.fromstring(text)
                return root

            except (ClientError, asyncio.TimeoutError) as e:
                _LOGGER.debug("Connection failed for %s: %s", url, e)
                last_exc = e
            except ET.ParseError as e:
                _LOGGER.debug("XML parsing failed for %s: %s", url, e)
                last_exc = e

        if last_exc is not None:
            raise last_exc  # type: ignore[misc]

        return None

    async def get_themes(self) -> dict[str, dict[str, int]]:
        """Get available light and sound themes as a dictionary.

        Returns:
            Dictionary containing wake_light, dusk_light, wake_sound,
            and dusk_sound theme mappings
        """
        return {
            "wake_light": {
                item["name"].lower(): idx
                for idx, item in enumerate(
                    (await self._get("files/lightthemes")).values()
                )
                if item["name"]
            },
            "dusk_light": {
                item["name"].lower(): idx
                for idx, item in enumerate(
                    (await self._get("files/dusklightthemes")).values()
                )
            },
            "wake_sound": {
                item["name"].lower(): idx + 1
                for idx, item in enumerate(
                    (await self._get("files/wakeup")).values()
                )
                if item["name"]
            },
            "dusk_sound": {
                item["name"].lower(): idx + 1
                for idx, item in enumerate(
                    (await self._get("files/winddowndusk")).values()
                )
                if item["name"]
            },
        }

    async def get_sensor_data(self) -> dict[str, Any]:
        """Get sensor data as a dictionary.

        Returns:
            Dictionary with temperature, humidity, luminance, and noise values
        """
        data = await self._get("wusrd")
        return {
            "temperature": data.get("mstmp"),
            "humidity": data.get("msrhu"),
            "luminance": data.get("mslux"),
            "noise": data.get("mssnd"),
        }

    async def get_alarm_status(self) -> dict[str, Any]:
        """Get alarm status.

        Returns:
            Alarm status dictionary
        """
        return await self._get("wusts")

    async def get_light_data(self) -> dict[str, Any]:
        """Get light data.

        Returns:
            Light state dictionary
        """
        return await self._get("wulgt")

    async def get_sunset_data(self) -> dict[str, Any]:
        """Get sunset data.

        Returns:
            Sunset settings dictionary
        """
        return await self._get("wudsk")

    async def get_enabled_alarms(self) -> dict[str, Any]:
        """Get enabled alarms.

        Returns:
            Enabled alarms configuration dictionary
        """
        return await self._get("wualm/aenvs")

    async def get_time_alarms(self) -> dict[str, Any]:
        """Get time alarms.

        Returns:
            Time alarm settings dictionary
        """
        return await self._get("wualm/aalms")

    async def get_snooze_time(self) -> dict[str, Any]:
        """Get snooze time.

        Returns:
            Snooze time configuration
        """
        return await self._get("wualm")

    async def get_player_status(self) -> dict[str, Any]:
        """Get player status.

        Returns:
            Player state dictionary
        """
        return await self._get("wuply")

    async def modify_light(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set light data.

        Args:
            payload: Light settings dictionary

        Returns:
            Device response
        """
        if "wucrv" in payload:
            payload.pop("wucrv")
        return await self.put("wulgt", payload=payload)

    async def modify_sunset(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set sunset data.

        Args:
            payload: Sunset settings dictionary

        Returns:
            Device response
        """
        return await self.put("wudsk", payload=payload)

    async def modify_player(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set player control data.

        Args:
            payload: Player settings dictionary

        Returns:
            Device response
        """
        return await self.put("wuply", payload=payload)

    async def modify_alarm_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set alarm control data.

        Args:
            payload: Alarm settings dictionary

        Returns:
            Device response
        """
        return await self.put("wualm", payload=payload)

    async def modify_running_alarm(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set running alarm control data.

        Args:
            payload: Running alarm control dictionary

        Returns:
            Device response
        """
        return await self.put("wualm/alctr", payload=payload)

    async def modify_alarm_wake_up_configuration(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Set alarm wake up configuration data.

        Args:
            payload: Wake up configuration dictionary

        Returns:
            Device response
        """
        return await self.put("wualm/prfwu", payload=payload)

    async def modify_alarm_status(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Set alarm status data.

        Args:
            payload: Alarm status dictionary

        Returns:
            Device response
        """
        return await self.put("wusts", payload=payload)