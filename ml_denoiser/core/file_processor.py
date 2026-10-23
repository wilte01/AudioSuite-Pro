"""
core/file_processor.py
Multi-threaded orchestrator for the ML Denoiser.

Discovers audio files, dispatches each to a worker thread that runs RNNoise,
and reports progress through the shared in-place workflow.

The discover/temp-file/write/undo/cleanup sequence is shared with every other
in-place repair tool through ``BaseFileProcessor.run_inplace_dsp_batch`` and
``BaseFileProcessor.process_audio_file_inplace``; this module supplies only the
denoise adapter and its report wording.

A dry run is not free here: the model has to run to measure what it would
change, so a dry run needs the ``ml`` extra exactly as a live run does.  What it
never does is write — the shared workflow suppresses the export, the tag write
and the copy-back when ``is_dry_run`` is set, and this processor threads the
flag through from ``DenoiseParams.dry_run``.

Counter semantics
-----------------
  processed : every file attempted (succeeded + skipped + errors)
  succeeded : files where the level moved (live) or would move (dry run)
  skipped   : files the model left alone
  errors    : files that raised an exception during processing

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from queue import Queue
from typing import Any

from pydub import AudioSegment

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.file_processor_base import (
    BaseFileProcessor,
    InplaceDspResult,
)
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

from .models import DenoiseParams
from .rnnoise_engine import denoise_segment, require_rnnoise

logger = logging.getLogger(__name__)

#: Progress label shown while the model runs.
DSP_LABEL = "Denoising (RNNoise)"

#: Undo operation recorded for a live write.
TAG_OPERATION = "ml_denoise_edit"


def _build_processor() -> BaseFileProcessor:
    return BaseFileProcessor(
        max_workers=DEFAULT_MAX_WORKERS, operation_type="ml_denoise"
    )


def _make_dsp(
    params: DenoiseParams,
) -> Callable[[AudioSegment], InplaceDspResult]:
    """Adapt the denoise pass to the shared in-place workflow.

    ``denoise_segment`` always measures, so a dry run still reports the
    attenuation it found; the shared workflow's ``is_dry_run`` flag is what stops
    the write.  A file whose level did not move is reported clean and is not
    rewritten, which is how a second pass over an already-denoised folder
    becomes a no-op instead of a re-encode.
    """

    def _run_dsp(audio: AudioSegment) -> InplaceDspResult:
        result = denoise_segment(audio, params.amount)
        if not result.was_modified:
            return InplaceDspResult(
                audio=result.audio,
                was_modified=False,
                action=f"Clean — no attenuation ({result.rms_before_db:.1f} dBFS)",
            )
        return InplaceDspResult(
            audio=result.audio,
            was_modified=True,
            action=(
                f"Attenuated {result.attenuation_db():.1f} dB "
                f"({result.rms_before_db:.1f} → {result.rms_after_db:.1f} dBFS)"
            ),
            repaired_suffix=" — Denoised",
        )

    return _run_dsp


def process_single_file(
    name: str,
    dir_path: str,
    params: DenoiseParams,
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
    params : DenoiseParams
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


def run_ml_denoise(
    dir_path: str,
    params: DenoiseParams,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """Discover audio files in *dir_path* and denoise them in parallel.

    Parameters
    ----------
    dir_path : str
        Absolute path to the directory of audio files.
    params : DenoiseParams
        Processing parameters.
    slot_vars : list[Any]
        Per-worker status label variables.
    slot_queue : Queue[int]
        Pool of available slot indices.
    on_progress : Callable[..., None]
        Per-file progress callback.
    on_complete : Callable[..., None]
        Completion callback; the shared workflow publishes ``total``,
        ``processed``, ``succeeded``, ``skipped``, ``errors``,
        ``duration_secs`` and ``log_entries``.
    on_error : Callable[[str], None]
        Fatal-error callback.

    Raises:
        ValueError: The parameters are invalid.
        AudioMissingDependencyError: The ``ml`` extra is not installed.  Raised
            before the batch so a CLI run exits non-zero and says why, and so the
            GUI can report it from ``_validate_start`` instead of after a run
            that produced nothing.  A dry run needs the model too: measuring is
            what it does.
    """
    problems = params.validate()
    if problems:
        raise ValueError(" ".join(problems))
    require_rnnoise()

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
