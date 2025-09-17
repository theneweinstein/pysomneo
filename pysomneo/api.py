import time
from requests import Session, request
from urllib.parse import urljoin
import json
import logging

_LOGGER = logging.getLogger('pysomneo')

class SomneoSession(Session):
    def __init__(self, base_url = None, use_session = True):
        if use_session: 
            super().__init__()
        self._use_session = use_session
        self.base_url = base_url

    def request(self, method: str | bytes, url: str | bytes, *args, **kwargs):
        joined_url = urljoin(self.base_url, url)
        if self._use_session:
            return super().request(method, joined_url, *args, **kwargs)
        else:
            return request(method, joined_url, *args, **kwargs)


def internal_call(session, method, url, headers=None, payload=None, retries=3, backoff_factor=2):
    """Call to the API with retries and exponential backoff."""
    args = {}

    if payload:
        args["data"] = json.dumps(payload)

    if headers:
        args["headers"] = headers

    for attempt in range(1, retries + 1):
        try:
            r = session.request(method, url, verify=False, timeout=20, **args)

            if r.status_code == 422:
                _LOGGER.error(f"Invalid URL: {url}")
                raise Exception(f"Invalid URL: {url}")

            r.raise_for_status()
            return r.json()

        except Exception as e:
            if attempt < retries:
                sleep_time = backoff_factor ** (attempt - 1)
                _LOGGER.warning(
                    f"Attempt {attempt} failed: {e}. Retrying in {sleep_time}s..."
                )
                time.sleep(sleep_time)
            else:
                _LOGGER.error(f"Error connecting to somneo after {retries} attempts.")
                raise

def get(session, url, payload=None):
    """Get request."""
    return internal_call(session, 'GET', url, None, payload)

def put(session, url, payload=None):
    """Put request."""
    return internal_call(session, 'PUT', url, {"Content-Type": "application/json"}, payload)