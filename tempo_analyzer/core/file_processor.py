"""
file_processor.py - Tempo analysis using BaseFileProcessor.

Eliminates ~150 lines of duplicated threading and error handling code
by using shared BaseFileProcessor infrastructure while preserving identical
functionality.
"""

import logging
import os
import threading
from queue import Queue
from typing import Any, Callable

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import (
    TagHandlerFactory,
    read_bpm,
    read_tempo_marking,
    write_tempo_marking,
)

from .tempo_schemes import MarkingList, get_tempo_marking

logger = logging.getLogger(__name__)


def _file_has_any_tags(file_path: str) -> bool:
    """
    Determine whether a file has any tag block at all, independent of BPM.

    Used only to choose the more accurate SKIP message when no BPM is found:
    distinguishes "file has tags but no BPM value" from "file has no tag
    block at all". Uses the existing public ``get_raw_tags()`` accessor on
    ``BaseTagHandler`` — verified empirically across MP3, FLAC, OGG, M4A,
    WAV, and AIFF to return a falsy value (``None`` or an empty tag
    container) if and only if the file has no tag block.

    Args:
        file_path: Full path to the audio file.

    Returns:
        True if the file has any existing tag block, False if it has none
        or if tag presence could not be determined (e.g. unreadable file).
        Defaults to True on error so an undetermined state falls back to
        the more conservative "No BPM tag" message rather than implying
        a file has no tags when that's merely unknown.
    """
    try:
        return bool(TagHandlerFactory.get_handler(file_path).get_raw_tags())
    except Exception as exc:
        logger.debug(
            "Could not determine tag presence for %s: %s", file_path, exc, exc_info=True
        )
        return True


class TempoAnalyzerProcessor(BaseFileProcessor):
    """
    Tempo analyzer using shared BaseFileProcessor infrastructure.

    Eliminates ~150 lines of duplicated threading and error handling code
    while maintaining identical functionality.
    """

    def __init__(self) -> None:
        super().__init__(operation_type="tempo_analysis")


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    markings: MarkingList,
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    slot_vars: list[Any],
) -> None:
    """
    Process a single audio file for tempo marking.

    Args:
        name:        Filename (not full path) of the audio file.
        dir_path:    Directory containing the file.
        is_dry_run:  When True, derive the marking but do not write it.
        markings:    Active scheme's BPM-to-marking mapping.
        slot_idx:    Worker slot index for status display.
        lock:        Shared threading lock guarding on_progress calls.
        on_progress: Callback accepting keyword args n_skipped, n_errors,
                     display_text, log_text.
        slot_vars:   List of tk.StringVar objects for slot status display.

    Returns:
        None
    """
    slot_vars[slot_idx].set(f"Reading: {name[:25]}...")

    file_path = os.path.join(dir_path, name)
    bpm = read_bpm(file_path)

    if not bpm or bpm <= 0:
        if _file_has_any_tags(file_path):
            display = f"[SKIP] {name} (No BPM tag)"
            log = f"[SKIP] {name} | No BPM tag found\n"
        else:
            display = f"[SKIP] {name} (No tags found)"
            log = f"[SKIP] {name} | No tags found\n"
        with lock:
            on_progress(n_skipped=1, n_errors=0, display_text=display, log_text=log)
        return

    marking = get_tempo_marking(bpm, markings)
    status = "DRY RUN"
    action = f"{marking} ({bpm} BPM)"

    if not is_dry_run:
        slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")

        existing_tempo = read_tempo_marking(file_path)
        write_tempo_marking(file_path, marking)
        status = "TAGGED"

        if existing_tempo and existing_tempo != marking:
            action += f" (was {existing_tempo})"

    display = f"[{status}] {name} → {action}"
    log = f"[{status}] {name} | {marking} ({bpm} BPM)\n"

    with lock:
        on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)


@handle_audio_errors(reraise=False, context="tempo_analyzer_run_analysis")
def run_analysis(
    dir_path: str,
    is_dry_run: bool,
    markings: MarkingList,
    scheme_name: str,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """
    Run parallel tempo analysis using shared infrastructure.

    Args:
        dir_path:    Directory to scan for audio files.
        is_dry_run:  When True, analyse only — do not write tags.
        markings:    Active scheme's BPM-to-marking mapping.
        scheme_name: Human-readable name of the active scheme (for logging).
        slot_vars:   List of tk.StringVar objects for slot status display.
        slot_queue:  Queue of available worker slot indices (kept for interface
                     compatibility with BaseFileProcessor).
        on_progress: Callback called after each file is processed.
        on_complete: Callback called when all files are done.
        on_error:    Callback called with an error message string on failure.

    Returns:
        None
    """
    processor = TempoAnalyzerProcessor()

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    def processor_func(
        filename: str,
        dir_path: str,
        slot_idx: int,
        lock: threading.Lock,
        on_progress: Callable[..., None],
        **kwargs: Any,
    ) -> None:
        with use_batch(undo_batch):
            process_single_file(
                name=filename,
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                markings=markings,
                slot_idx=slot_idx,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
            )

    processor.run_parallel_processing(
        dir_path=dir_path,
        processor_func=processor_func,
        on_progress=on_progress,
        on_complete=on_complete,
        on_error=on_error,
        extensions=SUPPORTED_EXTENSIONS,
    )
