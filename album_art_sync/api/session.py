"""
session.py — Shared HTTP session with retry logic and connection pooling.
"""

import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def create_session() -> requests.Session:
    """Create a requests Session with enhanced security."""
    session = requests.Session()

    # Enhanced SSL configuration
    session.verify = certifi.where()

    # Retry strategy with security considerations
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        raise_on_status=False,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10,
    )

    session.mount("https://", adapter)
    session.mount("http://", adapter)

    # Security headers
    session.headers.update(
        {
            "User-Agent": "AudioSuite/6.0 (Optimized)",
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )

    return session


# Module-level singleton — re-used across all API calls
http = create_session()
