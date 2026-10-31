"""The declip batch: the shared in-place workflow with the declip DSP plugged in.

The discover/temp-file/write/undo/cleanup sequence is
``BaseFileProcessor.run_inplace_dsp_batch`` and
``process_audio_file_inplace``; this module supplies only the DSP adapter and
its report wording.  That is what gives the tool the suite's guarantees for
free: the source is never opened for writing until the final copy-back, tags are
preserved, a live write records a byte-level undo snapshot, and — the one this
repair depends on — **a file with nothing to repair is skipped and never
rewritten**, so a clean file's bytes are untouched.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
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

from .declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD, declip_segment

logger = logging.getLogger(__name__)

#: Progress label shown while the DSP runs.
DSP_LABEL = "Reconstructing peaks"

#: Undo operation recorded for a live write.
TAG_OPERATION = "declip_edit"


class _HeadlessSlot:
    """Stand-in for a worker-slot label when no window is drawing one.

    The in-place workflow writes progress into a per-worker ``StringVar``; a
    CLI or programmatic run has no widget to write, and the workflow only needs
    an object with ``set``/``get``.
    """

    def set(self, value: str) -> None:
        """Discard the label.

        Args:
            value: The label the workflow would have shown.
        """
        del value

    def get(self) -> str:
        """Return an empty label.

        Returns:
            The empty string.
        """
        return ""


def _build_processor() -> BaseFileProcessor:
    return BaseFileProcessor(max_workers=DEFAULT_MAX_WORKERS, operation_type="declip")


def _resolve_pool(
    processor: BaseFileProcessor,
    slot_vars: list[Any] | None,
    slot_queue: Queue[int] | None,
) -> tuple[list[Any], Queue[int]]:
    """Return a usable slot pool for *processor*.

    A worker takes its index from ``slot_queue`` and blocks until one is free,
    so an empty queue deadlocks the batch instead of failing it -- which is
    exactly what happened the first time this ran without a window.  The pool
    is therefore built here whenever the caller supplies neither, sized to the
    processor's worker count (the number of indices ``process_batch`` hands
    out).

    Args:
        processor: The processor whose ``max_workers`` sizes the pool.
        slot_vars: Per-worker status labels, or ``None`` for headless stubs.
        slot_queue: Preloaded slot indices, or ``None`` to derive them.

    Returns:
        ``(slot_vars, slot_queue)``, both non-empty.
    """
    pool: list[Any] = (
        list(slot_vars)
        if slot_vars is not None
        else [_HeadlessSlot() for _ in range(processor.max_workers)]
    )
    queue: Queue[int] = slot_queue if slot_queue is not None else Queue()
    if slot_queue is None:
        for index in range(len(pool)):
            queue.put(index)
    return pool, queue


def _make_dsp(
    threshold: float, max_run_ms: int
) -> Callable[[AudioSegment], InplaceDspResult]:
    """Adapt the declip DSP to the shared in-place workflow.

    Args:
        threshold: Fraction of the file's own peak a sample must reach to be a
            clipping candidate.
        max_run_ms: Longest plateau the repair may reconstruct.

    Returns:
        The callable the shared workflow invokes with the decoded segment.
    """

    def _run_dsp(audio: AudioSegment) -> InplaceDspResult:
        result = declip_segment(audio, threshold=threshold, max_run_ms=max_run_ms)
        if not result.was_modified:
            if result.runs_skipped:
                action = (
                    f"Clean - {result.runs_skipped} plateau(s) need more headroom "
                    "than the file scale allows"
                )
            else:
                action = "Clean - no clipping found"
            return InplaceDspResult(
                audio=result.audio, was_modified=False, action=action
            )
        return InplaceDspResult(
            audio=result.audio,
            was_modified=True,
            action=(
                f"Restored {result.runs_found} clipped peak(s) - peak now "
                f"{result.restored_peak_db:.1f} dBFS"
            ),
            repaired_suffix=" - Repaired",
        )

    return _run_dsp


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    threshold: float,
    max_run_ms: int,
    temp_dir: str,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    lock: threading.Lock,
    on_progress: Callable[..., None],
) -> None:
    """Process one file through the shared in-place workflow.

    Args:
        name: Filename (basename only) of the audio file.
        dir_path: Directory containing *name*.
        is_dry_run: When True, detect clipping but never write audio back.
        threshold: Clipping-detection threshold for this run.
        max_run_ms: Longest reconstructible plateau, in milliseconds.
        temp_dir: Shared temporary directory for this batch.
        slot_vars: Per-worker status label variables.
        slot_queue: Pool of available slot indices.
        lock: Serialises writes to shared counters and *on_progress*.
        on_progress: Inner progress callback ``(status, display_text, log_text)``.
    """
    _build_processor().process_audio_file_inplace(
        name,
        dir_path,
        temp_dir,
        slot_vars,
        slot_queue,
        lock,
        on_progress,
        run_dsp=_make_dsp(threshold, max_run_ms),
        dsp_label=DSP_LABEL,
        tag_operation=TAG_OPERATION,
        is_dry_run=is_dry_run,
    )


@handle_audio_errors(reraise=False, context="restoration_run_declipping")
def run_declipping(
    dir_path: str,
    is_dry_run: bool,
    threshold: float = DEFAULT_THRESHOLD,
    max_run_ms: int = DEFAULT_MAX_RUN_MS,
    slot_vars: list[Any] | None = None,
    slot_queue: Queue[int] | None = None,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Scan *dir_path* and reconstruct clipped peaks in its audio files.

    Args:
        dir_path: Directory of audio files to process.
        is_dry_run: When True, detect clipping but do not write repaired audio.
        threshold: Fraction of a file's own peak at or above which a sample is
            a clipping candidate.
        max_run_ms: Longest plateau to reconstruct, in milliseconds.
        slot_vars: Per-worker status label variables managed by the window;
            ``None`` builds headless stand-ins, so a CLI or test caller needs
            no widgets.
        slot_queue: Pool of available worker-slot indices; ``None`` preloads
            one per slot, because an empty pool blocks the first worker.
        on_progress: ``(processed, total, succeeded, skipped, errors,
            display_text)`` per finished file.
        on_complete: ``(total, succeeded, skipped, errors, duration_secs,
            log_entries)`` once, after every file finished.
        on_error: Fatal-error callback taking one message.

    Raises:
        Nothing: a per-file failure is counted, and a fatal one is reported
        through *on_error*.
    """
    processor = _build_processor()
    safe_slots, queue = _resolve_pool(processor, slot_vars, slot_queue)
    report: Callable[..., None] = on_progress or (lambda **_kwargs: None)
    complete: Callable[..., None] = on_complete or (lambda **_kwargs: None)
    error: Callable[[str], None] = on_error or (lambda _message: None)

    def _make_worker(
        temp_dir: str, batch_lock: threading.Lock, reporter: Callable[..., None]
    ) -> Callable[[str], None]:
        def _worker(name: str) -> None:
            process_single_file(
                name,
                dir_path,
                is_dry_run,
                threshold,
                max_run_ms,
                temp_dir,
                safe_slots,
                queue,
                batch_lock,
                reporter,
            )

        return _worker

    processor.run_inplace_dsp_batch(
        dir_path,
        make_worker=_make_worker,
        on_progress=report,
        on_complete=complete,
        on_error=error,
        extensions=SUPPORTED_EXTENSIONS,
    )
