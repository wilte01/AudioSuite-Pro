"""
file_processor.py - Migrated to use BaseFileProcessor for audio normalization.

This file eliminates ~150 lines of duplicated threading and error handling code
by using shared BaseFileProcessor infrastructure while preserving
identical functionality.

Changed in 2.1.7: ``true_peak`` and ``lra`` reach every loudnorm call, and the
peak the re-encode actually achieved is reported in the display and log line
instead of only the requested ceiling.
"""

import logging
import os
import threading
from queue import Queue
from typing import Any, Callable

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.lossless_gain import apply_track_gain, is_mp3_file

from .loudness import measure
from .normalizer import apply as apply_normalisation

logger = logging.getLogger(__name__)

# Locate suite root and add error recovery


class AudioNormalizerProcessor(BaseFileProcessor):
    """
    Audio normalizer using shared BaseFileProcessor infrastructure.

    Eliminates ~150 lines of duplicated threading and error handling code
    while maintaining identical functionality.
    """

    def __init__(self) -> None:
        super().__init__(operation_type="audio_normalization")


def process_single_file(
    name: str,
    dir_path: str,
    target_lufs: float,
    tolerance: float,
    is_dry_run: bool,
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    normalization_mode: str = "normalise",
    true_peak: float = -1.5,
    lra: float = 11,
    **kwargs: Any,
) -> None:
    """
    Process a single audio file for normalization using shared infrastructure.

    ``true_peak`` and ``lra`` are the loudnorm delivery targets; they default to
    the values the tool hard-coded before 2.1.7, so an unset driver argv keeps
    the shipped behaviour.
    """
    slot_vars: list[Any] | None = kwargs.get("slot_vars")

    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Analyzing: {name[:20]}...")

    file_path = os.path.normpath(os.path.join(dir_path, name))
    loudness_data = measure(file_path, target_lufs, true_peak, lra)

    if not loudness_data:
        raise AudioAnalysisError(
            "Could not detect loudness for file",
            context={"file": name},
        )

    current_lufs = loudness_data["input_i"]
    gain_needed = target_lufs - current_lufs

    if abs(gain_needed) <= tolerance:
        display = f"[SKIPPED] {name} ({current_lufs:.1f} LUFS - within tolerance)"
        log = f"[SKIPPED] {name} | {current_lufs:.1f} LUFS - within tolerance\n"
        with lock:
            on_progress(n_skipped=1, display_text=display, log_text=log)
        return

    if is_dry_run:
        display = f"[DRY RUN] {name} → Would apply {gain_needed:.2f} dB gain"
        log = f"[DRY RUN] {name} | Would apply {gain_needed:.2f} dB gain\n"
    else:
        try:
            if slot_vars is not None:
                slot_vars[slot_idx].set(f"Processing: {name[:20]}...")
            achieved_peak = _apply_normalisation(
                file_path,
                target_lufs,
                loudness_data,
                gain_needed,
                normalization_mode,
                true_peak,
                lra,
            )
            display = f"[NORMALIZED] {name} → Applied {gain_needed:.2f} dB gain"
            log = f"[NORMALIZED] {name} | Applied {gain_needed:.2f} dB gain"
            if isinstance(achieved_peak, (int, float)):
                # The achieved peak is the only evidence the requested ceiling
                # was met; it is reported for review, not assumed from argv.
                display += f" (true peak {achieved_peak:+.1f} dBTP)"
                log += f" | true peak {achieved_peak:+.1f} dBTP"
            log += "\n"
        except Exception as exc:
            mapped = map_to_audio_error(
                exc, context={"file": name, "operation": "normalise"}
            )
            logger.error(
                "[%s] Normalisation failed for %s: %s",
                type(mapped).__name__,
                name,
                mapped,
                exc_info=True,
            )
            clean = user_message_for(mapped)
            with lock:
                on_progress(
                    n_errors=1,
                    display_text=f"[ERROR] {name}: {clean}",
                    log_text=f"[ERROR] {name}: {clean}\n",
                )
            return

    with lock:
        on_progress(display_text=display, log_text=log)


def _apply_normalisation(
    file_path: str,
    target_lufs: float,
    loudness_data: dict[str, Any],
    gain_needed: float,
    normalization_mode: str,
    true_peak: float = -1.5,
    lra: float = 11,
) -> float | None:
    """Apply the gain to a single file using the selected strategy.

    In *lossless* mode, MP3 files have their ``global_gain`` adjusted
    in-place (no re-encode).  Everything else — including non-MP3 files in
    lossless mode — falls back to the FFmpeg loudnorm re-encode.

    Args:
        file_path: Absolute path to the audio file.
        target_lufs: Target integrated loudness.
        loudness_data: Measurements from loudness.measure().
        gain_needed: Target minus current loudness (dB).
        normalization_mode: ``"lossless"`` or ``"normalise"``.
        true_peak: True-peak ceiling in dBTP for the loudnorm re-encode.
        lra: Target loudness range in LU for the loudnorm re-encode.

    Returns:
        The true peak the encode achieved in dBTP, or ``None`` for the
        lossless MP3 path (which re-encodes nothing) or when FFmpeg did not
        report one.
    """
    if normalization_mode == "lossless" and is_mp3_file(file_path):
        apply_track_gain(file_path, gain_needed)
        return None
    return apply_normalisation(
        file_path, target_lufs, loudness_data, true_peak=true_peak, lra=lra
    )


@handle_audio_errors(reraise=False, context="normalizer_run_parallel")
def run_parallel_process(
    dir_path: str,
    target_lufs: float,
    tolerance: float,
    is_dry_run: bool,
    slot_vars: list[Any] | None,
    slot_queue: Queue[Any],
    on_progress: Callable[..., Any],
    on_complete: Callable[..., Any],  # on_complete(total, processed, skipped, errors,
    #                                       duration_secs, log_entries)
    on_error: Callable[..., Any],  # on_error(message: str)
    normalization_mode: str = "normalise",
    true_peak: float = -1.5,
    lra: float = 11,
) -> None:
    """
    Run parallel audio normalization using shared infrastructure.

    This function maintains the same interface as the original but delegates
    to BaseFileProcessor for all common functionality.
    """
    processor = AudioNormalizerProcessor()

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    # Create wrapper function that matches BaseFileProcessor expectations
    def processor_func(
        filename: str,
        dir_path: str,
        slot_idx: int,
        lock: threading.Lock,
        on_progress: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        with use_batch(undo_batch):
            process_single_file(
                name=filename,
                dir_path=dir_path,
                target_lufs=target_lufs,
                tolerance=tolerance,
                is_dry_run=is_dry_run,
                slot_idx=slot_idx,
                lock=lock,
                on_progress=on_progress,
                slot_vars=slot_vars,
                normalization_mode=normalization_mode,
                true_peak=true_peak,
                lra=lra,
                **kwargs,
            )

    # Use shared infrastructure - eliminates ~150 lines of duplicated code
    processor.run_parallel_processing(
        dir_path=dir_path,
        processor_func=processor_func,
        on_progress=on_progress,
        on_complete=on_complete,
        on_error=on_error,
        extensions=SUPPORTED_EXTENSIONS,
    )
