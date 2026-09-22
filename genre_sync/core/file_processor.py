"""
file_processor.py
Per-file worker and thread-pool orchestration for Genre Sync.

All UI interaction via injected callbacks — no tkinter imports.

Supports: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF
(see audio_suite_shared.audio_formats.SUPPORTED_EXTENSIONS for the
canonical list shared across the suite)
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from queue import Queue
from typing import Any

from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_album_artist,
    read_custom_genre_fields,
    read_genre,
    write_genre_sync_result,
)

from .genre_resolver import resolve_genre

logger = logging.getLogger(__name__)


class GenreSyncProcessor(BaseFileProcessor):
    """Genre Sync file processor using BaseFileProcessor infrastructure."""

    def __init__(self) -> None:
        super().__init__(operation_type="genre_sync")


def process_single_file(
    filename: str,
    dir_path: str,
    is_dry_run: bool,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    lock: threading.Lock,
    on_progress: Callable[..., None],
) -> None:
    """Acquire a slot, apply genre rules to one file, release the slot."""
    slot_idx = slot_queue.get()
    filepath = os.path.normpath(os.path.join(dir_path, filename))
    name = filename if len(filename) <= 50 else filename[:47] + "..."

    try:
        slot_vars[slot_idx].set(f"Processing: {name}")

        fields = read_custom_genre_fields(filepath)
        album_artist = read_album_artist(filepath)
        current_genre = read_genre(filepath)

        resolution = resolve_genre(
            fields["TITLEGENRE"],
            fields["ARTISTGENRE"],
            fields["ALBUMGENRE"],
            fields["ALBUMARTISTGENRE"],
            album_artist,
        )

        n_updated = n_skipped = n_no_genre = 0
        log_updated = log_skipped = log_no_genre = ""
        action = "No genre fields available"
        status = "NO_CHANGE"

        if resolution.status == "no_genre":
            n_no_genre = 1
            log_no_genre = f"{filename} | {action}\n"

        elif current_genre == resolution.selected_genre:
            status = "SKIPPED"
            action = f"Already set: {resolution.selected_genre}"
            n_skipped = 1
            log_skipped = f"{filename} | {action}\n"

        else:
            if is_dry_run:
                status = "DRY_RUN"
                action = (
                    f"Would set: {resolution.selected_genre} "
                    f"({resolution.selection_reason})"
                )
            else:
                # resolve_genre() sets status "resolved" only when it picked a
                # concrete genre and derived marker, so narrow for the writer.
                assert resolution.selected_genre is not None
                assert resolution.derived_value is not None
                write_genre_sync_result(
                    filepath, resolution.selected_genre, resolution.derived_value
                )
                status = "UPDATED"
                action = (
                    f"Set to: {resolution.selected_genre} "
                    f"({resolution.selection_reason})"
                )

            n_updated = 1
            entry = f"{filename} | {action}"
            if current_genre and current_genre != resolution.selected_genre:
                entry += f" | Previous: {current_genre}"
            log_updated = entry + "\n"

        display = f"[{status}] {name} → {action}"
        if (
            current_genre
            and resolution.selected_genre
            and current_genre != resolution.selected_genre
        ):
            display += f" (was: {current_genre})"

        with lock:
            on_progress(
                n_updated=n_updated,
                n_skipped=n_skipped,
                n_no_genre=n_no_genre,
                n_errors=0,
                display_text=display,
                log_updated=log_updated,
                log_skipped=log_skipped,
                log_no_genre=log_no_genre,
                log_errors="",
            )

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        with lock:
            on_progress(
                n_updated=0,
                n_skipped=0,
                n_no_genre=0,
                n_errors=1,
                display_text=f"[ERROR] {name}: {exc}",
                log_updated="",
                log_skipped="",
                log_no_genre="",
                log_errors=f"{filename}: {exc}\n",
            )

    finally:
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


@handle_audio_errors(reraise=False, context="genre_sync_run_processing")
def run_processing(
    dir_path: str,
    is_dry_run: bool,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """Scan directory, process all supported audio files, call on_complete."""
    processor = GenreSyncProcessor()

    try:
        files = processor.discover_audio_files(dir_path, SUPPORTED_EXTENSIONS)
    except AudioSuiteError as exc:
        logger.error("Directory scan failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
        return

    lock = threading.Lock()
    total = len(files)
    updated = [0]
    skipped = [0]
    no_genre = [0]
    errors = [0]
    log_updated_list: list[str] = []
    log_skipped_list: list[str] = []
    log_no_genre_list: list[str] = []
    log_errors_list: list[str] = []

    def _on_progress(
        n_updated: int,
        n_skipped: int,
        n_no_genre: int,
        n_errors: int,
        display_text: str,
        log_updated: str,
        log_skipped: str,
        log_no_genre: str,
        log_errors: str,
        **_: Any,
    ) -> None:
        updated[0] += n_updated
        skipped[0] += n_skipped
        no_genre[0] += n_no_genre
        errors[0] += n_errors
        if log_updated:
            log_updated_list.append(log_updated)
        if log_skipped:
            log_skipped_list.append(log_skipped)
        if log_no_genre:
            log_no_genre_list.append(log_no_genre)
        if log_errors:
            log_errors_list.append(log_errors)
        on_progress(
            processed=updated[0] + skipped[0] + no_genre[0] + errors[0],
            total=total,
            updated=updated[0],
            skipped=skipped[0],
            no_genre=no_genre[0],
            errors=errors[0],
            display_text=display_text,
        )

    def _process_with_retry(name: str) -> None:
        safe_name = name.replace("/", "_").replace("\\", "_")

        def _task() -> None:
            with use_batch(undo_batch):
                process_single_file(
                    name,
                    dir_path,
                    is_dry_run,
                    slot_vars,
                    slot_queue,
                    lock,
                    _on_progress,
                )

        processor.run_with_retry(_task, label=f"genre_sync_{safe_name}")

    def _on_worker_error(message: str) -> None:
        # An exception that escaped every worker layer is not reported by
        # process_single_file(), so count it here to keep the final summary
        # accurate (fed through the same progress counters).
        errors[0] += 1
        _on_progress(
            n_updated=0,
            n_skipped=0,
            n_no_genre=0,
            n_errors=1,
            display_text="[ERROR] " + message,
            log_updated="",
            log_skipped="",
            log_no_genre="",
            log_errors=message + "\n",
        )

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    start = time.time()

    processor.process_batch(
        files,
        _process_with_retry,
        max_workers=processor.max_workers,
        on_error=_on_worker_error,
    )

    processed = updated[0] + skipped[0] + no_genre[0] + errors[0]

    on_complete(
        total=total,
        processed=processed,
        updated=updated[0],
        skipped=skipped[0],
        no_genre=no_genre[0],
        errors=errors[0],
        duration_secs=time.time() - start,
        log_entries=log_updated_list
        + log_skipped_list
        + log_no_genre_list
        + log_errors_list,
        log_updated=log_updated_list,
        log_skipped=log_skipped_list,
        log_no_genre=log_no_genre_list,
        log_errors=log_errors_list,
    )
