"""
inplace_workflow.py - part of BaseFileProcessor, split out in 2.4.3.

WP-9 #2 moved this group of methods off :class:`BaseFileProcessor` into
``InplaceWorkflowMixin``. Method bodies are unchanged, and ``file_processor_base``
still re-exports every public name, so existing importers are
unaffected.

Changed in 2.4.3: split out of ``audio_suite_shared.file_processor_base``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Any, Callable

from pydub import AudioSegment

from .audio_formats import (
    get_export_args,
    is_read_only_extension,
    preserve_depth_params,
)
from .batch_undo import (
    get_active_batch_id,
    record_audio_overwrite_snapshot,
    use_batch,
)
from .exceptions import handle_audio_errors, map_to_audio_error, user_message_for
from .reporting import (
    CompleteCallback,
    ErrorCallback,
    ProgressCallback,
    _preflight_discover,
)

logger = logging.getLogger(f"audio_suite.{__name__}")


@dataclass(frozen=True)
class InplaceDspResult:
    """Outcome of a per-tool DSP pass over a single file.

    Mirrors the shape of the per-tool DSP results (``NoiseReductionResult`` /
    ``DeclickResult``): ``audio`` is always present - the DSP implementations
    return the untouched input when there is nothing to do - and
    ``was_modified`` carries the verdict.  ``action`` is the human-readable
    summary the shared report displays; ``repaired_suffix`` is appended to it
    only once the repaired audio has actually been written back to disk.

    This is the *only* thing a tool has to supply to plug its DSP into the
    shared in-place workflow; the DSP itself stays in the tool module.
    """

    audio: AudioSegment
    was_modified: bool
    action: str
    repaired_suffix: str = ""


#: Per-tool DSP adapter: takes the decoded segment, returns the shared result.
InplaceDspFn = Callable[[AudioSegment], InplaceDspResult]

#: Builds a per-file worker.  Called once per batch with the shared temp dir,
#: counter lock and inner progress callback; returns the ``worker(name)`` that
#: :meth:`BaseFileProcessor.run_inplace_dsp_batch` submits to the thread pool.
InplaceWorkerFactory = Callable[
    [str, threading.Lock, ProgressCallback], Callable[[str], None]
]


class InplaceWorkflowMixin:
    """The shared in-place DSP batch and its per-file temp-file workflow."""

    #: Host surface provided by ``BaseFileProcessor``'s other mixins.
    max_workers: int
    process_batch: Callable[..., list[object]]

    def discover_audio_files(
        self, dir_path: str, extensions: tuple[str, ...] | None = None
    ) -> list[str]:
        """Provided by ``FileDiscoveryMixin``, composed ahead of this one."""
        raise NotImplementedError

    def process_audio_file_inplace(
        self,
        name: str,
        dir_path: str,
        temp_dir: str,
        slot_vars: list[Any],
        slot_queue: Queue[int],
        lock: threading.Lock,
        on_progress: ProgressCallback,
        *,
        run_dsp: InplaceDspFn,
        dsp_label: str,
        tag_operation: str,
        is_dry_run: bool,
    ) -> None:
        """Run one file through the shared in-place DSP workflow.

        This is the single implementation of the discover/temp-file/write/undo
        sequence that the in-place repair tools share; only ``run_dsp`` (and
        the wording it produces) differs between them.

        Steps
        -----
        1. Copy the source into a per-worker temp directory, so the source
           file is never opened for writing until the final copy-back.
        2. Read and preserve all metadata tags.
        3. Run the tool's DSP via *run_dsp*.
        4. Live run only: export the processed audio, re-apply the tags,
           record the undo snapshot, then copy back over the source.
        5. Report the outcome through *on_progress* under *lock*.

        The slot index is always returned to *slot_queue* and the per-worker
        temp directory is always removed, so neither can leak on an exception.

        Args:
            name: Filename (basename only) to process.
            dir_path: Directory containing *name*.
            temp_dir: Shared batch temp directory; a per-worker
                sub-directory is created inside it and removed afterwards.
            slot_vars: Per-worker status label variables.
            slot_queue: Pool of available slot indices.
            lock: Serialises writes to shared counters and *on_progress*.
            on_progress: Inner progress callback
                ``(status, display_text, log_text)`` where status is one of
                ``"SKIP"``, ``"FOUND"``, ``"FIXED"`` or ``"ERROR"``.
            run_dsp: Tool-supplied DSP adapter returning an
                :class:`InplaceDspResult`.
            dsp_label: Progress label, e.g. ``"Reducing noise"``.
            tag_operation: Undo operation name recorded for a live write.  It
                is stored on the byte-level undo record that restores the
                file, not on a separate tag record.
            is_dry_run: When ``True``, detect but never write audio back.
        """
        from .tag_helper import read_tags_raw, write_tags_raw

        slot_idx = slot_queue.get()
        full_path = os.path.join(dir_path, name)
        ext = os.path.splitext(name)[1].lower()

        if is_read_only_extension(name):
            display = (
                f"[SKIP] {name} → read-only format ({ext}); cannot rewrite in place"
            )
            log = f"[SKIP] {name} | read-only format ({ext}); cannot rewrite in place\n"
            slot_vars[slot_idx].set("IDLE")
            slot_queue.put(slot_idx)
            with lock:
                on_progress(status="SKIP", display_text=display, log_text=log)
            return

        worker_temp = tempfile.mkdtemp(dir=temp_dir)
        temp_input = os.path.join(worker_temp, f"in{ext}")
        temp_output = os.path.join(worker_temp, f"out{ext}")

        try:
            slot_vars[slot_idx].set(f"Loading: {name[:25]}...")
            original_tags = read_tags_raw(full_path)
            shutil.copy2(full_path, temp_input)

            slot_vars[slot_idx].set(f"{dsp_label}: {name[:25]}...")
            audio = AudioSegment.from_file(temp_input)
            outcome = run_dsp(audio)

            if not outcome.was_modified:
                status = "SKIP"
                action = outcome.action
            else:
                action = outcome.action
                status = "FOUND"  # dry run: detected but not written
                if not is_dry_run:
                    slot_vars[slot_idx].set(f"Exporting: {name[:25]}...")
                    fmt, export_params = get_export_args(ext)
                    # Pin a lossless source's bit depth: FFmpeg's WAV/AIFF
                    # encoders default to 16-bit and silently truncated a
                    # 24-bit source on every in-place rewrite (F-10).
                    export_params = [
                        *export_params,
                        *preserve_depth_params(ext, full_path),
                    ]
                    outcome.audio.export(
                        temp_output, format=fmt, parameters=export_params
                    )

                    slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
                    write_tags_raw(temp_output, original_tags, record_snapshot=False)
                    # Byte-level snapshot, taken while the source file is
                    # still in its pre-run state: the write below replaces the
                    # audio, so a tag-only snapshot would let Undo restore the
                    # tags of audio that is still processed.
                    record_audio_overwrite_snapshot(full_path, tag_operation)
                    shutil.copy2(temp_output, full_path)
                    action += outcome.repaired_suffix
                    status = "FIXED"

            display = f"[{status}] {name} → {action}"
            log = f"[{status}] {name} | {action}\n"

            with lock:
                on_progress(status=status, display_text=display, log_text=log)

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            # Report the sanitised message, not raw str(exc): the raw text can
            # carry internal paths/details meant only for the log file.  This
            # mirrors run_parallel_processing's on_error handling.
            message = user_message_for(mapped)
            display = f"[ERROR] {name}: {message[:80]}"
            log = f"[ERROR] {name}: {message}\n"
            with lock:
                on_progress(status="ERROR", display_text=display, log_text=log)

        finally:
            shutil.rmtree(worker_temp, ignore_errors=True)
            slot_vars[slot_idx].set("IDLE")
            slot_queue.put(slot_idx)

    @handle_audio_errors(reraise=False, context="run_inplace_dsp_batch")
    def run_inplace_dsp_batch(
        self,
        dir_path: str,
        make_worker: InplaceWorkerFactory,
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        on_error: ErrorCallback,
        extensions: tuple[str, ...] | None = None,
    ) -> None:
        """Discover, dispatch and summarise a batch of in-place DSP repairs.

        The batch-level half of the shared in-place workflow: sorted discovery,
        the succeeded/skipped/errors counters, joining the caller's undo batch,
        the shared temp directory and the completion callback.  Each file is
        handled by :meth:`process_audio_file_inplace` via the worker that
        *make_worker* builds.

        Unlike :meth:`run_parallel_processing` this method does **not** wrap
        files in a retry loop: a per-file failure is already reported through
        the counters by the worker, so a retry could never observe it.

        Args:
            dir_path: Directory of audio files to process.
            make_worker: Factory called once as
                ``make_worker(temp_dir, lock, on_progress)`` and expected to
                return a ``worker(name)`` callable.
            on_progress: Called per finished file with
                ``(processed, total, succeeded, skipped, errors, display_text)``.
            on_complete: Called once after every file finished with
                ``(total, processed, succeeded, skipped, errors, duration_secs,
                log_entries)``.
            on_error: Called for fatal errors that prevent the batch from
                starting, with a sanitised ``user_message_for()`` string.
            extensions: Extensions to discover.  Defaults to
                ``SUPPORTED_EXTENSIONS``.
        """
        files = _preflight_discover(
            self,
            dir_path,
            extensions,
            on_error,
            sort=True,
            empty_message="No supported audio files found in the selected directory.",
        )
        if files is None:
            return

        lock = threading.Lock()
        processed = [0]
        succeeded = [0]
        skipped = [0]
        errors = [0]
        log_entries: list[str] = []
        undo_batch = get_active_batch_id()

        def _on_progress(status: str, display_text: str, log_text: str) -> None:
            """Inner callback — called under *lock* from each worker thread."""
            processed[0] += 1
            if status == "ERROR":
                errors[0] += 1
            elif status == "SKIP":
                skipped[0] += 1
            else:  # "FOUND" or "FIXED"
                succeeded[0] += 1
            log_entries.append(log_text)
            on_progress(
                processed=processed[0],
                total=len(files),
                succeeded=succeeded[0],
                skipped=skipped[0],
                errors=errors[0],
                display_text=display_text,
            )

        start = time.monotonic()
        temp_dir = tempfile.mkdtemp()
        worker = make_worker(temp_dir, lock, _on_progress)

        def _worker(name: str) -> None:
            """Run one file inside the caller's undo batch."""
            with use_batch(undo_batch):
                worker(name)

        # KEEP-IN-SYNC: run_parallel_processing, run_cpu_bound_processing,
        # run_analysis_workflow — the executor loops are intentionally
        # ununified (D5) because each uses a different pool/process model.
        try:
            self.process_batch(files, _worker, max_workers=self.max_workers)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        on_complete(
            total=len(files),
            processed=succeeded[0] + skipped[0] + errors[0],
            succeeded=succeeded[0],
            skipped=skipped[0],
            errors=errors[0],
            duration_secs=time.monotonic() - start,
            log_entries=log_entries,
        )
