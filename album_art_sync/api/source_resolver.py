"""
source_resolver.py — Orchestrates the prioritised artwork source fallback chain.
MusicBrainz → Fanart.tv → Deezer → iTunes Store.
"""

from collections.abc import Callable
from typing import Any

from ..core.ranker import RankedCandidate
from . import deezer, fanart, itunes, musicbrainz


def resolve(
    artist: str,
    album: str,
    fanart_config: dict[str, Any],
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_pick: Callable[[list[RankedCandidate], str, str], bytes | None],
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
) -> tuple[bytes | None, str | None]:
    """
    Try each artwork source in priority order.

    Each API module now calls ``filter_and_rank()`` internally before
    passing candidates to *on_pick*, so all callers receive pre-filtered,
    quality-ranked candidate lists.

    Parameters
    ----------
    artist, album:
        Lookup terms passed to each source.
    fanart_config:
        Configuration dict for Fanart.tv (app_key, client_key).
    log:
        Logging callback.
    cancel_flag:
        Returns True if the user/caller has requested cancellation.
    on_pick:
        Called with ``(ranked_candidates, artist, engine)`` after
        filtering and ranking.  Must return image bytes or None.
    min_art_dimension:
        Minimum image dimension in pixels (forwarded to filter_and_rank).
    album_match_threshold:
        Fuzzy-match threshold for album name (forwarded to filter_and_rank).

    Returns:
        (image_bytes, source_name) or (None, None) if nothing found.
    """
    # Step 1 — MusicBrainz IDs (needed for Fanart.tv)
    mb_rg_ids = musicbrainz.query(artist, album, log, cancel_flag)
    if cancel_flag():
        return None, None

    # Step 2 — Fanart.tv (requires MB IDs)
    if mb_rg_ids:
        img = fanart.query(
            artist,
            album,
            mb_rg_ids,
            fanart_config,
            log,
            cancel_flag,
            on_pick,
            min_art_dimension=min_art_dimension,
            album_match_threshold=album_match_threshold,
        )
        if img:
            return img, "Fanart.tv"
    if cancel_flag():
        return None, None

    # Step 3 — Deezer
    img = deezer.query(
        artist,
        album,
        log,
        cancel_flag,
        on_pick,
        min_art_dimension=min_art_dimension,
        album_match_threshold=album_match_threshold,
    )
    if img:
        return img, "Deezer"
    if cancel_flag():
        return None, None

    # Step 4 — iTunes Store (last resort)
    img = itunes.query(
        artist,
        album,
        log,
        cancel_flag,
        on_pick,
        min_art_dimension=min_art_dimension,
        album_match_threshold=album_match_threshold,
    )
    if img:
        return img, "iTunes Store"

    return None, None
