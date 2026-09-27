"""
file_processor.py
Folder-grouped two-phase ReplayGain orchestration using BaseFileProcessor.

Phase 1 (per file, parallel):  Measure LUFS + peak via FFmpeg with retry.
Phase 2 (per folder, serial):  Calculate album gain, write all tags.

Slot-release is handled exclusively in finally — never manually —
preventing double-put / over-concurrency in the slot queue.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
from typing import Any

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.exceptions import (
    AudioFormatError,
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.lossless_gain import apply_track_gain, is_mp3_file

try:
    from mutagen import MutagenError
    # mutagen is a declared hard dependency (pyproject [project.dependencies]);
    # this fallback exists only to keep the module importable in an incomplete
    # env, so it cannot run in a correctly installed suite (plan D2).
except ImportError:  # pragma: no cover
    MutagenError = Exception  # type: ignore[misc,assignment]

from .ffmpeg_metrics import get_metrics
from .gain_calculator import calculate_album_gain
from .tag_writer import write_replaygain_tags

logger = logging.getLogger(__name__)


# ── Job data carriers (immutable) ──────────────────────────────────────────────


@dataclass(frozen=True)
class _MeasureJob:
    """All context needed to measure one audio file in Phase 1."""

    filename: str
    folder_path: str
    target_lufs: float
    slot_idx: int
    on_slot_update: Callable[[int, str], None] | None
    slot_queue: Queue[Any]
    lock: threading.Lock
    album_lock: threading.Lock
    album_data: dict[str, list[dict[str, Any]]]
    on_progress: Callable[..., None]
    processor: ReplayGainProcessor


@dataclass(frozen=True)
class _WriteJob:
    """All context needed to write album/track tags for one folder in Phase 2."""

    folder_path: str
    files_data: list[Any]
    target_lufs: float
    is_dry_run: bool
    apply_lossless_gain: bool
    on_folder_complete: Callable[..., None]
    lock: threading.Lock
    undo_batch: str | None


# ── Per-file measurement worker ────────────────────────────────────────────────


def _measure_worker(job: _MeasureJob) -> None:
    """Acquire a slot, measure one file's LUFS + peak, store result, release slot."""
    slot_idx = job.slot_queue.get()
    full_path = os.path.join(job.folder_path, job.filename)

    try:
        if job.on_slot_update:
            job.on_slot_update(slot_idx, f"Analyzing: {job.filename[:25]}...")

        def _do_measure() -> tuple[float | None, float]:
            return get_metrics(full_path)

        lufs, peak = job.processor.run_with_retry(
            _do_measure, max_retries=2, label=f"measure {job.filename}"
        )

        if lufs is None:
            with job.lock:
                job.on_progress(n_errors=1, display_text=f"[ERROR] {job.filename}")
            return

        target_gain = job.target_lufs - lufs
        file_data = {
            "name": job.filename,
            "path": full_path,
            "lufs": lufs,
            "peak": peak,
            "track_gain": target_gain,
        }

        with job.album_lock:
            job.album_data.setdefault(job.folder_path, []).append(file_data)

        with job.lock:
            job.on_progress(n_errors=0, display_text="")

    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"file": job.filename})
        logger.error(
            "[%s] ReplayGain analysis failed for %s: %s",
            type(mapped).__name__,
            job.filename,
            mapped,
            exc_info=True,
        )
        with job.lock:
            job.on_progress(
                n_errors=1,
                display_text=f"[ERROR] {job.filename}: {user_message_for(mapped)}",
            )

    finally:
        if job.on_slot_update:
            job.on_slot_update(slot_idx, "IDLE")
        job.slot_queue.put(slot_idx)


# ── Per-folder tag writing worker ──────────────────────────────────────────────


def _write_worker(job: _WriteJob) -> None:
    """Calculate album gain for a folder and optionally write tags.

    Runs inside ``use_batch`` so snapshots taken by the tag writer are
    recorded against the active undo batch opened by the orchestrator.
    """
    if not job.files_data:
        return

    with use_batch(job.undo_batch):
        lufs_values = [f["lufs"] for f in job.files_data]
        peak_values = [f["peak"] for f in job.files_data]

        album_gain, album_peak, album_gain_str, album_peak_str = calculate_album_gain(
            job.target_lufs, lufs_values, peak_values
        )

        log_header = (
            f"\nFOLDER: {job.folder_path}\n"
            f"ALBUM STATS -> Gain: {album_gain_str} | Peak: {album_peak_str}\n"
            + "-" * 65
            + "\n"
        )

        tag_results: list[Any] = []

        for file_data in job.files_data:
            safe_name = os.path.basename(file_data["path"])
            target_gain = file_data["track_gain"]

            try:
                track_gain_str = f"{target_gain:+.2f} dB"
                track_peak_str = f"{file_data['peak']:.6f}"

                if job.is_dry_run:
                    tag_results.append(
                        (file_data, "DRY RUN", track_gain_str, track_peak_str)
                    )
                    continue

                success, msg = write_replaygain_tags(
                    file_data["path"],
                    track_gain_str,
                    track_peak_str,
                    album_gain_str,
                    album_peak_str,
                )

                status = "TAGGED" if success else "ERROR"

                # Optional post-tag application: bake the track gain into
                # MP3 files losslessly (MP3Gain-style) so the file itself
                # reaches the target loudness, not just its tags.
                if (
                    success
                    and job.apply_lossless_gain
                    and is_mp3_file(file_data["path"])
                ):
                    try:
                        # The bake's own undo snapshot dedupes into the
                        # write_replaygain record above (first snapshot per
                        # batch+file wins) — the file is restorable via that
                        # record; no separate lossless_gain_track row appears.
                        apply_track_gain(file_data["path"], target_gain)
                        status = "TAGGED + GAIN APPLIED"
                    except (AudioFormatError, OSError) as exc:
                        status = "ERROR"
                        logger.error(
                            "Lossless gain application failed for %s: %s",
                            safe_name,
                            exc,
                            exc_info=True,
                        )

                tag_results.append((file_data, status, track_gain_str, track_peak_str))

                if not success:
                    logger.error(
                        "ReplayGain tag write failed for %s: %s", safe_name, msg
                    )

            except (MutagenError, OSError, ValueError) as exc:
                logger.error(
                    "ReplayGain tag write failed for %s: %s",
                    safe_name,
                    exc,
                    exc_info=True,
                )
                mapped = map_to_audio_error(exc, context={"file": file_data["path"]})
                tag_results.append((file_data, "ERROR", user_message_for(mapped), ""))

        job.on_folder_complete(
            folder_path=job.folder_path,
            files_data=job.files_data,
            album_gain_str=album_gain_str,
            album_peak_str=album_peak_str,
            tag_results=tag_results,
            log_header=log_header,
        )


# ── Processor class ────────────────────────────────────────────────────────────


class ReplayGainProcessor(BaseFileProcessor):
    """File processor for two-phase ReplayGain analysis and tag writing."""

    def __init__(self) -> None:
        super().__init__(operation_type="replaygain")


# ── Top-level orchestrator ────────────────────────────────────────────────────


@handle_audio_errors(reraise=False, context="replaygain_run_analysis")
def run_analysis(
    dir_path: str,
    target_lufs: float,
    is_dry_run: bool,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., None],
    on_folder_complete: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    on_slot_update: Callable[[int, str], None] | None = None,
    apply_lossless_gain: bool = False,
) -> None:
    """
    Walk the directory tree, process files with a parallel measure phase
    via process_batch, then apply ReplayGain tags folder by folder.

    Args:
        dir_path:           Root directory to scan for audio files.
        target_lufs:        Desired integrated loudness target.
        is_dry_run:         When True, measure only — do not write tags.
        slot_vars:          List of slot objects (kept for backward compatibility).
        slot_queue:         Queue of available worker slot indices (0–3).
        on_file_progress:   Callback(processed, total, errors) after each file.
        on_folder_complete: Callback(**kwargs) after each folder completes.
        on_complete:        Callback(**kwargs) after all folders are done.
        on_error:           Callback(message) on fatal errors.
        on_slot_update:     Optional callback(slot_idx, text) for worker status display.
                            Replaces the old tk.StringVar-based slot_vars pattern.
        apply_lossless_gain: When True (and not a dry run), bake the track
                            gain into MP3 files losslessly after tagging.
    """
    processor = ReplayGainProcessor()

    all_work: list[tuple[str, list[str]]] = []
    try:
        for root, _, _ in os.walk(dir_path):
            files = processor.discover_audio_files(root, SUPPORTED_EXTENSIONS)
            if files:
                all_work.append((root, files))
    except AudioSuiteError as exc:
        logger.error("Directory scan failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    total = sum(len(f) for _, f in all_work)
    if total == 0:
        on_error("No audio files found in the selected directory.")
        return

    lock = threading.Lock()
    album_lock = threading.Lock()
    album_data: dict[str, list[dict[str, Any]]] = {}
    processed = [0]
    errors = [0]

    _slot_update = on_slot_update
    if _slot_update is None and slot_vars:

        def _slot_update(idx: int, text: str) -> None:
            slot_vars[idx].set(text)

    def _on_file_progress(n_errors: int, display_text: str) -> None:
        if n_errors == 0:
            processed[0] += 1
        errors[0] += n_errors
        on_progress(
            processed=processed[0],
            total=total,
            errors=errors[0],
        )

    start = time.time()
    undo_batch = get_active_batch_id()

    # ── Phase 1: Parallel measurement ──
    measure_jobs = [
        _MeasureJob(
            filename=name,
            folder_path=folder_path,
            target_lufs=target_lufs,
            slot_idx=i % processor.max_workers,
            on_slot_update=_slot_update,
            slot_queue=slot_queue,
            lock=lock,
            album_lock=album_lock,
            album_data=album_data,
            on_progress=_on_file_progress,
            processor=processor,
        )
        for folder_path, audio_files in all_work
        for i, name in enumerate(audio_files)
    ]

    processor.process_batch(
        measure_jobs, _measure_worker, max_workers=processor.max_workers
    )

    # ── Phase 2: Per-folder tag writing (serial via single worker) ──
    log_entries: list[str] = []

    def _on_folder_complete(**kwargs: Any) -> None:
        log_entries.append(kwargs["log_header"])
        for file_data, status, tg_str, tp_str in kwargs["tag_results"]:
            entry = (
                f"[{status}] {file_data['name']}\n"
                f"    Track Gain: {tg_str} | Track Peak: {tp_str}\n"
            )
            log_entries.append(entry)
        on_folder_complete(**kwargs)

    write_jobs = [
        _WriteJob(
            folder_path=fp,
            files_data=files_data,
            target_lufs=target_lufs,
            is_dry_run=is_dry_run,
            apply_lossless_gain=apply_lossless_gain,
            on_folder_complete=_on_folder_complete,
            lock=lock,
            undo_batch=undo_batch,
        )
        for fp, files_data in sorted(album_data.items())
    ]

    processor.process_batch(write_jobs, _write_worker, max_workers=1)

    on_complete(
        total=total,
        processed=processed[0],
        skipped=0,
        errors=errors[0],
        duration_secs=time.time() - start,
        log_entries=log_entries,
    )


# Backward-compatible aliases for existing test imports
def process_single_file(
    file_name: str,
    folder_path: str,
    target_lufs: float,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    lock: threading.Lock,
    album_lock: threading.Lock,
    album_data: dict[str, Any],
    on_progress: Callable[..., Any],
    is_dry_run: bool = False,
    slot_idx: int | None = None,
    on_slot_update: Callable[[int, str], None] | None = None,
) -> None:
    """Backward-compatible wrapper — builds _MeasureJob and delegates."""
    processor = ReplayGainProcessor()
    job = _MeasureJob(
        filename=file_name,
        folder_path=folder_path,
        target_lufs=target_lufs,
        slot_idx=slot_idx if slot_idx is not None else slot_queue.qsize(),
        on_slot_update=on_slot_update,
        slot_queue=slot_queue,
        lock=lock,
        album_lock=album_lock,
        album_data=album_data,
        on_progress=on_progress,
        processor=processor,
    )
    _measure_worker(job)


def apply_replaygain_tags(
    folder_path: str,
    files_data: list[Any],
    target_lufs: float,
    is_dry_run: bool,
    on_folder_complete: Callable[..., Any],
    lock: threading.Lock,
    apply_lossless_gain: bool = False,
) -> None:
    """Backward-compatible wrapper — builds _WriteJob and delegates."""
    job = _WriteJob(
        folder_path=folder_path,
        files_data=files_data,
        target_lufs=target_lufs,
        is_dry_run=is_dry_run,
        apply_lossless_gain=apply_lossless_gain,
        on_folder_complete=on_folder_complete,
        lock=lock,
        undo_batch=None,
    )
    _write_worker(job)
