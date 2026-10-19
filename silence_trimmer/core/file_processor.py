"""
file_processor.py
Per-file silence-trimming worker and thread-pool orchestration.

Owns the temp-directory lifecycle:
  - A single parent temp dir is created before the pool starts.
  - Each worker creates its own subdirectory under the parent.
  - Each worker cleans up its own subdirectory in a finally block.
  - The parent temp dir is cleaned up by run_trimming() after the pool finishes.

No tkinter imports. All UI interaction via injected callbacks.

Supports: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF, WavPack, Speex.
Read-only formats (APE, MPC, DSF) are skipped with a clear message.

Changed in 1.0.1: an export requires a non-empty trimmed segment, so a
wholly silent source is left untouched rather than replaced with an empty
file.

Changed in 1.1.0: read-only formats (APE/MPC/DSF) are skipped with a clear message
instead of being rewritten in place.

Changed in 1.4.0: the worker count resolves from ``default_max_workers()``
when not supplied (PLAN D56).
"""

# ── Standard library imports ─────────────────────────────────────────────────
import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from queue import Queue
from typing import Any

# ── Third-party imports ──────────────────────────────────────────────────────
from pydub import AudioSegment

# ── First-party imports ──────────────────────────────────────────────────────
from audio_suite_shared.audio_formats import get_export_args, is_read_only_extension
from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_tag_edit_snapshot,
    use_batch,
)
from audio_suite_shared.constants import default_max_workers
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.resource_manager import (
    cleanup_expired_resources,
    get_resource_manager,
    track_thread,
)
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_tags_raw,
    write_tags_raw,
)

# ── Local imports ────────────────────────────────────────────────────────────
from .trimmer import trim_and_fade

logger = logging.getLogger(__name__)


class SilenceTrimmerProcessor(BaseFileProcessor):
    """Silence-trimming file processor built on BaseFileProcessor."""

    def __init__(
        self, max_workers: int | None = None, parallel_mode: bool = False
    ) -> None:
        super().__init__(
            operation_type="silence_trimming",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    threshold: int,
    apply_fade: bool,
    fade_in_ms: int,
    fade_out_ms: int,
    temp_dir: str,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    lock: threading.Lock,
    on_progress: Callable[..., None],
    retry_fn: Callable[..., object] | None = None,
) -> None:
    """Acquire a slot, trim silence from one audio file, release the slot.

    Args:
        name: Filename (not full path) of the audio file to process.
        dir_path: Directory containing the audio file.
        is_dry_run: If True, analyse only — do not modify files.
        threshold: Silence threshold in dBFS.
        apply_fade: Whether to apply fade-in/fade-out after trimming.
        fade_in_ms: Fade-in duration in milliseconds.
        fade_out_ms: Fade-out duration in milliseconds.
        temp_dir: Parent temporary directory for worker subdirectories.
        slot_vars: List of tk.StringVar instances for slot status display.
        slot_queue: Queue of available slot indices.
        lock: Threading lock protecting the on_progress callback.
        on_progress: Callback invoked with (n_skipped, n_errors,
        display_text, log_text).
        retry_fn: Optional callable wrapping a zero-arg function with retry logic.

    Returns:
        None
    """
    slot_idx: int = slot_queue.get()
    full_path: str = os.path.join(dir_path, name)
    ext: str = os.path.splitext(name)[1].lower()

    if is_read_only_extension(name):
        skip_reason = f"read-only format ({ext}); cannot rewrite in place"
        with lock:
            on_progress(
                n_skipped=1,
                n_errors=0,
                display_text=f"[SKIP] {name}: {skip_reason}",
                log_text=f"[SKIP] {name} | {skip_reason}\n",
            )
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)
        return

    worker_temp: str = tempfile.mkdtemp(dir=temp_dir)
    temp_input: str = os.path.join(worker_temp, f"in{ext}")
    temp_output: str = os.path.join(worker_temp, f"out{ext}")

    def _trim_file() -> None:
        slot_vars[slot_idx].set(f"Loading: {name[:25]}...")

        original_tags = read_tags_raw(full_path)
        shutil.copy2(full_path, temp_input)

        slot_vars[slot_idx].set(f"Analyzing: {name[:25]}...")
        audio: AudioSegment = AudioSegment.from_file(temp_input)

        if apply_fade and not is_dry_run:
            slot_vars[slot_idx].set(f"Fading: {name[:25]}...")

        result = trim_and_fade(
            audio=audio,
            threshold=threshold,
            is_dry_run=is_dry_run,
            apply_fade=apply_fade,
            fade_in_ms=fade_in_ms,
            fade_out_ms=fade_out_ms,
        )

        if (
            not is_dry_run
            and result.has_silence
            and result.trimmed is not None
            and len(result.trimmed) > 0
        ):
            slot_vars[slot_idx].set(f"Exporting: {name[:25]}...")
            fmt, params = get_export_args(ext)
            result.trimmed.export(temp_output, format=fmt, parameters=params)

            slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
            write_tags_raw(temp_output, original_tags, record_snapshot=False)
            record_tag_edit_snapshot(full_path, "trim_edit")
            shutil.copy2(temp_output, full_path)

        display: str = f"[{result.status}] {name} \u2192 {result.action}"
        log: str = f"[{result.status}] {name} | {result.action}\n"
        n_skipped: int = 1 if result.status == "SKIP" else 0

        with lock:
            on_progress(
                n_skipped=n_skipped, n_errors=0, display_text=display, log_text=log
            )

    try:
        if retry_fn is not None:
            retry_fn(lambda: _trim_file())
        else:
            _trim_file()

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        action = get_recovery_action(exc, "silence_trimming")

        if action == RecoveryAction.SKIP:
            display = f"[SKIP] {name}: {exc}"
            log = f"[SKIP] {name}: {exc}\n"
            with lock:
                on_progress(n_skipped=1, n_errors=0, display_text=display, log_text=log)
        else:
            display = f"[ERROR] {name}: {str(exc)[:50]}"
            log = f"[ERROR] {name}: {exc}\n"
            with lock:
                on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)

    finally:
        try:
            shutil.rmtree(worker_temp)
        except Exception as cleanup_exc:
            logger.warning("Temp dir cleanup failed: %s", cleanup_exc, exc_info=True)
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


@handle_audio_errors(reraise=False, context="silence_trimmer_run_trimming")
def run_trimming(
    dir_path: str,
    is_dry_run: bool,
    threshold: int,
    apply_fade: bool,
    fade_in_ms: int,
    fade_out_ms: int,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    parallel_mode: bool = False,
    max_workers: int | None = None,
) -> None:
    """Scan directory and process all supported audio files with a worker pool.

    Silence trimming is I/O-bound (ffmpeg subprocess calls) and already
    multi-threaded.  The *parallel_mode* flag is accepted for CLI consistency
    with other tools but does not change the executor type; *max_workers*
    controls the thread-pool size.

    Args:
        dir_path: Directory containing audio files to process.
        is_dry_run: If True, analyse only — do not modify files.
        threshold: Silence threshold in dBFS.
        apply_fade: Whether to apply fade-in/fade-out after trimming.
        fade_in_ms: Fade-in duration in milliseconds.
        fade_out_ms: Fade-out duration in milliseconds.
        slot_vars: List of tk.StringVar instances for slot status display.
        slot_queue: Queue of available slot indices.
        on_progress: Progress callback invoked per file.
        on_complete: Completion callback invoked after all files are processed.
        on_error: Error callback invoked on unrecoverable failure.
        parallel_mode: Accepted for CLI consistency (silence trimmer is
            already parallelised via threads).
        max_workers: Number of parallel workers.  Defaults to
            ``default_max_workers()``.

    Returns:
        None
    """
    processor = SilenceTrimmerProcessor(
        max_workers=max_workers or default_max_workers(),
        parallel_mode=parallel_mode,
    )
    resource_manager = get_resource_manager()

    undo_batch: str | None = get_active_batch_id()

    def _join_undo_batch(*args: Any, **kwargs: Any) -> None:
        with use_batch(undo_batch):
            process_single_file(*args, **kwargs)

    try:
        files: list[str] = processor.discover_audio_files(
            dir_path, SUPPORTED_EXTENSIONS
        )
    except AudioSuiteError as exc:
        logger.error("File discovery failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return

    if not files:
        on_error("No supported audio files found in selected directory.")
        return

    lock = threading.Lock()
    processed, skipped, errors, log_entries, _on_progress = (
        processor.create_progress_tracker(on_progress, len(files))
    )

    start: float = time.monotonic()

    with resource_manager.temporary_directory(prefix="silence_trimmer_") as temp_dir:
        track_thread(threading.current_thread(), "silence_trimmer_main")

        def _worker(name: str) -> None:
            _join_undo_batch(
                name,
                dir_path,
                is_dry_run,
                threshold,
                apply_fade,
                fade_in_ms,
                fade_out_ms,
                temp_dir,
                slot_vars,
                slot_queue,
                lock,
                _on_progress,
                processor.run_with_retry,
            )

        try:
            processor.process_batch(
                files,
                _worker,
                max_workers=processor.max_workers,
                future_timeout=600.0,
            )

        except Exception as pool_exc:
            mapped = map_to_audio_error(pool_exc)
            logger.error("Pool-level processing error: %s", mapped, exc_info=True)
            on_error(user_message_for(mapped))

    on_complete(
        total=len(files),
        processed=processed[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.monotonic() - start,
        log_entries=log_entries,
    )

    cleanup_expired_resources(max_age_hours=1)
