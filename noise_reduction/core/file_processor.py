"""
core/file_processor.py
Multi-threaded orchestrator for the Noise Reduction tool.

Discovers audio files, dispatches each to a worker thread that applies
hum removal and/or spectral gating, and reports progress via callbacks.

The discover/temp-file/write/undo/cleanup sequence is shared with every other
in-place repair tool through ``BaseFileProcessor.run_inplace_dsp_batch`` and
``BaseFileProcessor.process_audio_file_inplace``; this module supplies only the
noise-specific DSP adapter and its report wording.

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

from .models import NoiseReductionParams
from .noise_reducer import reduce_noise

logger = logging.getLogger(__name__)

#: Progress label shown while the DSP runs.
DSP_LABEL = "Reducing noise"

#: Undo operation recorded for a live write.
TAG_OPERATION = "noise_reduce_edit"


def _build_processor() -> BaseFileProcessor:
    return BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="noise_reduction"
    )


def _make_dsp(
    params: NoiseReductionParams,
) -> Callable[[AudioSegment], InplaceDspResult]:
    """Adapt the noise DSP to the shared in-place workflow.

    Returns the callable the shared workflow invokes with the decoded
    segment.  ``reduce_noise`` returns the untouched input (with
    ``was_modified=False``) in dry-run mode, so a dry run reports the file as
    skipped rather than as "found but not written".
    """

    def _run_dsp(audio: AudioSegment) -> InplaceDspResult:
        result = reduce_noise(audio, params)
        if not result.was_modified:
            return InplaceDspResult(
                audio=result.audio,
                was_modified=False,
                action="Clean — no noise detected",
            )
        attenuation = result.energy_before_db - result.energy_after_db
        return InplaceDspResult(
            audio=result.audio,
            was_modified=True,
            action=f"Attenuated {attenuation:.1f} dB",
            repaired_suffix=" — Reduced",
        )

    return _run_dsp


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

    Thin wiring onto the shared in-place workflow: this tool's DSP, progress
    label, undo operation name and dry-run flag, nothing else.

    Parameters
    ----------
    name : str
        Filename (basename only).
    dir_path : str
        Absolute path to the directory containing *name*.
    params : NoiseReductionParams
        Processing parameters for this run, including ``dry_run``.
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
    _build_processor().process_audio_file_inplace(
        name,
        dir_path,
        temp_dir,
        slot_vars,
        slot_queue,
        lock,
        on_progress,
        run_dsp=_make_dsp(params),
        dsp_label=DSP_LABEL,
        tag_operation=TAG_OPERATION,
        is_dry_run=params.dry_run,
    )


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
    processor = _build_processor()

    def _make_worker(
        temp_dir: str, lock: threading.Lock, report: Callable[..., None]
    ) -> Callable[[str], None]:
        def _worker(name: str) -> None:
            process_single_file(
                name,
                dir_path,
                params,
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
