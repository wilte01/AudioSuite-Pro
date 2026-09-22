"""
deezer.py — Deezer album art lookup.
Candidates are filtered and ranked via ``filter_and_rank()`` before being
passed to the selection callback.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import requests

from ..config.settings import CONFIG
from ..core.candidate_filter import filter_and_rank
from ..core.ranker import RankedCandidate
from .session import http

logger = logging.getLogger(__name__)


def query(
    artist: str,
    album: str,
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_pick: Callable[[list[RankedCandidate], str, str], Optional[bytes]],
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
) -> Optional[bytes]:
    """Search Deezer for album artwork.

    ``filter_and_rank()`` is called with ``is_trusted_source=False`` so
    album-name fuzzy matching is applied.  Only candidates that pass both
    the name filter and the minimum-dimension threshold reach *on_pick*.
    """
    try:
        log("  → Querying Deezer...")
        response = http.get(
            "https://api.deezer.com/search/album",
            params={"q": f'artist:"{artist}" album:"{album}"'},
            timeout=CONFIG["REQUEST_TIMEOUT"],
        )
        response.raise_for_status()
        data = response.json()

        raw_items = [
            {"url": x.get("cover_xl", ""), "title": x.get("title", "")}
            for x in data.get("data", [])
            if x.get("cover_xl")
        ]

        if not raw_items:
            log("    ✗ No results found")
            return None

        ranked = filter_and_rank(
            raw_items,
            query_album=album,
            source_name="Deezer",
            is_trusted_source=False,
            min_dimension=min_art_dimension,
            match_threshold=album_match_threshold,
            log=log,
        )
        if not ranked:
            log("    ✗ No candidates passed guardrails")
            return None

        log(f"    ✓ {len(ranked)} candidate(s) passed guardrails")
        return on_pick(ranked, artist, "Deezer")

    except requests.Timeout:
        logger.warning("Deezer request timed out", exc_info=True)
        log("    ✗ Deezer timeout")
    except requests.RequestException as exc:
        logger.warning("Deezer request failed: %s", exc, exc_info=True)
        log(f"    ✗ Deezer error: {exc}")
    except (KeyError, ValueError) as exc:
        logger.error("Deezer unexpected error: %s", exc, exc_info=True)
        log(f"    ✗ Unexpected error: {exc}")
    return None
