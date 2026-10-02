"""caa.py — Cover Art Archive album art lookup.

Cover Art Archive is the canonical MusicBrainz-keyed cover source (the one
Picard uses): it needs no API key, and its release endpoint keys exactly on
the ``MUSICBRAINZ_ALBUMID`` the Audio Fingerprinter's identifier write puts on
files. When no release id is available the provider falls back to the
release-group ids the existing MusicBrainz ID lookup already resolves.

Candidates are filtered and ranked via ``filter_and_rank()`` like every
other source. CAA is a trusted source: the evidence is the MusicBrainz id
the art is keyed on, so album-name fuzzy matching is skipped. A 404 is the
service's normal "no art for this release" answer and is logged as a miss,
not an error.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

import requests

from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.security.error_handler import SecureErrorHandler
from audio_suite_shared.security.input_validator import InputValidator

from ..config.settings import CONFIG
from ..core.candidate_filter import filter_and_rank
from ..core.ranker import RankedCandidate
from .session import http

logger = logging.getLogger(__name__)

CAA_BASE_URL = "https://coverartarchive.org"


def _raw_candidates(images: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build raw filter candidates from a CAA ``images`` payload.

    Front covers are what an album-cover sync embeds, so fronts win when any
    exist; a release whose images carry no Front type at all still yields its
    untyped images rather than nothing.
    """
    fronts: list[dict[str, str]] = []
    others: list[dict[str, str]] = []
    for image in images:
        url = str(image.get("image", "") or "")
        if not url:
            continue
        types = image.get("types") or []
        is_front = bool(image.get("front")) or "Front" in types
        label = "front" if is_front else "/".join(str(t) for t in types) or "image"
        approved = "approved" if image.get("approved") else "unapproved"
        entry = {"url": url, "title": f"CAA {label} ({approved})"}
        (fronts if is_front else others).append(entry)
    return fronts or others


def query(
    artist: str,
    album: str,
    release_mbid: str,
    mb_rg_ids: list[str],
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_pick: Callable[[list[RankedCandidate], str, str], Optional[bytes]],
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
) -> Optional[bytes]:
    """
    Search the Cover Art Archive for album artwork using MusicBrainz ids.

    The release endpoint (exact, preferred) is queried first when
    *release_mbid* is present — the ``MUSICBRAINZ_ALBUMID`` read from the
    album's files; then each release-group id from the MusicBrainz ID lookup
    is tried in turn.

    on_pick(ranked_candidates, artist, engine) -> bytes | None
        Receives a pre-filtered, quality-ranked list of candidates.

    Returns:
        Image bytes chosen by *on_pick*, or None when the archive holds no
        usable art for any of the ids.
    """
    lookups: list[tuple[str, str]] = []
    if release_mbid:
        lookups.append(("release", release_mbid))
    for rg_id in mb_rg_ids:
        lookups.append(("release-group", rg_id))

    if not lookups:
        log("  → Cover Art Archive: no MusicBrainz ids available")
        return None

    log("  → Querying Cover Art Archive...")
    for kind, mbid in lookups:
        if cancel_flag():
            return None

        sanitized = InputValidator.sanitize_api_input(mbid)
        if not sanitized:
            log("    ✗ Invalid MusicBrainz ID format")
            continue

        try:
            response = http.get(
                f"{CAA_BASE_URL}/{kind}/{sanitized}",
                timeout=CONFIG["REQUEST_TIMEOUT"],
                verify=True,
            )
            if response.status_code == 404:
                # The archive's normal "no art for this release" answer.
                log(f"    ✗ No cover art found for {kind} {sanitized}")
                continue
            if response.status_code != 200:
                log(f"    ✗ Cover Art Archive error (HTTP {response.status_code})")
                continue
            payload = response.json()
            # A well-formed body is an object; anything else (HTML error page
            # parsed as JSON, a bare list) is treated as "no art" rather than
            # allowed to break the whole source chain.
            images = payload.get("images", []) if isinstance(payload, dict) else []
        except requests.exceptions.SSLError as exc:
            error_msg = SecureErrorHandler.handle_network_error(exc, "CAA")
            log(f"    ✗ {error_msg}")
            continue
        except requests.exceptions.Timeout as exc:
            error_msg = SecureErrorHandler.handle_network_error(exc, "CAA")
            log(f"    ✗ {error_msg}")
            continue
        except requests.exceptions.RequestException as exc:
            error_msg = SecureErrorHandler.handle_api_error(exc, "CAA")
            log(f"    ✗ {error_msg}")
            continue
        except (KeyError, ValueError) as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            error_msg = SecureErrorHandler.handle_error(exc, "CAA lookup")
            log(f"    ✗ {error_msg}")
            continue

        if not images:
            continue

        raw_items = _raw_candidates(images)
        if not raw_items:
            continue
        ranked = filter_and_rank(
            raw_items,
            query_album=album,
            source_name="Cover Art Archive",
            is_trusted_source=True,
            min_dimension=min_art_dimension,
            match_threshold=album_match_threshold,
            log=log,
        )
        if ranked:
            log(f"    ✓ {len(ranked)} candidate(s) passed guardrails")
            img_data = on_pick(ranked, artist, "Cover Art Archive")
            if img_data:
                return img_data

    log("    ✗ No covers found on Cover Art Archive")
    return None
