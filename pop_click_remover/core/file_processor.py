"""
file_processor.py
Orchestrates multi-threaded audio file processing.

The discover/temp-file/write/undo/cleanup sequence is shared with every other
in-place repair tool through ``BaseFileProcessor.run_inplace_dsp_batch`` and
``BaseFileProcessor.process_audio_file_inplace``; this module supplies only the
declicker DSP adapter and its report wording.

Concurrency model
-----------------
A thread pool with DEFAULT_MAX_WORKERS threads, managed via
``BaseFileProcessor.process_batch``.  The same constant is imported by
app.py to size its slot-display pool, so the two are always in sync.

All callbacks from worker threads are fire-and-forget; app.py is
responsible for marshalling them onto the Tkinter main thread via
root.after(0, fn).

Counter semantics
-----------------
  processed : every file attempted (succeeded + skipped + errors)
  succeeded : files where clicks were detected (dry run) or repaired (live)
  skipped   : files that were clean — no defects found
  errors    : files that raised an exception during processing
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from queue import Queue
from typing import Any

from pydub import AudioSegment

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.file_processor_base import (
    BaseFileProcessor,
    InplaceDspResult,
)
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

from .declicker import declick_audio

logger = logging.getLogger(__name__)

#: Progress label shown while the DSP runs.
DSP_LABEL = "De-clicking"

#: Undo operation recorded for a live write.
TAG_OPERATION = "declick_edit"


# ── DSP adapter ───────────────────────────────────────────────────────────────


def _build_processor() -> BaseFileProcessor:
    return BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="pop_click_removal"
    )


def _make_dsp(
    sensitivity: float, max_width: int
) -> Callable[[AudioSegment], InplaceDspResult]:
    """Adapt the declicker DSP to the shared in-place workflow.

    Returns the callable the shared workflow invokes with the decoded segment.
    ``declick_audio`` has no dry-run awareness, so the shared workflow is what
    keeps a dry run from writing the detected defects back to disk.
    """

    def _run_dsp(audio: AudioSegment) -> InplaceDspResult:
        result = declick_audio(audio, threshold=sensitivity, max_width_ms=max_width)
        if not result.was_modified:
            return InplaceDspResult(
                audio=result.audio,
                was_modified=False,
                action="Clean — no defects found",
            )
        return InplaceDspResult(
            audio=result.audio,
            was_modified=True,
            action=f"Found {result.clicks_found} click(s)",
            repaired_suffix=" — Repaired",
        )

    return _run_dsp


# ── Single-file worker ────────────────────────────────────────────────────────


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    sensitivity: float,
    max_width: int,
    temp_dir: str,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    lock: threading.Lock,
    on_progress: Callable[..., None],
) -> None:
    """
    Process a single audio file in a worker thread.

    Thin wiring onto the shared in-place workflow: this tool's DSP, progress
    label, undo operation name and dry-run flag, nothing else.  The source file
    is never opened for writing until the final copy-back, and the slot index
    is always returned to *slot_queue* even on an exception.

    Parameters
    ----------
    name : str
        Filename (basename only) of the audio file to process.
    dir_path : str
        Absolute path to the directory containing *name*.
    is_dry_run : bool
        When ``True``, detect clicks but do not write repaired audio back.
    sensitivity : float
        Click detection threshold passed to :func:`declick_audio`.
    max_width : int
        Maximum defect width in milliseconds passed to :func:`declick_audio`.
    temp_dir : str
        Shared temporary directory; a per-worker sub-directory is created
        inside it and removed in the ``finally`` block.
    slot_vars : list[Any]
        Per-worker status label variables; updated to show current filename.
    slot_queue : Queue[int]
        Pool of available slot indices; blocks until a slot is free.
    lock : threading.Lock
        Serialises writes to shared counters and the *on_progress* call.
    on_progress : Callable[..., None]
        Inner progress callback with signature
        ``(status, display_text, log_text)``.
    """
    _build_processor().process_audio_file_inplace(
        name,
        dir_path,
        temp_dir,
        slot_vars,
        slot_queue,
        lock,
        on_progress,
        run_dsp=_make_dsp(sensitivity, max_width),
        dsp_label=DSP_LABEL,
        tag_operation=TAG_OPERATION,
        is_dry_run=is_dry_run,
    )


# ── Main entry point ──────────────────────────────────────────────────────────


@handle_audio_errors(reraise=False, context="pop_click_run_declicking")
def run_declicking(
    dir_path: str,
    is_dry_run: bool,
    sensitivity: float,
    max_width: int,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """
    Discover audio files in *dir_path* and process them in parallel.

    Callbacks
    ---------
    on_progress(processed, total, succeeded, skipped, errors, display_text)
        Called after each file completes.  Invoked from a worker thread;
        the caller must marshal it onto the Tk main thread via root.after().

    on_complete(total, succeeded, skipped, errors, duration_secs, log_entries)
        Called once from the orchestrating thread after all workers finish.
        Must also be marshalled to the Tk main thread by the caller.

    on_error(message)
        Called for fatal errors that prevent any processing from starting.

    Parameters
    ----------
    dir_path : str
        Absolute path to the directory of audio files to process.
    is_dry_run : bool
        When ``True``, detect clicks but do not write repaired audio back.
    sensitivity : float
        Click detection threshold forwarded to each worker.
    max_width : int
        Maximum defect width in milliseconds forwarded to each worker.
    slot_vars : list[Any]
        Per-worker status label variables managed by the app orchestrator.
    slot_queue : Queue[int]
        Pool of available worker-slot indices.
    on_progress : Callable[..., None]
        Per-file progress callback; keyword signature matches
        ``_on_progress`` in ``app.py``.
    on_complete : Callable[..., None]
        Completion callback; keyword signature matches
        ``_on_complete`` in ``app.py``.
    on_error : Callable[[str], None]
        Fatal-error callback accepting a human-readable message string.
    """
    processor = _build_processor()

    def _make_worker(
        temp_dir: str, lock: threading.Lock, report: Callable[..., None]
    ) -> Callable[[str], None]:
        def _worker(name: str) -> None:
            process_single_file(
                name,
                dir_path,
                is_dry_run,
                sensitivity,
                max_width,
                temp_dir,
                slot_vars,
                slot_queue,
                lock,
                report,
            )

        return _worker

    processor.run_inplace_dsp_batch(
        dir_path,
        make_worker=_make_worker,
        on_progress=on_progress,
        on_complete=on_complete,
        on_error=on_error,
        extensions=SUPPORTED_EXTENSIONS,
    )
