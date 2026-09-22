"""Non-interactive pipeline — resolve artwork and apply to all files in a directory."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from audio_suite_shared.exceptions import (
    AudioConfigurationError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_album_artist,
    read_artist_album,
)

from ..api import source_resolver
from ..config.settings import CONFIG, load_config
from .artwork_applier import apply as apply_artwork
from .ranker import RankedCandidate

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ArtSyncReport:
    """Result of one ``resolve_and_apply()`` call."""

    success: bool
    source: str | None
    total_files: int
    processed: int
    skipped: int
    errors: int
    duration_secs: float
    log_entries: list[str] = field(default_factory=list)
    selection_audit: str | None = None


def _no_op(**kwargs: Any) -> None:
    pass


def _auto_select_pick(
    ranked_candidates: list[RankedCandidate],
    artist: str,
    engine: str,
) -> bytes | None:
    """Auto-select the top-ranked candidate and download its image bytes.

    Used by both the CLI and Master Driver (headless) paths.
    """
    if not ranked_candidates:
        return None
    best = ranked_candidates[0]
    logger.info(
        "Auto-selected from %s: %s (%dx%d)",
        engine,
        best.title,
        best.width,
        best.height,
    )
    return _download_image(best.url)


def _download_image(url: str) -> bytes | None:
    """Download full image bytes from *url*."""
    from album_art_sync.api.session import http

    try:
        resp = http.get(url, timeout=CONFIG["REQUEST_TIMEOUT"])
        resp.raise_for_status()
        return resp.content
    except (requests.RequestException, OSError) as exc:
        logger.warning("Failed to download image from %s: %s", url, exc)
        return None


@handle_audio_errors(reraise=False, context="art_sync_resolve_and_apply")
def resolve_and_apply(
    directory: str | os.PathLike[str],
    *,
    embed_size: int = 800,
    purge: bool = True,
    auto_select: bool = True,
    dry_run: bool = False,
    min_art_dimension: int = 500,
    album_match_threshold: float = 0.85,
    progress_callback: Callable[..., Any] | None = None,
    log_callback: Callable[..., Any] | None = None,
) -> ArtSyncReport:
    """Resolve artwork from all sources and apply to all files in *directory*.

    Parameters
    ----------
    directory:
        Path to a directory containing audio files.
    embed_size:
        Maximum pixel dimension for embedded tag image (200–2000).
    purge:
        Whether to delete hidden Windows thumbnail files before writing.
    auto_select:
        If True, automatically pick the highest-ranked candidate.
    dry_run:
        If True, fetch and rank candidates but do not write anything.
    min_art_dimension:
        Minimum image dimension in pixels; smaller candidates are rejected.
    album_match_threshold:
        Fuzzy-match threshold (0.0–1.0) for album name verification.
    progress_callback:
        Called with keyword arguments (processed=, total=, display_text=)
        matching the convention used by other AudioSuite CLI tools.
    log_callback:
        Called with ``display_text=`` keyword for each log line.

    Returns
    -------
    ArtSyncReport
        Summary of the operation including audit trail.
    """
    if progress_callback is None:
        progress_callback = _no_op
    if log_callback is None:
        log_callback = _no_op

    path = os.fspath(directory)
    log_entries: list[str] = []
    selection_audit_lines: list[str] = []
    start = time.monotonic()

    def _log(msg: str) -> None:
        log_entries.append(msg + "\n")
        log_callback(display_text=msg)

    def _audit(msg: str) -> None:
        selection_audit_lines.append(msg)
        _log(msg)

    if not os.path.isdir(path):
        _log(f"Error: directory does not exist: {path}")
        return ArtSyncReport(
            success=False,
            source=None,
            total_files=0,
            processed=0,
            skipped=0,
            errors=1,
            duration_secs=time.monotonic() - start,
            log_entries=log_entries,
        )

    files = [
        f for f in os.listdir(path) if f.lower().endswith(tuple(SUPPORTED_EXTENSIONS))
    ]
    if not files:
        _log("Error: no supported audio files found in directory")
        return ArtSyncReport(
            success=False,
            source=None,
            total_files=0,
            processed=0,
            skipped=0,
            errors=1,
            duration_secs=time.monotonic() - start,
            log_entries=log_entries,
        )

    first_file = os.path.join(path, files[0])
    try:
        artist, album = read_artist_album(first_file)
        album_artist = read_album_artist(first_file)
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        _log(f"Error reading file metadata: {user_message_for(mapped)}")
        return ArtSyncReport(
            success=False,
            source=None,
            total_files=len(files),
            processed=0,
            skipped=0,
            errors=1,
            duration_secs=time.monotonic() - start,
            log_entries=log_entries,
        )

    lookup_artist = album_artist if album_artist else artist
    _audit(f'Artist: "{lookup_artist}"  Album: "{album}"')
    _audit("Sources queried: MusicBrainz → Fanart.tv → Deezer → iTunes")
    _audit("")
    _log(f"Files: {len(files)} audio file(s)")

    app_config = load_config(__file__)
    on_pick: Callable[..., Any]
    if auto_select:
        on_pick = _auto_select_pick
    else:
        raise AudioConfigurationError(
            "Non-auto-select mode requires a custom on_pick callback; "
            "use source_resolver.resolve() directly for interactive use."
        )

    img_raw, source_used = source_resolver.resolve(
        artist=lookup_artist,
        album=album,
        fanart_config=app_config.get("fanart", {}),
        log=_log,
        cancel_flag=lambda: False,
        on_pick=on_pick,
        min_art_dimension=min_art_dimension,
        album_match_threshold=album_match_threshold,
    )

    if img_raw and source_used:
        _audit(f"✓ Selected from {source_used}")
        _log("")

        if dry_run:
            _log(f"[Dry Run] Would apply artwork from {source_used}")
            _log(f"[Dry Run] Would embed at {embed_size}×{embed_size}")
            _log(f"[Dry Run] Purge={'yes' if purge else 'no'}")
            processed = len(files)
        else:
            _log(f"Artwork retrieved from {source_used}")
            mode = "Update Artwork"
            success_flag = apply_artwork(
                path=path,
                files=files,
                img_raw=img_raw,
                mode=mode,
                embed_size=embed_size,
                purge=purge,
                log=_log,
                cancel_flag=lambda: False,
                on_file_progress=lambda i: progress_callback(
                    processed=i,
                    total=len(files),
                    display_text=f"Processed {i}/{len(files)} files",
                ),
            )
            processed = len(files) if success_flag else 0
    else:
        source_used = None
        _audit("✗ No artwork found from any source")
        processed = 0

    elapsed = time.monotonic() - start
    return ArtSyncReport(
        success=img_raw is not None,
        source=source_used,
        total_files=len(files),
        processed=processed,
        skipped=0,
        errors=0,
        duration_secs=elapsed,
        log_entries=log_entries,
        selection_audit="\n".join(selection_audit_lines),
    )
