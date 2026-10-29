"""
file_processor.py — batch lyric lookup and embedding for Lyrics Manager.

Built on the shared :class:`BaseFileProcessor` infrastructure (thread pool,
progress tracking, error recovery) with a pluggable lyric provider injected
per batch, so worker threads never share provider state.

Changed in 1.4.0: the worker count resolves from ``default_max_workers()``
when not supplied (PLAN D56). The artist/title and existing-lyrics reads
share one handler load instead of two (PLAN D55).
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import inspect
import logging
import os
import threading
from enum import Enum, auto
from queue import Queue
from typing import Any, Callable

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.constants import cap_workers_to_slot_grid, default_max_workers
from audio_suite_shared.exceptions import AudioTagError, handle_audio_errors
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.lrc_handler import LrcParseError
from audio_suite_shared.tag_helper_base import (
    BaseTagHandler,
    LyricsTags,
    TagHandlerFactory,
)
from audio_suite_shared.tag_helper_writer import write_plain_lyrics, write_synced_lyrics

from .providers import (
    LyricProvider,
    LyricProviderError,
    LyricResult,
    get_provider,
)

logger = logging.getLogger(__name__)


class LyricsProcessor(BaseFileProcessor):
    """Lyric fetch/embed processor using the shared base infrastructure."""

    def __init__(
        self, max_workers: int | None = None, parallel_mode: bool = False
    ) -> None:
        super().__init__(
            operation_type="lyrics_lookup",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


class ProcessingStatus(Enum):
    """Enumeration of processing status values for lyric lookup."""

    DRY_RUN = auto()
    TAGGED = auto()
    SKIPPED = auto()
    ERROR = auto()


def _report(
    lock: threading.Lock,
    on_progress: Callable[..., None],
    *,
    n_skipped: int,
    n_errors: int,
    display: str,
    log: str,
) -> None:
    """Report one file's outcome through the locked progress callback."""
    with lock:
        on_progress(
            n_skipped=n_skipped,
            n_errors=n_errors,
            display_text=display,
            log_text=log,
        )


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    provider: LyricProvider,
    request_timeout: float,
    skip_existing: bool,
    plain_fallback: bool,
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """Fetch and optionally embed lyrics for a single audio file.

    Args:
        name: File name (not full path) of the audio file.
        dir_path: Directory containing the audio file.
        is_dry_run: When True, fetch lyrics but do not write any tags.
        provider: Lyric source used for the lookup.
        request_timeout: Per-request timeout in seconds for the source.
        skip_existing: When True, skip files that already carry lyrics.
        plain_fallback: When True, store unsynced (plain) lyrics when the
            source has no synced text.
        slot_idx: Index of the worker-slot display variable.
        lock: Threading lock that gates calls to on_progress.
        on_progress: Callback with signature (n_skipped, n_errors,
            display_text, log_text) used by BaseFileProcessor.
        **kwargs: Extra keyword arguments forwarded by the base class
            (e.g. slot_vars).
    """
    slot_vars: list[Any] | None = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Looking up: {name[:25]}...")

    full_path: str = os.path.join(dir_path, name)

    handler: BaseTagHandler | None = None
    try:
        handler = TagHandlerFactory.get_handler(full_path)
        artist, title = handler.read_artist_title()
    except Exception:
        logger.exception("Could not read tags from %s", full_path)
        handler = None
        artist, title = "Unknown", "Unknown"

    if artist == "Unknown" or title == "Unknown":
        logger.info("[SKIPPED] %s - no artist/title tags", name)
        _report(
            lock,
            on_progress,
            n_skipped=1,
            n_errors=0,
            display=f"[SKIPPED] {name} → no artist/title tags",
            log=f"[SKIPPED] {name} | no artist/title tags\n",
        )
        return

    if skip_existing:
        existing = handler.read_lyrics_tags() if handler is not None else LyricsTags()
        if existing.has_any:
            logger.info("[SKIPPED] %s - already has lyrics", name)
            _report(
                lock,
                on_progress,
                n_skipped=1,
                n_errors=0,
                display=f"[SKIPPED] {name} → already has lyrics",
                log=f"[SKIPPED] {name} | already has lyrics\n",
            )
            return

    try:
        search_kwargs: dict[str, Any] = {
            "timeout": request_timeout,
        }
        sig = inspect.signature(provider.search)
        if "file_path" in sig.parameters:
            search_kwargs["file_path"] = full_path
        result: LyricResult | None = provider.search(artist, title, **search_kwargs)
    except LyricProviderError as exc:
        logger.error(
            "[LyricProviderError] lookup failed for '%s': %s",
            name,
            exc,
        )
        _report(
            lock,
            on_progress,
            n_skipped=0,
            n_errors=1,
            display=f"[ERROR] {name}: lyric lookup failed",
            log=f"[ERROR] {name}: lyric lookup failed — {exc}\n",
        )
        return

    if result is None or not result.has_lyrics:
        logger.info("[SKIPPED] %s - lyrics not found", name)
        _report(
            lock,
            on_progress,
            n_skipped=1,
            n_errors=0,
            display=f"[SKIPPED] {name} → lyrics not found",
            log=f"[SKIPPED] {name} | lyrics not found\n",
        )
        return

    if is_dry_run:
        kind = "synced" if result.synced_lyrics is not None else "plain"
        logger.info("[DRY RUN] %s - %s lyrics found", name, kind)
        _report(
            lock,
            on_progress,
            n_skipped=0,
            n_errors=0,
            display=f"[DRY RUN] {name} → {kind} lyrics found",
            log=f"[DRY RUN] {name} | {kind} lyrics found\n",
        )
        return

    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")

    status: ProcessingStatus = ProcessingStatus.SKIPPED
    action: str = ""

    if result.synced_lyrics is not None:
        try:
            write_synced_lyrics(full_path, result.synced_lyrics)
            status = ProcessingStatus.TAGGED
            action = "synced lyrics"
            logger.info("[TAGGED] %s - synced lyrics", name)
        except (AudioTagError, LrcParseError) as exc:
            if plain_fallback and result.plain_lyrics is not None:
                write_plain_lyrics(full_path, result.plain_lyrics)
                status = ProcessingStatus.TAGGED
                action = "plain lyrics (synced unsupported)"
                logger.info("[TAGGED] %s - plain lyrics (synced unsupported)", name)
            else:
                logger.error(
                    "[ERROR] %s: could not embed synced lyrics - %s",
                    name,
                    exc,
                    exc_info=True,
                )
                _report(
                    lock,
                    on_progress,
                    n_skipped=0,
                    n_errors=1,
                    display=f"[ERROR] {name}: could not embed synced lyrics",
                    log=f"[ERROR] {name}: could not embed synced lyrics — {exc}\n",
                )
                return
    elif plain_fallback and result.plain_lyrics is not None:
        write_plain_lyrics(full_path, result.plain_lyrics)
        status = ProcessingStatus.TAGGED
        action = "plain lyrics"
        logger.info("[TAGGED] %s - plain lyrics", name)
    else:
        action = "plain only (plain fallback disabled)"
        logger.info("[SKIPPED] %s - %s", name, action)

    _report(
        lock,
        on_progress,
        n_skipped=1 if status == ProcessingStatus.SKIPPED else 0,
        n_errors=0,
        display=f"[{status.name}] {name} → {action}",
        log=f"[{status.name}] {name} | {action}\n",
    )


@handle_audio_errors(reraise=False, context="lyrics_manager_run_fetch")
def run_fetch(
    dir_path: str,
    is_dry_run: bool,
    provider_name: str,
    request_timeout: float,
    skip_existing: bool,
    plain_fallback: bool,
    slot_vars: list[Any],
    slot_queue: Queue,  # type: ignore[type-arg]  # kept for interface compatibility
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    parallel_mode: bool = False,
    max_workers: int | None = None,
) -> None:
    """Run the batch lyric lookup using shared BaseFileProcessor infrastructure.

    *slot_queue* is accepted for API compatibility but is managed internally
    by BaseFileProcessor.  Tag snapshots are recorded against the active undo
    batch when the caller (the Master Driver) opened one.

    Args:
        dir_path: Directory of audio files to process.
        is_dry_run: When True, fetch only — do not write tags.
        provider_name: Registered lyric provider identifier (e.g. ``'lrclib'``).
        request_timeout: Per-request timeout in seconds.
        skip_existing: When True, skip files that already carry lyrics.
        plain_fallback: When True, store unsynced lyrics when the source has
            no synced text.
        slot_vars: List of tk.StringVar for worker-slot status labels.
        slot_queue: Accepted for interface compatibility; not used directly.
        on_progress: UI progress callback forwarded to BaseFileProcessor.
        on_complete: Completion callback forwarded to BaseFileProcessor.
        on_error: Error callback forwarded to BaseFileProcessor.
        parallel_mode: When True, use the configured worker count; when False
            process serially.
        max_workers: Number of parallel workers.  Defaults to
            ``default_max_workers()``.
    """
    logger.info(
        "run_fetch: dir=%s dry_run=%s provider=%s timeout=%s "
        "skip_existing=%s plain_fallback=%s parallel=%s workers=%s",
        dir_path,
        is_dry_run,
        provider_name,
        request_timeout,
        skip_existing,
        plain_fallback,
        parallel_mode,
        max_workers,
    )

    provider: LyricProvider = get_provider(provider_name)
    # A typed count can exceed the caller's slot grid; the worker writes
    # slot_vars[slot_idx], so cap the pool at the grid (D66).
    effective_workers = cap_workers_to_slot_grid(
        max_workers or default_max_workers(), slot_vars
    )
    processor = LyricsProcessor(
        max_workers=effective_workers if parallel_mode else 1,
        parallel_mode=parallel_mode,
    )

    undo_batch: str | None = get_active_batch_id()

    def processor_func(
        filename: str,
        dir_path: str,
        slot_idx: int,
        lock: threading.Lock,
        on_progress: Callable[..., None],
        **kwargs: object,
    ) -> None:
        with use_batch(undo_batch):
            process_single_file(
                name=filename,
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                provider=provider,
                request_timeout=request_timeout,
                skip_existing=skip_existing,
                plain_fallback=plain_fallback,
                slot_idx=slot_idx,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
                **kwargs,
            )

    processor.run_parallel_processing(
        dir_path=dir_path,
        processor_func=processor_func,
        on_progress=on_progress,
        on_complete=on_complete,
        on_error=on_error,
        extensions=SUPPORTED_EXTENSIONS,
    )
