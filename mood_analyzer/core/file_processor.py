"""
file_processor.py
Per-file processing worker and ThreadPoolExecutor orchestration
for Mood Analyzer.

All UI interaction via injected callbacks — no tkinter imports.

Per the V1 decision, every supported audio file is analysed in full;
only undecodable / near-silent files are skipped.

Supports: MP3, FLAC, OGG, M4A, Opus

Changed in 1.4.0: the worker count resolves from ``default_max_workers()``
when not supplied (PLAN D56).
Changed in 1.4.0: a failed file reports the reason in plain language and logs
one line; the stack trace goes to the DEBUG log instead of the console.
"""

import logging
import os
import threading
from collections.abc import Callable
from functools import partial
from queue import Queue
from typing import Any

from audio_suite_shared.analysis_loader import load_analysis_audio
from audio_suite_shared.constants import default_max_workers
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    AudioCodecError,
    AudioFormatError,
    failure_reason,
    handle_audio_errors,
    log_handled_failure,
    map_to_audio_error,
)
from audio_suite_shared.file_processor_base import (
    BaseFileProcessor,
    run_analysis_workflow,
)
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    write_energy,
    write_mood,
    write_mood_confidence,
)

from .signal_mood_engine import MoodAnalysis, analyze_mood

logger = logging.getLogger(__name__)

# ── Type aliases ──────────────────────────────────────────────────────────────

# Signature of the internal progress callback accepted by process_single_file.
# Called under lock; all parameters are keyword-only.
_ProgressCallback = Callable[..., None]

# Signature of the public on_progress callback accepted by run_analysis.
# Called with: processed, total, skipped, errors, display_text.
_PublicProgressCallback = Callable[[int, int, int, int, str], None]

# Signature of the on_complete callback accepted by run_analysis.
_CompleteCallback = Callable[..., None]

# Signature of the on_error callback accepted by run_analysis.
_ErrorCallback = Callable[[str], None]

# Analysis failures that indicate a file simply cannot be analysed with
# signal analysis — these are counted as SKIPs, not errors.
_SKIPPABLE_ANALYSIS_ERRORS = (
    AudioCodecError,
    AudioFormatError,
    AudioAnalysisError,
)


class MoodAnalyzerProcessor(BaseFileProcessor):
    """Mood analysis file processor using BaseFileProcessor infrastructure."""

    def __init__(
        self, max_workers: int | None = None, parallel_mode: bool = False
    ) -> None:
        super().__init__(
            operation_type="mood_analysis",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


def _analyse_file(file_path: str, analysis_duration: int) -> MoodAnalysis:
    """Load and analyse a single audio file, returning its mood.

    Raises:
        AudioCodecError: if the file cannot be decoded.
        AudioAnalysisError: if the audio is too short or near-silent.
    """
    y, sr = load_analysis_audio(file_path, max_duration=analysis_duration)
    return analyze_mood(y, int(sr))


def process_single_file(
    processor: MoodAnalyzerProcessor,
    name: str,
    dir_path: str,
    is_dry_run: bool,
    analysis_duration: int,
    slot_vars: list[Any],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: _ProgressCallback,
) -> None:
    """Process a single audio file: detect mood, optionally write tags.

    Args:
        processor:         MoodAnalyzerProcessor instance for retry utilities.
        name:              Filename (not full path).
        dir_path:          Directory containing the file.
        is_dry_run:        When True, analyse but do not write tags.
        analysis_duration: Maximum seconds of audio to load for analysis.
        slot_vars:         Shared list of UI status StringVars (one per worker).
        slot_idx:          Assigned worker slot index.
        lock:              Mutex guarding *on_progress* calls.
        on_progress:       Callback invoked (under lock) after each file outcome.
    """
    file_path = os.path.join(dir_path, name)
    safe_name = name.replace(" ", "_").replace("-", "_")

    def _process_file() -> None:
        slot_vars[slot_idx].set(f"Analyzing: {name[:25]}...")
        analysis = _analyse_file(file_path, analysis_duration)

        status = "DETECTED"
        if not is_dry_run:
            slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
            write_mood(file_path, analysis.to_tag_string())
            write_mood_confidence(file_path, f"{analysis.confidence:.2f}")
            write_energy(file_path, str(analysis.energy))
            status = "TAGGED"

        display = (
            f"[{status}] {name} \u2192 {analysis.to_tag_string()} "
            f"(conf {analysis.confidence:.2f})"
        )
        log = (
            f"[{status}] {name} | Mood: {analysis.to_tag_string()} "
            f"| Confidence: {analysis.confidence:.2f} | Energy: {analysis.energy}\n"
        )

        with lock:
            on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)

    try:
        processor.run_with_retry(_process_file, label=f"mood_{safe_name}")

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        reason = failure_reason(mapped)
        log_handled_failure(logger, "[%s] %s", type(mapped).__name__, reason, exc=exc)
        action = get_recovery_action(exc, "mood_analysis")

        if action == RecoveryAction.SKIP or isinstance(
            mapped, _SKIPPABLE_ANALYSIS_ERRORS
        ):
            display = f"[SKIP] {safe_name}: {reason}"
            with lock:
                on_progress(
                    n_skipped=1,
                    display_text=display,
                    log_text=f"[SKIP] {safe_name}: {reason}\n",
                )
        else:
            display = f"[ERROR] {safe_name}: {reason}"
            with lock:
                on_progress(
                    n_errors=1,
                    display_text=display,
                    log_text=f"[ERROR] {safe_name}: {reason}\n",
                )


def _analyze_mood_cpu(
    file_path: str,
    analysis_duration: int,
    **kwargs: object,
) -> dict[str, object]:
    """Top-level CPU worker for mood analysis (picklable for ProcessPoolExecutor).

    Runs librosa.load + analyze_mood in a separate process.  No callback, lock,
    or UI references.

    Returns:
        ``{"status": "ok", "mood": <str>, "confidence": <float>,
        "energy": <int>}`` on success, or
        ``{"status": "error", "error": <str>}`` on failure.
    """
    try:
        analysis = _analyse_file(file_path, analysis_duration)
        return {
            "status": "ok",
            "mood": analysis.to_tag_string(),
            "confidence": float(analysis.confidence),
            "energy": int(analysis.energy),
        }
    except Exception as exc:
        reason = failure_reason(exc)
        log_handled_failure(
            logger,
            "[Unexpected] _analyze_mood_cpu failed for '%s': %s",
            file_path,
            reason,
            exc=exc,
        )
        return {"status": "error", "error": reason}


def _handle_mood_result(
    filename: str,
    dir_path: str,
    result: dict[str, object],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """Main-thread handler for mood CPU results.  Reads/writes tags and
    reports progress."""
    is_dry_run = kwargs.get("is_dry_run", False)
    slot_vars: list[Any] = kwargs.get("slot_vars", [])
    file_path = os.path.join(dir_path, filename)

    if result.get("status") == "error":
        display = f"[ERROR] {filename}: {result.get('error', 'unknown error')}"
        log = f"[ERROR] {filename}: mood analysis failed — {result.get('error')}\n"
        with lock:
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    mood: str = result["mood"]  # type: ignore[assignment]
    confidence: float = result["confidence"]  # type: ignore[assignment]
    raw_energy = result.get("energy", 0)
    energy: int = int(raw_energy) if isinstance(raw_energy, (int, str)) else 0

    status = "DETECTED"
    if not is_dry_run:
        slot_vars[slot_idx].set(f"Tagging: {filename[:25]}...")
        write_mood(file_path, mood)
        write_mood_confidence(file_path, f"{confidence:.2f}")
        write_energy(file_path, str(energy))
        status = "TAGGED"

    display = f"[{status}] {filename} → {mood} (conf {confidence:.2f})"
    log = (
        f"[{status}] {filename} | Mood: {mood} | Confidence: {confidence:.2f} "
        f"| Energy: {energy}\n"
    )

    with lock:
        on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)


@handle_audio_errors(reraise=False, context="mood_analyzer_run_analysis")
def run_analysis(
    dir_path: str,
    is_dry_run: bool,
    analysis_duration: int,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: _PublicProgressCallback,
    on_complete: _CompleteCallback,
    on_error: _ErrorCallback,
    parallel_mode: bool = False,
    max_workers: int | None = None,
) -> None:
    """Scan directory, analyse all supported audio files with a worker thread
    pool, then call *on_complete* with the summary.

    When *parallel_mode* is True, uses ``ProcessPoolExecutor`` via
    ``run_cpu_bound_processing`` for true multi-process CPU parallelism
    (bypasses the GIL for librosa FFT / CQT).

    Args:
        dir_path:          Path to the directory containing audio files.
        is_dry_run:        When True, analyse only — do not write tags.
        analysis_duration: Maximum seconds of audio to load per file.
        slot_vars:         List of UI status StringVars (one per worker slot).
        slot_queue:        Queue pre-loaded with worker slot indices 0-3.
        on_progress:       Called after each file with
                           (processed, total, skipped, errors, display_text).
        on_complete:       Called once with summary keyword arguments.
        on_error:          Called with a human-readable message on fatal errors.
        parallel_mode:     When True, use ProcessPoolExecutor for CPU-bound
            analysis; when False (default), use ThreadPoolExecutor.
        max_workers:       Number of parallel workers.  Defaults to
            ``default_max_workers()``.
    """
    processor = MoodAnalyzerProcessor(
        max_workers=max_workers or default_max_workers(),
        parallel_mode=parallel_mode,
    )

    run_analysis_workflow(
        processor,
        dir_path,
        slot_vars,
        slot_queue,
        on_progress,
        on_complete,
        on_error,
        extensions=SUPPORTED_EXTENSIONS,
        is_dry_run=is_dry_run,
        analysis_duration=analysis_duration,
        main_thread_label="mood_analyzer_main",
        process_file=partial(process_single_file, processor),
        cpu_worker=_analyze_mood_cpu,
        cpu_result_handler=_handle_mood_result,
        parallel_mode=parallel_mode,
        max_workers=max_workers,
    )
