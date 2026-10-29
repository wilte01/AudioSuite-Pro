"""
fanart.py — Fanart.tv album art lookup.
Candidates are filtered and ranked via ``filter_and_rank()`` before being
passed to the selection callback, regardless of run mode.
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

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


def query(
    artist: str,
    album: str,
    mb_rg_ids: list[str],
    fanart_config: dict[str, Any],
    log: Callable[[str], None],
    cancel_flag: Callable[[], bool],
    on_pick: Callable[[list[RankedCandidate], str, str], Optional[bytes]],
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
) -> Optional[bytes]:
    """
    Search Fanart.tv for album artwork using MusicBrainz IDs.

    on_pick(ranked_candidates, artist, engine) -> bytes | None
        Receives a pre-filtered, quality-ranked list of candidates.
        In interactive mode this opens the PickerDialog; in headless
        mode it auto-selects the top candidate.
    """
    if not mb_rg_ids:
        return None

    app_key = fanart_config.get("app_key", "")
    if not app_key:
        log("  -> Fanart.tv: No API key configured")
        return None

    client_key = fanart_config.get("client_key", "")

    log("  -> Querying Fanart.tv...")
    for rg_id in mb_rg_ids:
        if cancel_flag():
            return None

        sanitized_rg_id = InputValidator.sanitize_api_input(rg_id)
        if not sanitized_rg_id:
            log("    [X] Invalid MusicBrainz ID format")
            continue

        try:
            response = http.get(
                f"https://webservice.fanart.tv/v3/music/albums/{sanitized_rg_id}",
                params={"api_key": app_key, "client_key": client_key},
                timeout=CONFIG["REQUEST_TIMEOUT"],
                verify=True,
            )
            if response.status_code == 200:
                data = response.json()
                covers = (
                    data.get("albums", {})
                    .get(sanitized_rg_id, {})
                    .get("albumcover", [])
                )
                if covers:
                    raw_items = [
                        {
                            "url": c["url"],
                            "title": f"Fanart ({c.get('likes', '0')} likes)",
                        }
                        for c in covers
                    ]

                    ranked = filter_and_rank(
                        raw_items,
                        query_album=album,
                        source_name="Fanart.tv",
                        is_trusted_source=True,
                        min_dimension=min_art_dimension,
                        match_threshold=album_match_threshold,
                        log=log,
                    )
                    if ranked:
                        log(f"    [OK] {len(ranked)} candidate(s) passed guardrails")
                        img_data = on_pick(ranked, artist, "Fanart.tv")
                        if img_data:
                            return img_data

        except requests.exceptions.SSLError as exc:
            error_msg = SecureErrorHandler.handle_network_error(exc, "Fanart.tv")
            log(f"    [X] {error_msg}")
        except requests.exceptions.Timeout as exc:
            error_msg = SecureErrorHandler.handle_network_error(exc, "Fanart.tv")
            log(f"    [X] {error_msg}")
        except requests.exceptions.RequestException as exc:
            error_msg = SecureErrorHandler.handle_api_error(exc, "Fanart.tv")
            log(f"    [X] {error_msg}")
        except (KeyError, ValueError) as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            error_msg = SecureErrorHandler.handle_error(exc, "Fanart.tv lookup")
            log(f"    [X] {error_msg}")

    log("    [X] No covers found on Fanart.tv")
    return None
