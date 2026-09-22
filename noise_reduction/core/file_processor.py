"""
core/file_processor.py
Multi-threaded orchestrator for the Noise Reduction tool.

Discovers audio files, dispatches each to a worker thread that applies
hum removal and/or spectral gating, and reports progress via callbacks.

Concurrency model
-----------------
A thread pool with ``DEFAULT_MAX_WORKERS`` threads, managed via
``BaseFileProcessor.process_batch``.  The same constant is imported by
``app.py`` to size its slot-display pool.

Counter semantics
-----------------
  processed : every file attempted (succeeded + skipped + errors)
  succeeded : files where noise reduction was applied (live) or detected (dry run)
  skipped   : files that were already clean
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

from .models import NoiseReductionParams
from .noise_reducer import reduce_noise

logger = logging.getLogger(__name__)


def process_single_file(
    name: str,
    dir_path: str,
    params: NoiseReductionParams,
    temp_dir: str,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    lock: threading.Lock,
    on_progress: Callable[..., None],
) -> None:
    """Process a single audio file in a worker thread.

    Parameters
    ----------
    name : str
        Filename (basename only).
    dir_path : str
        Absolute path to the directory containing *name*.
    params : NoiseReductionParams
        Processing parameters for this run.
    temp_dir : str
        Shared temporary directory.
    slot_vars : list[Any]
        Per-worker status label variables.
    slot_queue : Queue[int]
        Pool of available slot indices.
    lock : threading.Lock
        Serialises writes to shared counters and callbacks.
    on_progress : Callable[..., None]
        Inner progress callback ``(status, display_text, log_text)``.
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

        slot_vars[slot_idx].set(f"Reducing noise: {name[:25]}...")
        audio = AudioSegment.from_file(temp_input)
        result = reduce_noise(audio, params)

        if not result.was_modified:
            status = "SKIP"
            action = "Clean — no noise detected"
        else:
            attenuation = result.energy_before_db - result.energy_after_db
            action = f"Attenuated {attenuation:.1f} dB"
            status = "FOUND"
            if not params.dry_run:
                slot_vars[slot_idx].set(f"Exporting: {name[:25]}...")
                fmt, params_export = get_export_args(ext)
                result.audio.export(temp_output, format=fmt, parameters=params_export)

                slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
                write_tags_raw(temp_output, original_tags, record_snapshot=False)
                record_tag_edit_snapshot(full_path, "noise_reduce_edit")
                shutil.copy2(temp_output, full_path)
                action += " — Reduced"
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


@handle_audio_errors(reraise=False, context="noise_reduction_run")
def run_noise_reduction(
    dir_path: str,
    params: NoiseReductionParams,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """Discover audio files in *dir_path* and process them in parallel.

    Parameters
    ----------
    dir_path : str
        Absolute path to the directory of audio files.
    params : NoiseReductionParams
        Processing parameters.
    slot_vars : list[Any]
        Per-worker status label variables.
    slot_queue : Queue[int]
        Pool of available slot indices.
    on_progress : Callable[..., None]
        Per-file progress callback.
    on_complete : Callable[..., None]
        Completion callback.
    on_error : Callable[[str], None]
        Fatal-error callback.
    """
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
        processed[0] += 1
        if status == "ERROR":
            errors[0] += 1
        elif status == "SKIP":
            skipped[0] += 1
        else:
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

    start = time.monotonic()
    temp_dir = tempfile.mkdtemp()

    processor = BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="noise_reduction"
    )

    def _worker(name: str) -> None:
        _join_undo_batch(
            name,
            dir_path,
            params,
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
