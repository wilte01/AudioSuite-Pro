"""
file_processor.py — Album Art Normalizer processing using BaseFileProcessor.

Eliminates duplicated threading/error-handling by delegating to shared
BaseFileProcessor infrastructure while preserving identical behaviour.

Changed in 1.4.0: the worker count resolves from ``default_max_workers()``
when not supplied (PLAN D56).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any, Optional

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.constants import default_max_workers
from audio_suite_shared.exceptions import AudioSuiteError, handle_audio_errors
from audio_suite_shared.file_processor_base import BaseFileProcessor

from .art_processor import (
    AudioTagReadError,
    AudioTagWriteError,
    ImageDecodeError,
    process_audio_artwork,
    process_flac_artwork,
    process_mp3_artwork,
)

logger = logging.getLogger(__name__)


class ArtNormalizerProcessor(BaseFileProcessor):
    """Album artwork normalizer using shared BaseFileProcessor infrastructure."""

    def __init__(self, max_workers: int | None = None) -> None:
        super().__init__(
            operation_type="art_normalization",
            max_workers=max_workers,
        )


def _normalize_single_file(
    name: str,
    dir_path: str,
    target_size: tuple[int, int],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    undo_batch: Optional[str] = None,
    dry_run: bool = False,
    **kwargs: Any,
) -> None:
    """Process a single audio file: inspect and normalise embedded artwork.

    Args:
        name: File name (not full path) of the audio file.
        dir_path: Directory containing the audio file.
        target_size: Desired ``(width, height)`` for embedded artwork.
        slot_idx: Index of the worker-slot display variable.
        lock: Threading lock that gates calls to on_progress.
        on_progress: Callback with signature ``(n_skipped, n_errors,
            display_text, log_text)`` used by BaseFileProcessor.
        undo_batch: Active undo batch id captured by the orchestrating
            thread; worker threads join it via :func:`use_batch` so shared
            embed snapshots are recorded against the run's batch.
        dry_run: When True, every format processor previews the resize and
            writes nothing (no embed, no undo snapshot).
        **kwargs: Extra keyword arguments (slot_vars, etc.).
    """
    path = Path(dir_path) / name
    suffixes = {
        ".mp3": process_mp3_artwork,
        ".flac": process_flac_artwork,
        ".ogg": process_audio_artwork,
        ".opus": process_audio_artwork,
        ".m4a": process_audio_artwork,
        ".mp4": process_audio_artwork,
        ".wav": process_audio_artwork,
        ".aiff": process_audio_artwork,
        ".aif": process_audio_artwork,
    }
    processor = suffixes.get(path.suffix.lower())

    slot_vars = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Processing: {name[:25]}...")

    if processor is None:
        display = f"[SKIPPED] {name} — unsupported format"
        log_line = f"[SKIPPED] {name} | unsupported format\n"
        with lock:
            on_progress(
                n_skipped=1, n_errors=0, display_text=display, log_text=log_line
            )
        return

    with use_batch(undo_batch):
        try:
            outcome = processor(path, target_size, dry_run)
            # A dry run reports the resize it *would* apply, so it counts as an
            # update even though its outcome text never claims a save.
            updated = "resized" in outcome and ("saved" in outcome or dry_run)
            if updated:
                display = f"[UPDATED] {name} → {outcome}"
                log_line = f"[UPDATED] {name} | {outcome}\n"
                logger.info("[UPDATED] %s — %s", name, outcome)
                with lock:
                    on_progress(
                        n_skipped=0, n_errors=0, display_text=display, log_text=log_line
                    )
            else:
                display = f"[SKIPPED] {name} — {outcome}"
                log_line = f"[SKIPPED] {name} | {outcome}\n"
                with lock:
                    on_progress(
                        n_skipped=1, n_errors=0, display_text=display, log_text=log_line
                    )
        except (
            AudioTagReadError,
            AudioTagWriteError,
            ImageDecodeError,
            AudioSuiteError,
        ) as exc:
            logger.exception("Handled error processing %s", name)
            display = f"[ERROR] {name}: {exc}"
            log_line = f"[ERROR] {name} — {exc}\n"
            with lock:
                on_progress(
                    n_skipped=0, n_errors=1, display_text=display, log_text=log_line
                )
        except (OSError, ValueError):
            logger.exception("Unexpected error processing %s", name)
            display = f"[ERROR] {name}: unexpected error"
            log_line = f"[ERROR] {name} | unexpected error\n"
            with lock:
                on_progress(
                    n_skipped=0, n_errors=1, display_text=display, log_text=log_line
                )


@handle_audio_errors(reraise=False, context="art_normalizer_run")
def run_normalization(
    dir_path: str,
    target_size: tuple[int, int],
    slot_vars: Optional[list[Any]] = None,
    slot_queue: Optional[Queue[int]] = None,
    on_progress: Optional[Callable[..., None]] = None,
    on_complete: Optional[Callable[..., None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    max_workers: int | None = None,
    is_dry_run: bool = False,
) -> None:
    """Run parallel album artwork normalisation using BaseFileProcessor.

    Args:
        dir_path: Directory containing audio files.
        target_size: Desired ``(width, height)`` for embedded artwork.
        slot_vars: List of tk.StringVar for worker-slot status labels.
        slot_queue: Pool of available worker-slot indices.  Declared so the
            ``cli_base._run_tool`` call — which supplies one for every CLI
            invocation — does not raise ``TypeError``.  ``BaseFileProcessor``
            allocates its own pool internally and passes it to the workers, so
            this value is absorbed and unused, exactly as in
            ``audio_enhancer``'s and ``genre_sync``'s ``run_*``.  Forwarding it
            instead would raise ``got multiple values for argument
            'slot_queue'`` from ``_process_with_recovery``.
        on_progress: UI progress callback forwarded to BaseFileProcessor.
        on_complete: Completion callback forwarded to BaseFileProcessor.
        on_error: Error callback forwarded to BaseFileProcessor.
        max_workers: Number of parallel workers (defaults to
            ``default_max_workers()``).
        is_dry_run: When True, each file's artwork is decoded, measured and
            re-encoded but nothing is embedded, so neither the file nor an
            undo snapshot is written.
    """
    logger.info(
        "run_normalization: dir=%s target=%dx%d workers=%d dry_run=%s",
        dir_path,
        target_size[0],
        target_size[1],
        max_workers or default_max_workers(),
        is_dry_run,
    )

    undo_batch = get_active_batch_id()

    processor = ArtNormalizerProcessor(max_workers=max_workers)

    def processor_func(
        filename: str,
        dir_path: str,
        slot_idx: int,
        lock: threading.Lock,
        on_progress: Callable[..., None],
        **kwargs: Any,
    ) -> None:
        _normalize_single_file(
            name=filename,
            dir_path=dir_path,
            target_size=target_size,
            slot_idx=slot_idx,
            lock=lock,
            on_progress=on_progress,
            undo_batch=undo_batch,
            dry_run=is_dry_run,
            slot_vars=slot_vars,
            **kwargs,
        )

    # BaseFileProcessor requires live callbacks; fall back to no-ops when a
    # caller (e.g. the CLI) omits them.
    progress_cb = on_progress if on_progress is not None else (lambda **kw: None)
    complete_cb = on_complete if on_complete is not None else (lambda **kw: None)
    error_cb = on_error if on_error is not None else (lambda msg: None)

    processor.run_parallel_processing(
        dir_path=dir_path,
        processor_func=processor_func,
        on_progress=progress_cb,
        on_complete=complete_cb,
        on_error=error_cb,
        extensions=SUPPORTED_EXTENSIONS,
    )
