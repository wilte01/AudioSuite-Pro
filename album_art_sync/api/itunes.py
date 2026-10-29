"""
itunes.py — iTunes Store album art lookup.
Candidates are filtered and ranked via ``filter_and_rank()`` before being
passed to the selection callback.
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
from typing import Callable, Optional

import requests

from audio_suite_shared.exceptions import map_to_audio_error

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
    """Search iTunes Store for album artwork.

    ``filter_and_rank()`` is called with ``is_trusted_source=False`` so
    album-name fuzzy matching is applied.  Only candidates that pass both
    the name filter and the minimum-dimension threshold reach *on_pick*.
    """
    try:
        log("  -> Querying iTunes Store...")
        response = http.get(
            "https://itunes.apple.com/search",
            params={"term": f"{artist} {album}", "entity": "album"},
            timeout=CONFIG["REQUEST_TIMEOUT"],
        )
        response.raise_for_status()
        data = response.json()

        raw_items = [
            {
                "url": x.get("artworkUrl100", "").replace("100x100bb", "1200x1200bb"),
                "title": x.get("collectionName", ""),
            }
            for x in data.get("results", [])
            if x.get("artworkUrl100")
        ]

        if not raw_items:
            log("    [X] No results found")
            return None

        ranked = filter_and_rank(
            raw_items,
            query_album=album,
            source_name="iTunes Store",
            is_trusted_source=False,
            min_dimension=min_art_dimension,
            match_threshold=album_match_threshold,
            log=log,
        )
        if not ranked:
            log("    [X] No candidates passed guardrails")
            return None

        log(f"    [OK] {len(ranked)} candidate(s) passed guardrails")
        return on_pick(ranked, artist, "iTunes Store")

    except requests.Timeout:
        log("    [X] iTunes timeout")
    except requests.RequestException as exc:
        log(f"    [X] iTunes error: {exc}")
    except (KeyError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("%s: %s", type(mapped).__name__, mapped, exc_info=True)
        log(f"    [X] Unexpected error: {exc}")
    return None
