"""
core/file_processor.py
Multi-threaded pipeline orchestrator for Audio Refinery.

Discovers audio files, checks the completion registry, dispatches
workers, and aggregates results.  All UI interaction is via injected
callbacks so this module has no tkinter dependency.

Changed in 1.1.0: read-only formats (APE/MPC/DSF) are skipped with a clear message
instead of being rewritten in place.

Changed in 2.3.1 (U-02): a worker records completion only for a run that
actually wrote the file, so a Dry Run or a no-op cannot mask a later run with
different settings.

Changed in 2.5.0: album mode measures the folder once, before any worker
starts, and hands the same plan to every worker (F-E1).  A failed album
measurement stops the run before a single file is touched.

Changed in 2.5.0: an exact copy-mode trim is refused at the run level when
another stage has to decode the audio (F-E3), so the run stops with the reason
instead of every file failing one by one.

Changed in 2.6.0: a peak target plans no album gain (F-E2), so the folder is
never measured as one album for a mode that is per-file by definition.
"""

from __future__ import annotations

import functools
import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any

from audio_normalizer.core.album import AlbumPlan, build_album_plan
from audio_suite_shared.audio_formats import READ_ONLY_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    AudioConfigurationError,
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.resource_manager import cleanup_expired_resources
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

from .models import FileResult, FileStatus, StageConfig
from .pipeline import process_file
from .registry import CompletionRegistry
from .trim import check_copy_mode

logger = logging.getLogger(__name__)


class AudioRefineryProcessor(BaseFileProcessor):
    """Audio Refinery file processor built on BaseFileProcessor."""

    def __init__(self) -> None:
        super().__init__(operation_type="audio_refinery")


def _worker_process(
    path: Path,
    source_dir: Path,
    output_dir: Path,
    config: StageConfig,
    registry: CompletionRegistry,
    slot_queue: Queue[Any],
    slot_vars: list[Any],
    lock: threading.Lock,
    on_file_done: Callable[..., Any],
    processor: AudioRefineryProcessor,
    undo_batch: str | None,
    album_plan: AlbumPlan | None = None,
) -> None:
    """Process a single audio file with retry and slot management."""
    slot_idx = slot_queue.get()
    safe_name = path.name.replace(" ", "_").replace("-", "_")

    def _process_one() -> None:
        with use_batch(undo_batch):
            ext = path.suffix.lower()
            if ext in READ_ONLY_EXTENSIONS:
                result = FileResult(
                    path=path,
                    status=FileStatus.SKIPPED,
                    error=(
                        f"read-only format ({ext}); no encoder exists - "
                        "convert from it instead"
                    ),
                )
                with lock:
                    on_file_done(result)
                return

            slot_vars[slot_idx].set(f"Hashing: {path.name[:22]}...")

            source_hash = registry.hash_file(path)
            if registry.is_done(path, source_hash):
                result = FileResult(path=path, status=FileStatus.SKIPPED)
                with lock:
                    on_file_done(result)
                return

            out_path = path if output_dir == source_dir else output_dir / path.name

            def _progress(stage: str, msg: str) -> None:
                slot_vars[slot_idx].set(f"{stage}: {path.name[:20]}...")

            slot_vars[slot_idx].set(f"Processing: {path.name[:18]}...")
            result = process_file(
                source_path=path,
                output_path=out_path,
                config=config,
                on_progress=_progress,
                album_plan=album_plan,
            )

            # Only a run that actually wrote the file is progress.  A Dry Run
            # is DONE by design and a no-op is SKIPPED, but recording either
            # would mask a later run with different settings (U-02).
            if result.status == FileStatus.DONE and result.was_modified:
                completion_hash = (
                    registry.hash_file(out_path)
                    if output_dir == source_dir
                    else source_hash
                )
                registry.mark_done(path, completion_hash)

            with lock:
                on_file_done(result)

    try:
        processor.run_with_retry(_process_one, label=f"refinery_{safe_name}")
    except Exception as exc:
        mapped = map_to_audio_error(exc, context={"file": str(path)})
        logger.error(
            "[%s] Worker error on %s: %s",
            type(mapped).__name__,
            path.name,
            mapped,
            exc_info=True,
        )
        action = get_recovery_action(mapped.original or mapped, "audio_refinery")
        clean_msg = user_message_for(mapped)
        if action == RecoveryAction.SKIP:
            result = FileResult(path=path, status=FileStatus.SKIPPED, error=clean_msg)
        else:
            result = FileResult(path=path, status=FileStatus.ERROR, error=clean_msg)
        with lock:
            on_file_done(result)
    finally:
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


@handle_audio_errors(reraise=False, context="refinery_run_pipeline")
def run_pipeline(
    source_dir: Path,
    output_dir: Path,
    config: StageConfig,
    registry: CompletionRegistry,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., Any],
    on_complete: Callable[..., Any],
    on_error: Callable[..., Any],
) -> None:
    """
    Discover audio files and process them through the pipeline.

    Callbacks (all called from worker threads; marshal to Tk via root.after)
    -------------------------------------------------------------------------
    on_progress(processed, total, succeeded, skipped, errors, display_text, log_text)
    on_complete(total, processed, succeeded, skipped,
                errors, duration_secs, log_entries)
    on_error(message)
    """
    processor = AudioRefineryProcessor()

    try:
        file_names = processor.discover_audio_files(
            str(source_dir), SUPPORTED_EXTENSIONS
        )
    except AudioSuiteError as exc:
        logger.error("Directory scan failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return

    if not file_names:
        on_error("No supported audio files found in the selected directory.")
        logger.warning("File discovery found 0 files in %s", source_dir)
        return

    files = [source_dir / name for name in file_names]

    # A stream-copy trim cannot share a run with a stage that decodes the
    # audio; refusing here stops the run before the first file is touched.
    try:
        check_copy_mode(config)
    except AudioConfigurationError as exc:
        logger.error("Copy mode refused for this run: %s", exc.message)
        on_error(exc.message)
        return

    # Album mode measures the folder once, before any worker starts: album
    # loudness is the combined signal's, so a per-worker measurement would cost
    # N concatenated decodes and produce N disagreeing answers (F-E1).
    album_plan: AlbumPlan | None = None
    # A peak target is per file (F-E2): album mode is one gain measured across
    # the whole folder, so the two cannot describe one run.  The CLI refuses
    # the pair; this guard stops a stale saved preset from measuring the folder
    # for a run that will never use the plan.
    if (
        config.normalise
        and config.normalise_params.album_mode
        and config.normalise_params.target_mode == "lufs"
    ):
        try:
            album_plan = build_album_plan(
                [str(path) for path in files],
                target_lufs=config.normalise_params.target_lufs,
                true_peak_ceiling=config.normalise_params.true_peak,
                tolerance=config.normalise_params.tolerance,
            )
        except AudioSuiteError as exc:
            logger.error("Album measurement failed: %s", exc, exc_info=True)
            on_error(user_message_for(exc))
            return
        logger.info(
            "Album plan: %.1f LUFS across %d track(s), %d limited",
            album_plan.album_lufs,
            len(files),
            sum(1 for value in album_plan.limited.values() if value),
        )

    lock = threading.Lock()
    processed = [0]
    succeeded = [0]
    skipped = [0]
    errors = [0]
    log_entries: list[str] = []

    def _on_file_done(result: FileResult) -> None:
        processed[0] += 1
        if result.status == FileStatus.SKIPPED:
            skipped[0] += 1
            reason = result.error or "Already in completion registry"
            # The reason is shown verbatim: lowercasing the whole sentence
            # turned every format name and acronym in it into "mp3", "flac"
            # and "normalise stage" in the progress line while the run report
            # kept the original text.
            display = f"[SKIP] {result.path.name} -- {reason}"
            log = f"[SKIP] {result.path.name} | {reason}\n"
        elif result.status == FileStatus.ERROR:
            errors[0] += 1
            error_msg = result.error[:80] if result.error else "Unknown error"
            display = f"[ERROR] {result.path.name}: {error_msg}"
            log = f"[ERROR] {result.path.name} | {result.error}\n"
        else:
            succeeded[0] += 1
            log_lines = [f"[DONE] {result.path.name}\n"]
            for stage in result.stages:
                log_lines.append(f"    [{stage.stage}] {stage.message}\n")
            log = "".join(log_lines)
            display = f"[DONE] {result.path.name}"

        log_entries.append(log)
        on_progress(
            processed=processed[0],
            total=len(files),
            succeeded=succeeded[0],
            skipped=skipped[0],
            errors=errors[0],
            display_text=display,
            log_text=log,
        )

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    worker = functools.partial(
        _worker_process,
        source_dir=source_dir,
        output_dir=output_dir,
        config=config,
        registry=registry,
        slot_queue=slot_queue,
        slot_vars=slot_vars,
        lock=lock,
        on_file_done=_on_file_done,
        processor=processor,
        undo_batch=undo_batch,
        album_plan=album_plan,
    )

    start = time.monotonic()

    logger.info("Starting pipeline with %d files", len(files))
    processor.process_batch(files, worker)
    logger.info("All files processed, calling on_complete")

    on_complete(
        total=len(files),
        processed=succeeded[0] + skipped[0] + errors[0],
        succeeded=succeeded[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.monotonic() - start,
        log_entries=log_entries,
    )

    cleanup_expired_resources(max_age_hours=1)
