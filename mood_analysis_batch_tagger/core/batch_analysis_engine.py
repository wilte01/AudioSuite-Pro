"""
batch_analysis_engine.py
Recursively walks a root directory for supported audio files, analyses the
mood from the audio signal itself, and writes the mood + confidence tags.

The core analysis is delegated to ``mood_analyzer.core.file_processor``
(``_analyse_file`` is imported directly) and ``mood_analyzer.core.signal_mood_engine``
so that any given track produces *identical* mood values whether it is
processed via ``mood_analyzer`` or this batch tool.  The only difference is
directory traversal:  ``mood_analyzer`` scans a single flat directory whereas
this tool walks the whole tree recursively.

Workers post progress via a queue consumed by the UI:
    ("folder",   rel_folder, current, total)           — entering a new folder
    ("progress", current, total, filename)             — per-file progress
    ("result",   filepath, filename, success, detail)  — per-file outcome
    ("slot",     slot_index, label)                    — worker slot busy/IDLE
    ("done",     tagged, skipped, errors, folders, log_path) — batch complete
"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Queue
from typing import Any

from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_tag_edit_snapshot,
    use_batch,
)
from audio_suite_shared.constants import CPU_WORKER_TIMEOUT_SECS
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    AudioCodecError,
    AudioDirectoryError,
    AudioFormatError,
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
    write_energy,
    write_mood,
    write_mood_confidence,
)
from mood_analyzer.core.file_processor import _analyse_file
from mood_analyzer.core.signal_mood_engine import MoodAnalysis

logger = logging.getLogger(__name__)

# Analysis failures that indicate a file simply cannot be analysed with signal
# analysis — these are counted as SKIPs, not errors.
_SKIPPABLE_ANALYSIS_ERRORS = (
    AudioCodecError,
    AudioFormatError,
    AudioAnalysisError,
)


@dataclass(frozen=True)
class BatchResult:
    """Summary of a completed batch run."""

    total: int
    tagged: int
    skipped: int
    errors: int
    folders: int
    log_path: str


class _WorkerSlotTracker:
    """Thread-safe pool of reusable worker slot indices.

    Hands out a bounded set of ``0..count-1`` slot indices so the UI's "Active
    Workers" boxes reflect which workers are currently busy.  A slot is claimed
    while its worker is running and released back to the pool when it finishes.
    """

    def __init__(self, count: int) -> None:
        self._count = max(1, count)
        self._condition = threading.Condition()
        self._available: list[int] = list(range(self._count))

    def acquire(self) -> int:
        """Claim a slot index, blocking until one is free.

        The pool is empty only while every slot is held, and both call sites
        hold at most ``_count`` slots at a time: the thread path through
        ``ThreadPoolExecutor(max_workers=...)`` (one slot per worker thread,
        released before the thread takes its next item), the pool path through
        the ``len(pending) < slots._count`` submit bound (one slot per in-flight
        file).  So a wait here always ends when the holder releases.
        """
        with self._condition:
            while not self._available:
                self._condition.wait()
            return self._available.pop()

    def release(self, slot: int) -> None:
        """Return *slot* to the pool and wake a waiting acquirer."""
        with self._condition:
            self._available.append(slot)
            self._condition.notify()


def _collect_audio_files(root: str) -> list[str]:
    """Recursively walk *root* and collect all supported audio file paths.

    Args:
        root: Absolute path to the root directory to scan recursively.

    Returns:
        List of full paths to every supported audio file found, sorted by
        folder then filename.

    Raises:
        AudioDirectoryError: If *root* does not exist or is not a directory.
    """
    if not os.path.isdir(root):
        raise AudioDirectoryError(
            f"Root path does not exist or is not a directory: {root!r}"
        )
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            if filename.lower().endswith(SUPPORTED_EXTENSIONS):
                results.append(os.path.join(dirpath, filename))
    return results


def _determine_folder_plan(files: list[str]) -> list[tuple[str, int]]:
    """Return ordered ``(rel_folder, count)`` tuples for the UI folder grouping.

    Groups the collected full file paths by parent directory in encounter
    order and returns the relative path and the number of files in each
    folder.
    """
    from collections import OrderedDict

    counts: "OrderedDict[str, int]" = OrderedDict()
    for file_path in files:
        folder = os.path.dirname(file_path)
        counts[folder] = counts.get(folder, 0) + 1
    return list(counts.items())


class _BatchAnalysisProcessor(BaseFileProcessor):
    """Batch mood-analysis processor using BaseFileProcessor infrastructure."""

    def __init__(self, max_workers: int = 4, parallel_mode: bool = False) -> None:
        super().__init__(
            operation_type="mood_analysis_batch",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


def _analyse_audio_cpu(
    file_path: str,
    analysis_duration: int,
    **kwargs: object,
) -> dict[str, object]:
    """Top-level CPU worker for batch mood analysis (picklable for process pool).

    Returns:
        ``{"status": "ok", "mood": <str>, "confidence": <float>,
        "energy": <int>}`` on success, or ``{"status": "error",
        "error": <str>}`` on failure.
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
        logger.error(
            "[Unexpected] _analyse_audio_cpu failed for '%s': %s",
            file_path,
            exc,
            exc_info=True,
        )
        return {"status": "error", "error": str(exc)}


def _write_tags(file_path: str, analysis: MoodAnalysis) -> None:
    """Write mood and confidence tags to a single file with an undo snapshot."""
    record_tag_edit_snapshot(file_path, "write_mood")
    write_mood(file_path, analysis.to_tag_string())
    write_mood_confidence(file_path, f"{analysis.confidence:.2f}")
    write_energy(file_path, str(analysis.energy))


def _write_tags_from_result(file_path: str, result: dict[str, object]) -> None:
    """Write mood and confidence tags from a CPU worker result dict.

    Mirrors ``mood_analyzer``'s process-pool tag-writing path so the written
    values are identical to that tool.
    """
    mood: str = result["mood"]  # type: ignore[assignment]
    confidence: float = result["confidence"]  # type: ignore[assignment]
    energy: int = result["energy"]  # type: ignore[assignment]
    record_tag_edit_snapshot(file_path, "write_mood")
    write_mood(file_path, mood)
    write_mood_confidence(file_path, f"{confidence:.2f}")
    write_energy(file_path, str(energy))


def _slot_label(action: str, filename: str) -> str:
    """Build a worker-slot status string matching ``mood_analyzer``'s format."""
    return f"{action}: {filename[:25]}..."


@handle_audio_errors(reraise=False, context="mood_analysis_batch_process")
def run_batch(
    root: str,
    out_queue: Queue[tuple[Any, ...]],
    stop_event: threading.Event,
    live: bool = True,
    analysis_duration: int = 90,
    parallel_mode: bool = False,
    max_workers: int = 4,
    on_worker_status: Callable[[int, str], None] | None = None,
) -> BatchResult:
    """Recursively analyse mood for all supported audio files under *root*.

    Runs in a background thread.  Walks *root* recursively, analyses each
    supported file with the shared signal mood engine, and writes the mood
    and confidence tags when running in live mode.

    Progress and results are communicated to the UI via *out_queue*:

    ``("folder",   rel_folder, current, total)``   Entering a new folder.
    ``("progress", current, total, filename)``     Per-file progress tick.
    ``("result",   filepath, filename, success, detail)`` Per-file outcome.
    ``("done",     tagged, skipped, errors, folders, log_path)`` Batch done.

    Args:
        root:               Root directory to scan recursively.
        out_queue:          Queue consumed by the UI polling loop.
        stop_event:         Checked between files; set externally to cancel.
        live:               When ``False`` (Dry Run), moods are determined but
            tags are not written to disk.
        analysis_duration:  Maximum seconds of audio to load per file.
        parallel_mode:      When True, use a ProcessPoolExecutor for the
            CPU-bound analysis; otherwise a ThreadPoolExecutor.
        max_workers:        Number of parallel workers.
        on_worker_status:   Optional callback ``(slot_index, label)`` invoked
            when a worker claims or releases a slot.  Used to drive the UI's
            "Active Workers" boxes.

    Returns:
        A :class:`BatchResult` summary of the run.
    """
    get_resource_manager()
    undo_batch: str | None = get_active_batch_id()

    try:
        all_files = _collect_audio_files(root)
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error(
            "Failed to scan root directory %r: %s", root, mapped, exc_info=True
        )
        out_queue.put(("done", 0, 0, 0, 0, ""))
        return BatchResult(0, 0, 0, 0, 0, "")

    total: int = len(all_files)
    if total == 0:
        out_queue.put(("done", 0, 0, 0, 0, ""))
        return BatchResult(0, 0, 0, 0, 0, "")

    mode_label = "DRY RUN" if not live else "LIVE UPDATE"
    log_lines: list[str] = [
        "=" * 70,
        f"  Mood Analysis Batch Tagger Log  -  {mode_label}",
        f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}",
        f"  Root folder: {root}",
        f"  Audio files found: {total}",
        f"  Analysis duration: {analysis_duration}s",
        f"  Parallel: {'Yes' if parallel_mode else 'No'}  Workers: {max_workers}",
        "=" * 70,
    ]

    folder_plan = _determine_folder_plan(all_files)
    folder_count = len(folder_plan)
    for rel_folder, count in folder_plan:
        out_queue.put(("folder", rel_folder, count, folder_count))

    lock = threading.Lock()
    tagged_count: list[int] = [0]
    skipped_count: list[int] = [0]
    error_count: list[int] = [0]
    processed_count: list[int] = [0]

    current_folder: str | None = None

    def _on_file_result(
        filepath: str,
        success: bool,
        detail: str,
        log_text: str,
    ) -> None:
        with lock:
            processed_count[0] += 1
            if success:
                tagged_count[0] += 1
            else:
                skipped_count[0] += 1
            log_lines.extend(log_text if isinstance(log_text, list) else [log_text])
        out_queue.put(
            (
                "result",
                filepath,
                os.path.basename(filepath),
                success,
                detail,
            )
        )
        out_queue.put(
            ("progress", processed_count[0], total, os.path.basename(filepath))
        )

    def _on_error_result(
        filepath: str,
        detail: str,
        log_text: str,
    ) -> None:
        with lock:
            processed_count[0] += 1
            error_count[0] += 1
            log_lines.extend(log_text if isinstance(log_text, list) else [log_text])
        out_queue.put(
            (
                "result",
                filepath,
                os.path.basename(filepath),
                False,
                detail,
            )
        )
        out_queue.put(
            ("progress", processed_count[0], total, os.path.basename(filepath))
        )

    def _log_folder(filepath: str) -> None:
        nonlocal current_folder
        folder = os.path.dirname(filepath)
        if folder != current_folder:
            current_folder = folder
            rel_folder = os.path.relpath(folder, root)
            with lock:
                log_lines.append(f"\n{'-' * 70}")
                log_lines.append(f"  Folder: {rel_folder}")
                log_lines.append(f"{'-' * 70}")

    processor = _BatchAnalysisProcessor(
        max_workers=max_workers,
        parallel_mode=parallel_mode,
    )

    if parallel_mode:
        _run_process_pool(
            processor=processor,
            all_files=all_files,
            root=root,
            stop_event=stop_event,
            live=live,
            analysis_duration=analysis_duration,
            on_file_result=_on_file_result,
            on_error_result=_on_error_result,
            log_folder=_log_folder,
            processed_count=processed_count,
            on_worker_status=on_worker_status,
            undo_batch=undo_batch,
        )
    else:
        _run_thread_pool(
            processor=processor,
            all_files=all_files,
            root=root,
            stop_event=stop_event,
            live=live,
            analysis_duration=analysis_duration,
            on_file_result=_on_file_result,
            on_error_result=_on_error_result,
            log_folder=_log_folder,
            processed_count=processed_count,
            on_worker_status=on_worker_status,
            undo_batch=undo_batch,
        )

    log_lines.append(f"\n{'=' * 70}")
    log_lines.append(f"  Folders scanned: {folder_count}")
    log_lines.append(f"  Files tagged:    {tagged_count[0]}")
    log_lines.append(f"  Files skipped:   {skipped_count[0]}")
    log_lines.append(f"  Errors:          {error_count[0]}")
    log_lines.append(f"{'=' * 70}")

    log_path = os.path.join(root, "mood_analysis_batch_log.txt")
    try:
        with open(log_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(log_lines))
    except OSError as exc:
        logger.warning("Could not write batch analysis log: %s", exc, exc_info=True)
        log_path = ""

    out_queue.put(
        (
            "done",
            tagged_count[0],
            skipped_count[0],
            error_count[0],
            folder_count,
            log_path,
        )
    )
    return BatchResult(
        total=total,
        tagged=tagged_count[0],
        skipped=skipped_count[0],
        errors=error_count[0],
        folders=folder_count,
        log_path=log_path,
    )


def _run_thread_pool(
    processor: _BatchAnalysisProcessor,
    all_files: list[str],
    root: str,
    stop_event: threading.Event,
    live: bool,
    analysis_duration: int,
    on_file_result: Any,
    on_error_result: Any,
    log_folder: Any,
    processed_count: list[int],
    on_worker_status: Callable[[int, str], None] | None = None,
    undo_batch: str | None = None,
) -> None:
    """Process files in the current tree using a ThreadPoolExecutor."""
    main_thread = threading.current_thread()
    track_thread(main_thread, "mood_analysis_batch_main")

    slots = _WorkerSlotTracker(processor.max_workers)

    def _release(slot: int) -> None:
        slots.release(slot)
        if on_worker_status is not None:
            on_worker_status(slot, "IDLE")

    def _worker(filepath: str) -> None:
        if stop_event.is_set():
            return
        filename = os.path.basename(filepath)
        slot = slots.acquire()
        if slot >= 0 and on_worker_status is not None:
            on_worker_status(slot, _slot_label("Analyzing", filename))
        log_folder(filepath)
        safe_name = filename.replace(" ", "_").replace("-", "_")

        def _process_file() -> None:
            analysis = _analyse_file(filepath, analysis_duration)
            if not live:
                detail = f"{analysis.to_tag_string()} (dry run - not written)"
                log_text = (
                    f"  DRY   {filename}\n"
                    f"        Would set TMOO = {analysis.to_tag_string()}\n"
                )
                on_file_result(filepath, True, detail, log_text)
                return
            if slot >= 0 and on_worker_status is not None:
                on_worker_status(slot, _slot_label("Tagging", filename))
            _write_tags(filepath, analysis)
            detail = f"{analysis.to_tag_string()} (conf {analysis.confidence:.2f})"
            log_text = (
                f"  OK    {filename}\n"
                f"        TMOO = {analysis.to_tag_string()}\n"
                f"        Confidence = {analysis.confidence:.2f}\n"
                f"        Energy = {analysis.energy}\n"
            )
            on_file_result(filepath, True, detail, log_text)

        try:
            with use_batch(undo_batch):
                processor.run_with_retry(_process_file, label=f"mood_{safe_name}")
        except Exception as exc:
            mapped = map_to_audio_error(
                exc, context={"file": filename, "operation": "mood_analysis"}
            )
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            action = get_recovery_action(exc, "mood_analysis")
            if action == RecoveryAction.SKIP or isinstance(
                mapped, _SKIPPABLE_ANALYSIS_ERRORS
            ):
                detail = user_message_for(mapped)
                log_text = f"  SKIP  {filename}\n        {detail}\n"
                on_file_result(filepath, False, detail, log_text)
            else:
                detail = user_message_for(mapped)
                log_text = f"  ERROR {filename}\n        {detail}\n"
                on_error_result(filepath, detail, log_text)
        finally:
            if slot >= 0:
                _release(slot)

    processor.process_batch(
        all_files,
        _worker,
        max_workers=processor.max_workers,
        progress_callback=lambda done, n: None,
    )
    cleanup_expired_resources(max_age_hours=1)


def _run_process_pool(
    processor: _BatchAnalysisProcessor,
    all_files: list[str],
    root: str,
    stop_event: threading.Event,
    live: bool,
    analysis_duration: int,
    on_file_result: Any,
    on_error_result: Any,
    log_folder: Any,
    processed_count: list[int],
    on_worker_status: Callable[[int, str], None] | None = None,
    undo_batch: str | None = None,
) -> None:
    """Process files in the current tree using a ProcessPoolExecutor.

    The CPU-heavy analysis runs in worker processes (bypassing the GIL for
    FFT / CQT); tag writes run here in the main thread.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed

    slots = _WorkerSlotTracker(processor.max_workers)
    active_slots: dict[str, int] = {}

    def _handle_result(file_path: str, result: dict[str, object]) -> None:
        slot = active_slots.pop(file_path, -1)
        filename = os.path.basename(file_path)
        log_folder(file_path)
        mood: str = ""
        confidence: float = 0.0
        energy: int = 0
        if result.get("status") == "error":
            detail = str(result.get("error", "unknown error"))
            log_text = f"  ERROR {filename}\n        {detail}\n"
            on_error_result(file_path, detail, log_text)
        else:
            mood = result["mood"]  # type: ignore[assignment]
            confidence = result["confidence"]  # type: ignore[assignment]
            energy = result["energy"]  # type: ignore[assignment]
            if not live:
                detail = f"{mood} (dry run - not written)"
                log_text = f"  DRY   {filename}\n        Would set TMOO = {mood}\n"
                on_file_result(file_path, True, detail, log_text)
            else:
                if slot >= 0 and on_worker_status is not None:
                    on_worker_status(slot, _slot_label("Tagging", filename))
                try:
                    with use_batch(undo_batch):
                        _write_tags_from_result(file_path, result)
                except Exception as exc:
                    mapped = map_to_audio_error(
                        exc, context={"file": filename, "operation": "write_mood"}
                    )
                    logger.error(
                        "[%s] Tag write failed for %s: %s",
                        type(mapped).__name__,
                        filename,
                        mapped,
                        exc_info=True,
                    )
                    detail = user_message_for(mapped)
                    log_text = f"  SKIP  {filename}\n        {detail}\n"
                    on_file_result(file_path, False, detail, log_text)
                else:
                    detail = f"{mood} (conf {confidence:.2f})"
                    log_text = (
                        f"  OK    {filename}\n"
                        f"        TMOO = {mood}\n"
                        f"        Confidence = {confidence:.2f}\n"
                        f"        Energy = {energy}\n"
                    )
                    on_file_result(file_path, True, detail, log_text)
        if slot >= 0:
            slots.release(slot)
            if on_worker_status is not None:
                on_worker_status(slot, "IDLE")

    main_thread = threading.current_thread()
    track_thread(main_thread, "mood_analysis_batch_main")

    with ProcessPoolExecutor(max_workers=processor.max_workers) as executor:
        pending: dict[Any, str] = {}
        pending_list: list[str] = list(all_files)
        index = 0
        while index < len(pending_list) or pending:
            # At least one future is always in flight below: the outer condition
            # admits the iteration only while files remain or futures are still
            # pending, and the inner loop submits whenever files remain, so
            # ``pending`` cannot be empty at the ``as_completed`` call.
            while index < len(pending_list) and len(pending) < slots._count:
                file_path = pending_list[index]
                index += 1
                future = executor.submit(
                    _analyse_audio_cpu, file_path, analysis_duration
                )
                pending[future] = file_path
                if not stop_event.is_set():
                    slot = slots.acquire()
                    active_slots[file_path] = slot
                    if slot >= 0 and on_worker_status is not None:
                        on_worker_status(
                            slot,
                            _slot_label("Analyzing", os.path.basename(file_path)),
                        )
            done_iter = as_completed(list(pending.keys()))
            for future in done_iter:
                file_path = pending.pop(future, "")
                if file_path:
                    if stop_event.is_set():
                        break
                    try:
                        result = future.result(timeout=CPU_WORKER_TIMEOUT_SECS)
                    except Exception as exc:
                        mapped = map_to_audio_error(
                            exc,
                            context={
                                "file": os.path.basename(file_path),
                                "operation": "mood_analysis",
                            },
                        )
                        logger.error(
                            "[%s] CPU worker failed on %s: %s",
                            type(mapped).__name__,
                            os.path.basename(file_path),
                            mapped,
                            exc_info=True,
                        )
                        detail = user_message_for(mapped)
                        log_text = (
                            f"  ERROR {os.path.basename(file_path)}\n        {detail}\n"
                        )
                        on_error_result(file_path, detail, log_text)
                        slot = active_slots.pop(file_path, -1)
                        if slot >= 0:
                            slots.release(slot)
                            if on_worker_status is not None:
                                on_worker_status(slot, "IDLE")
                    else:
                        _handle_result(file_path, result)
                if stop_event.is_set():
                    remaining = {k: v for k, v in pending.items()}
                    for pfile in remaining.values():
                        slot = active_slots.pop(pfile, -1)
                        if slot >= 0:
                            slots.release(slot)
                            if on_worker_status is not None:
                                on_worker_status(slot, "IDLE")
                    for f in list(remaining.keys()):
                        f.cancel()
                    break

    cleanup_expired_resources(max_age_hours=1)
