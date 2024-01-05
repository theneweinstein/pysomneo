from requests import Session, Timeout, ConnectionError, RequestException
from urllib.parse import urljoin
import json
import logging

_LOGGER = logging.getLogger('pysomneo')

class SomneoSession(Session):
    def __init__(self, base_url = None):
        super().__init__()
        self.base_url = base_url

    def request(self, method: str | bytes, url: str | bytes, *args, **kwargs):
        joined_url = urljoin(self.base_url, url)
        return super().request(method, joined_url, *args, **kwargs)


def internal_call(session, method, url, headers, payload):
    """Call to the API."""
    args = dict()

    if payload:
        args['data'] = json.dumps(payload)

    if headers:
        args['headers'] = headers

    while True:
        try:
            r = session.request(method, url, verify=False, timeout=20, **args)
        except Timeout:
            _LOGGER.error('Connection to Somneo timed out.')
            raise
        except ConnectionError:
            continue
        except RequestException:
            _LOGGER.error('Error connecting to Somneo.')
            raise
        else:
            if r.status_code == 422:
                _LOGGER.error('Invalid URL.')
                raise Exception("Invalid URL.")
        break

    return r.json()

def get(session, url, payload=None):
    """Get request."""
    return internal_call(session, 'GET', url, None, payload)

def put(session, url, payload=None):
    """Put request."""
    return internal_call(session, 'PUT', url, {"Content-Type": "application/json"}, payload)