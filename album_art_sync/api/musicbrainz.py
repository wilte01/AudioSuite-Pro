"""
musicbrainz.py — MusicBrainz release lookup.
Pure network logic; logging via injected callback.
"""

import logging
from typing import Callable

import requests

from audio_suite_shared.exceptions import map_to_audio_error

from ..config.settings import CONFIG
from .session import http

logger = logging.getLogger(__name__)


def escape_lucene(text: str) -> str:
    """Escape special characters for Lucene/MusicBrainz query syntax.

    The backslash is escaped first in a dedicated pre-pass so that
    subsequently-inserted escape prefixes are not themselves re-escaped.
    """
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    for char in r'+-&|!(){}[]^"~*?:/':
        text = text.replace(char, f"\\{char}")
    return text


def query(
    artist: str, album: str, log: Callable[[str], None], cancel_flag: Callable[[], bool]
) -> list[str]:
    """
    Look up MusicBrainz release-group IDs for the given artist/album.

    Returns:
        List of release-group UUID strings (may be empty on failure).
    """
    try:
        log("  → Querying MusicBrainz...")
        response = http.get(
            "https://musicbrainz.org/ws/2/release",
            params={
                "query": (
                    f'release:"{escape_lucene(album)}"'
                    f' AND artist:"{escape_lucene(artist)}"'
                ),
                "fmt": "json",
            },
            timeout=CONFIG["REQUEST_TIMEOUT"],
        )
        response.raise_for_status()
        data = response.json()

        rg_ids = [
            r["release-group"]["id"]
            for r in data.get("releases", [])[: CONFIG["MAX_API_RESULTS"]]
            if "release-group" in r
        ]

        if rg_ids:
            log(f"    ✓ Found {len(rg_ids)} release group(s)")
        else:
            log("    ✗ No releases found")
        return rg_ids

    except requests.Timeout:
        log("    ✗ MusicBrainz timeout")
    except requests.RequestException as exc:
        log(f"    ✗ MusicBrainz error: {exc}")
    except (KeyError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        log(f"    ✗ Unexpected error: {exc}")
    return []
