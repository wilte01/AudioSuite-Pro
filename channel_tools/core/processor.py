"""core/processor.py — the channel batch on the shared in-place workflow.

The discover / temp-file / write / undo / cleanup sequence is
``BaseFileProcessor.run_inplace_dsp_batch`` and ``process_audio_file_inplace``;
this module supplies only the DSP adapter and the run report.  That is what
gives the tool the suite's guarantees for free: the source is never opened for
writing until the final copy-back, tags are preserved, a lossless source keeps
its bit depth, a live write records a byte-level undo snapshot, read-only
containers are skipped rather than half-written, and an operation that changes
nothing leaves the file's bytes untouched.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any

import numpy as np
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import numpy_to_segment, segment_to_numpy
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.channel_ops import apply_operation
from audio_suite_shared.cli_base import _make_slot_queue, _make_slot_vars
from audio_suite_shared.file_processor_base import BaseFileProcessor, InplaceDspResult

from .models import ChannelSettings

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The run report's names, one per mode: the file a run names is the one its
#: View Log opens, and a dry run and a live run must not overwrite each other.
REPORT_NAMES: dict[bool, str] = {
    True: "channel_tools_dry_run_log.txt",
    False: "channel_tools_sync_log.txt",
}

#: Progress label shown while the channel maths runs.
DSP_LABEL = "Processing channels"

#: Undo operation recorded for a live write.
UNDO_OPERATION = "channel_tools_edit"


def process_audio(audio: AudioSegment, settings: ChannelSettings) -> InplaceDspResult:
    """Apply *settings* to one decoded file.

    The decode, the maths and the pack all go through the shared helpers, so
    the samples this measures are the samples the file will contain.

    Args:
        audio: The decoded segment.
        settings: The operation to apply.

    Returns:
        The shared per-file result.  ``was_modified`` is False when the
        operation left the audio byte-for-byte the same (a mono rule on a mono
        file, width 100 %), which is what tells the workflow to skip the write.
    """
    samples, sample_rate = segment_to_numpy(audio)
    result = apply_operation(
        samples,
        settings.operation,
        width_percent=settings.width_percent,
        source_channel=settings.source_channel,
        invert_target=settings.invert_target,
    )
    unchanged = result.audio.shape == samples.shape and bool(
        np.array_equal(result.audio, samples.astype(np.float64))
    )
    if unchanged:
        return InplaceDspResult(audio=audio, was_modified=False, action=result.rule)
    processed = numpy_to_segment(
        result.audio,
        sample_rate,
        sample_width=audio.sample_width,
        num_channels=int(result.audio.shape[0]),
    )
    return InplaceDspResult(audio=processed, was_modified=True, action=result.rule)


def _report_lines(
    folder: Path,
    settings: ChannelSettings,
    payload: dict[str, Any],
    *,
    dry_run: bool,
    elapsed: float,
) -> list[str]:
    """Build the run report's lines, in the suite's documented shape."""
    header = [
        "CHANNEL TOOLS REPORT\n",
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
        f"Folder: {folder}\n",
        f"Operation: {settings.rule}\n",
        "=" * 60 + "\n",
    ]
    body = [str(line) for line in payload.get("log_entries", [])]
    summary = [
        "\n" + "=" * 60 + "\n",
        "SUMMARY:\n",
        f"Files: {payload.get('total', 0)}\n",
        f"Changed: {payload.get('succeeded', 0)}\n",
        f"Unchanged: {payload.get('skipped', 0)}\n",
        f"Errors: {payload.get('errors', 0)}\n",
        f"Time: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}\n",
    ]
    return [*header, *body, *summary]


def run_channels(
    directory: str,
    *,
    settings: ChannelSettings | None = None,
    dry_run: bool = False,
    max_workers: int | None = None,
    slot_vars: list[Any] | None = None,
    slot_queue: Queue[int] | None = None,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **_ignored: Any,
) -> None:
    """Apply one channel operation to every supported file in *directory*.

    Args:
        directory: Folder to scan (one level, like every in-place tool).
        settings: The operation and its parameters; the defaults when omitted.
        dry_run: Report what would change and write no audio.
        max_workers: Worker-pool size; the host default when omitted.
        slot_vars: Per-worker status labels from a window; headless stand-ins
            are built when absent.
        slot_queue: Pool of available slot indices; preloaded when absent,
            because an empty pool blocks the first worker.
        on_progress: Called per finished file with the shared progress payload.
        on_complete: Called once with the shared counters plus the report path.
        on_error: Called with one message when the batch cannot start.

    The report is written beside the scanned files and a failed write is
    logged, never raised: by then the audio work has already happened.
    """
    folder = Path(directory)
    active = settings or ChannelSettings()
    processor = BaseFileProcessor(
        max_workers=max_workers, operation_type="channel_tools"
    )
    slots = (
        slot_vars if slot_vars is not None else _make_slot_vars(processor.max_workers)
    )
    queue = (
        slot_queue
        if slot_queue is not None
        else _make_slot_queue(processor.max_workers)
    )
    started = time.monotonic()
    progress: Callable[..., None] = on_progress or (lambda **_kwargs: None)
    complete: Callable[..., None] = on_complete or (lambda **_kwargs: None)
    error: Callable[[str], None] = on_error or (lambda _message: None)

    def finish(**payload: Any) -> None:
        """Write the run report, then publish the completion payload."""
        elapsed = float(payload.get("duration_secs", time.monotonic() - started))
        report_path = folder / REPORT_NAMES[dry_run]
        try:
            report_path.write_text(
                "".join(
                    _report_lines(
                        folder, active, payload, dry_run=dry_run, elapsed=elapsed
                    )
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - depends on the folder's permissions
            logger.error("Could not write the run report: %s", exc, exc_info=True)
        complete(**payload, report=str(report_path), rule=active.rule)

    def make_worker(
        temp_dir: str, lock: threading.Lock, reporter: Callable[..., None]
    ) -> Callable[[str], None]:
        """Build the per-file worker the shared batch submits to its pool."""

        def worker(name: str) -> None:
            processor.process_audio_file_inplace(
                name,
                directory,
                temp_dir,
                slots,
                queue,
                lock,
                reporter,
                run_dsp=lambda audio: process_audio(audio, active),
                dsp_label=DSP_LABEL,
                tag_operation=UNDO_OPERATION,
                is_dry_run=dry_run,
            )

        return worker

    processor.run_inplace_dsp_batch(
        directory,
        make_worker=make_worker,
        on_progress=progress,
        on_complete=finish,
        on_error=error,
        extensions=SUPPORTED_EXTENSIONS,
    )
