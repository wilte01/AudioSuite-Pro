"""
lrclib.py — LRCLIB lyric provider.

Queries the public LRCLIB API (https://lrclib.net) exact-match endpoint,
``GET /api/get?artist_name=...&track_name=...``, which returns JSON with
``syncedLyrics`` and ``plainLyrics`` fields and a 404 status when the track
is not in the database.

Transport uses the suite's existing ``requests`` dependency (the same HTTP
client as album-art and acoustid integrations), so no new third-party
dependency is introduced.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from .base import LyricProvider, LyricProviderError, LyricResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://lrclib.net"
_GET_ENDPOINT = f"{_BASE_URL}/api/get"
_USER_AGENT = "AudioSuite-Pro LyricsManager/1.0"
_MAX_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0
_TRANSIENT_STATUSES = frozenset({429, 500, 502, 503})


class LRCLIBProvider(LyricProvider):
    """LRCLIB-backed lyric provider (synced + plain lyrics)."""

    name = "lrclib"

    def __init__(self, base_url: str = _GET_ENDPOINT) -> None:
        """Initialise the provider.

        Args:
            base_url: Override the API endpoint (used by tests).
        """
        self._base_url = base_url

    def search(
        self,
        artist: str,
        title: str,
        *,
        timeout: float = 10.0,
    ) -> LyricResult | None:
        """Query LRCLIB for the exact artist/title pair.

        Transient server responses (HTTP 429/500/502/503) are retried up to
        :data:`_MAX_ATTEMPTS` times with exponential backoff before the
        lookup is reported as failed.

        Args:
            artist: Artist name read from the file's tags.
            title: Track title read from the file's tags.
            timeout: Per-request timeout in seconds.

        Returns:
            :class:`LyricResult` when LRCLIB has any lyric text for the
            track, or None on a 404 (no match).

        Raises:
            LyricProviderError: On transport failure, timeout, malformed
                JSON, an unexpected non-404 HTTP status, or a transient
                server status that exhausted all retries.
        """
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = requests.get(
                    self._base_url,
                    params={"artist_name": artist, "track_name": title},
                    headers={"User-Agent": _USER_AGENT},
                    timeout=timeout,
                )
            except (requests.exceptions.RequestException, OSError) as exc:
                raise LyricProviderError(
                    f"Could not reach LRCLIB for {artist} - {title}: {exc}"
                ) from exc

            status = response.status_code
            if status == 404:
                logger.debug("LRCLIB: no match for %s - %s", artist, title)
                return None
            if status in _TRANSIENT_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                delay = _RETRY_BASE_DELAY * (2**attempt)
                logger.warning(
                    "LRCLIB returned HTTP %s for %s - %s; retrying in %.1fs "
                    "(attempt %d/%d)",
                    status,
                    artist,
                    title,
                    delay,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                )
                time.sleep(delay)
                continue
            if status != 200:
                if status in _TRANSIENT_STATUSES:
                    raise LyricProviderError(
                        f"LRCLIB is busy (HTTP {status}) for {artist} - {title} "
                        f"after {_MAX_ATTEMPTS} attempts; try again later"
                    )
                raise LyricProviderError(
                    f"LRCLIB returned HTTP {status} for {artist} - {title}"
                )
            break

        try:
            payload: dict[str, Any] = response.json()
        except ValueError as exc:
            raise LyricProviderError(
                f"LRCLIB returned unparseable data for {artist} - {title}"
            ) from exc

        synced = self._as_optional_str(payload.get("syncedLyrics"))
        plain = self._as_optional_str(payload.get("plainLyrics"))
        if synced is None and plain is None:
            logger.debug("LRCLIB: no lyric text for %s - %s", artist, title)
            return None

        return LyricResult(
            provider_name=self.name,
            synced_lyrics=synced,
            plain_lyrics=plain,
            track_name=self._as_optional_str(payload.get("trackName")),
            artist_name=self._as_optional_str(payload.get("artistName")),
        )

    @staticmethod
    def _as_optional_str(value: Any) -> str | None:
        """Coerce an API value to a stripped non-empty string or None."""
        if value is None:
            return None
        text = str(value).strip()
        return text or None
