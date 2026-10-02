"""
source_resolver.py — Orchestrates the prioritised artwork source fallback chain.
Cover Art Archive (MBID-keyed) → Fanart.tv → Deezer → iTunes Store.

The MusicBrainz step is an *id* lookup, not an art source: it feeds both the
Cover Art Archive release-group endpoint and Fanart.tv. When the album's
files carry a ``MUSICBRAINZ_ALBUMID`` (the fingerprinter's identifier write),
the Cover Art Archive release endpoint is queried before anything else — an
exact, keyless, canonical hit.
"""

from collections.abc import Callable
from typing import Any

from ..core.ranker import RankedCandidate
from . import caa, deezer, fanart, itunes, musicbrainz


def resolve(
    artist: str,
    album: str,
    fanart_config: dict[str, Any],
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_pick: Callable[[list[RankedCandidate], str, str], bytes | None],
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
    album_mbid: str = "",
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
    album_mbid:
        MusicBrainz release MBID read from the album's files, when present.
        Keys the exact Cover Art Archive release lookup (E2's output).

    Returns:
        (image_bytes, source_name) or (None, None) if nothing found.
    """
    # Step 1 — Cover Art Archive, exact-keyed on the file's release MBID.
    if album_mbid:
        img = caa.query(
            artist,
            album,
            release_mbid=album_mbid,
            mb_rg_ids=[],
            log=log,
            cancel_flag=cancel_flag,
            on_pick=on_pick,
            min_art_dimension=min_art_dimension,
            album_match_threshold=album_match_threshold,
        )
        if img:
            return img, "Cover Art Archive"
        if cancel_flag():
            return None, None

    # Step 2 — MusicBrainz ids (needed by Fanart.tv and the CAA
    # release-group fallback).
    mb_rg_ids = musicbrainz.query(artist, album, log, cancel_flag)
    if cancel_flag():
        return None, None

    # Step 3 — Cover Art Archive by release group.
    if mb_rg_ids:
        img = caa.query(
            artist,
            album,
            release_mbid="",
            mb_rg_ids=mb_rg_ids,
            log=log,
            cancel_flag=cancel_flag,
            on_pick=on_pick,
            min_art_dimension=min_art_dimension,
            album_match_threshold=album_match_threshold,
        )
        if img:
            return img, "Cover Art Archive"
        if cancel_flag():
            return None, None

    # Step 4 — Fanart.tv (requires MB ids)
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

    # Step 5 — Deezer
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

    # Step 6 — iTunes Store (last resort)
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
