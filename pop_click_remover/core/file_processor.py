"""
file_processor.py
Orchestrates multi-threaded audio file processing.

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
import os
import shutil
import tempfile
import threading
import time
from queue import Queue
from typing import Any, Callable

from pydub import AudioSegment

from audio_suite_shared.audio_formats import get_export_args
from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_tag_edit_snapshot,
    use_batch,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_tags_raw,
    write_tags_raw,
)

from .declicker import declick_audio

logger = logging.getLogger(__name__)


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

    Steps
    -----
    1. Copy the source to a per-worker temp directory (source file is never
       opened for writing until the final atomic shutil.copy2 at the end).
    2. Read and preserve all metadata tags.
    3. Run the declicker.
    4. Live run only: export the repaired audio, re-apply tags, then
       atomically replace the source file.
    5. Report progress via *on_progress* under *lock*.

    Slot-pool bookkeeping is always performed in the finally block so that
    a slot is never leaked on exception.

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
    on_progress : Callable[[str, str, str], None]
        Inner progress callback with signature
        ``(status, display_text, log_text)``.
    """
    slot_idx = slot_queue.get()
    full_path = os.path.join(dir_path, name)
    ext = os.path.splitext(name)[1].lower()

    worker_temp = tempfile.mkdtemp(dir=temp_dir)
    temp_input = os.path.join(worker_temp, f"in{ext}")
    temp_output = os.path.join(worker_temp, f"out{ext}")

    try:
        slot_vars[slot_idx].set(f"Loading: {name[:25]}...")
        original_tags = read_tags_raw(full_path)
        shutil.copy2(full_path, temp_input)

        slot_vars[slot_idx].set(f"De-clicking: {name[:25]}...")
        audio = AudioSegment.from_file(temp_input)
        result = declick_audio(audio, threshold=sensitivity, max_width_ms=max_width)

        if not result.was_modified:
            status = "SKIP"
            action = "Clean — no defects found"
        else:
            action = f"Found {result.clicks_found} click(s)"
            status = "FOUND"  # dry run: detected but not written
            if not is_dry_run:
                slot_vars[slot_idx].set(f"Exporting: {name[:25]}...")
                fmt, params = get_export_args(ext)
                result.audio.export(temp_output, format=fmt, parameters=params)

                slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
                write_tags_raw(temp_output, original_tags, record_snapshot=False)
                record_tag_edit_snapshot(full_path, "declick_edit")
                shutil.copy2(temp_output, full_path)
                action += " — Repaired"
                status = "FIXED"

        display = f"[{status}] {name} → {action}"
        log = f"[{status}] {name} | {action}\n"

        with lock:
            on_progress(status=status, display_text=display, log_text=log)

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        display = f"[ERROR] {name}: {str(exc)[:80]}"
        log = f"[ERROR] {name}: {exc}\n"
        with lock:
            on_progress(status="ERROR", display_text=display, log_text=log)

    finally:
        shutil.rmtree(worker_temp, ignore_errors=True)
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


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
    # ── Discover files ────────────────────────────────────────────────────────
    try:
        files: list[str] = sorted(
            e.name
            for e in os.scandir(dir_path)
            if e.is_file() and e.name.lower().endswith(SUPPORTED_EXTENSIONS)
        )
    except OSError as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
        return

    # ── Shared state (mutable cells, always accessed under lock) ─────────────
    lock = threading.Lock()
    processed = [0]
    succeeded = [0]
    skipped = [0]
    errors = [0]
    log_entries: list[str] = []
    undo_batch: str | None = get_active_batch_id()

    def _join_undo_batch(*args: Any, **kwargs: Any) -> None:
        with use_batch(undo_batch):
            process_single_file(*args, **kwargs)

    def _on_progress(status: str, display_text: str, log_text: str) -> None:
        """Inner callback — called under *lock* from each worker thread."""
        processed[0] += 1
        if status == "ERROR":
            errors[0] += 1
        elif status == "SKIP":
            skipped[0] += 1
        else:  # "FOUND" or "FIXED"
            succeeded[0] += 1
        log_entries.append(log_text)
        on_progress(
            processed=processed[0],
            total=len(files),
            succeeded=succeeded[0],
            skipped=skipped[0],
            errors=errors[0],
            display_text=display_text,
        )

    # ── Process files in parallel ─────────────────────────────────────────────
    start = time.monotonic()
    temp_dir = tempfile.mkdtemp()

    processor = BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="pop_click_removal"
    )

    def _worker(name: str) -> None:
        _join_undo_batch(
            name,
            dir_path,
            is_dry_run,
            sensitivity,
            max_width,
            temp_dir,
            slot_vars,
            slot_queue,
            lock,
            _on_progress,
        )

    try:
        processor.process_batch(files, _worker, max_workers=processor.max_workers)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    on_complete(
        total=len(files),
        processed=succeeded[0] + skipped[0] + errors[0],
        succeeded=succeeded[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.monotonic() - start,
        log_entries=log_entries,
    )
