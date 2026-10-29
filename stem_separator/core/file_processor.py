"""
core/file_processor.py
Multi-threaded orchestrator for the Stem Separator.

Discovers the audio files in one directory, separates each into its stems and
writes them under ``<output_dir>/<track>/``.  The source files are never
touched: this tool produces new files, so it records no undo snapshot.

Layout
------
::

    <output>/<track>/vocals.wav
    <output>/<track>/drums.wav
    <output>/<track>/bass.wav
    <output>/<track>/other.wav
    <output>/<track>/mix.wav        # only when a mix is requested

Two sources with the same stem (``song.flac`` and ``song.wav``) resolve to the
same ``<output>/song`` folder.  The first worker claims it and the second is
reported as skipped, so one source never overwrites another's stems.

Counter semantics
-----------------
  processed     : every file attempted (separated + skipped + errors)
  separated     : files whose stems were written (or would be, in a dry run)
  skipped       : files whose output folder was already produced this run
  errors        : files that raised while separating or writing

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import failure_reason, handle_audio_errors
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS

from . import demucs_engine
from .demucs_engine import mix_stems, separate, write_stem
from .models import (
    MIX_FILENAME,
    STEM_SUFFIX,
    SeparatedTrack,
    StemSeparationParams,
)

logger = logging.getLogger(__name__)

#: Progress label shown while the model runs.
DSP_LABEL = "Separating stems"

#: Worker-pool size, imported by ``app.py`` to size its slot display.
MAX_WORKERS = DEFAULT_MAX_WORKERS


def _build_processor() -> BaseFileProcessor:
    return BaseFileProcessor(max_workers=MAX_WORKERS, operation_type="stem_separation")


def track_folder(output_dir: str, filename: str) -> Path:
    """Return the folder one source file's stems are written into.

    Args:
        output_dir: The run's output directory.
        filename: The source file's basename.

    Returns:
        ``<output_dir>/<stem-of-filename>``.
    """
    return Path(output_dir) / Path(filename).stem


def _claim_folder(folder: Path, claimed: set[str], lock: threading.Lock) -> bool:
    """Reserve *folder* for this worker; False when another already produced it."""
    key = os.path.normcase(str(folder))
    with lock:
        if key in claimed:
            return False
        claimed.add(key)
        return True


def _write_track(
    track: SeparatedTrack,
    folder: Path,
    params: StemSeparationParams,
) -> list[Path]:
    """Write every requested stem (and the mix) and return the written paths."""
    written: list[Path] = []
    stems = params.resolved_stems()
    for stem in stems:
        path = folder / f"{stem}{STEM_SUFFIX}"
        write_stem(track.stems[stem], track.sample_rate, path)
        written.append(path)
    if params.write_mix:
        mixed = mix_stems(track.stems, stems)
        mix_path = folder / MIX_FILENAME
        write_stem(mixed, track.sample_rate, mix_path)
        written.append(mix_path)
    return written


def process_single_file(
    name: str,
    dir_path: str,
    params: StemSeparationParams,
    claimed: set[str],
    lock: threading.Lock,
    on_progress: Callable[..., None],
) -> None:
    """Separate one file, reporting exactly one progress event.

    Args:
        name: Filename (basename only).
        dir_path: Directory containing *name*.
        params: The run's settings.
        claimed: Output folders already produced in this run, guarded by *lock*.
        lock: Serialises the claim and the progress callback.
        on_progress: ``(n_separated, n_skipped, n_errors, display_text,
            log_text, files_written)`` progress callback.
    """
    source = os.path.join(dir_path, name)
    folder = track_folder(params.output_dir, name)
    stems = params.resolved_stems()

    def _report(
        n_separated: int,
        n_skipped: int,
        n_errors: int,
        display_text: str,
        log_text: str,
        files_written: int = 0,
    ) -> None:
        with lock:
            on_progress(
                n_separated=n_separated,
                n_skipped=n_skipped,
                n_errors=n_errors,
                display_text=display_text,
                log_text=log_text,
                files_written=files_written,
            )

    if not _claim_folder(folder, claimed, lock):
        reason = f"output folder already produced: {folder}"
        _report(
            0,
            1,
            0,
            f"[SKIPPED] {name} - {reason}",
            f"[SKIPPED] {name} - {reason}\n",
        )
        return

    if params.dry_run:
        # No model load and no file: a dry run reports the plan it would carry
        # out.  The output folder is not created, so "dry" is checkable on disk.
        plan = ", ".join(stems)
        if params.write_mix:
            plan += ", mix"
        _report(
            1,
            0,
            0,
            f"[DRY RUN] {name} - would write {len(stems)} stems ({plan})",
            f"[DRY RUN] {name} - would separate into {plan} in {folder}\n",
        )
        return

    try:
        track = separate(
            source,
            model=params.model,
            device=params.device,
            stems=stems,
        )
        written = _write_track(track, folder, params)
    except Exception as exc:
        reason = failure_reason(exc)
        logger.warning(
            "Stem separation failed for %s: %s", source, reason, exc_info=True
        )
        _report(0, 0, 1, f"[ERROR] {name} - {reason}", f"[ERROR] {name} - {reason}\n")
        return

    detail = ", ".join(path.name for path in written)
    _report(
        1,
        0,
        0,
        f"[SEPARATED] {name} - {len(written)} file(s): {detail}",
        f"[SEPARATED] {name} - wrote {detail} to {folder}\n",
        files_written=len(written),
    )


@handle_audio_errors(reraise=True, context="stem_separation_run")
def run_stem_separation(
    dir_path: str,
    params: StemSeparationParams,
    slot_vars: list[Any],
    slot_queue: Queue[int],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
) -> None:
    """Separate every audio file in *dir_path* into stems under ``output_dir``.

    Parameters
    ----------
    dir_path : str
        Absolute path to the source directory.
    params : StemSeparationParams
        Separation settings, including the output directory and dry-run flag.
    slot_vars : list[Any]
        Per-worker status label variables.
    slot_queue : Queue[int]
        Pool of available slot indices.
    on_progress : Callable[..., None]
        Per-file progress callback.
    on_complete : Callable[..., None]
        Completion callback; publishes the counts the GUI report renders.
    on_error : Callable[[str], None]
        Fatal-error callback.

    Raises:
        AudioConfigurationError: The parameters are incomplete, the output
            directory cannot be created, or Demucs is not installed for a live
            run.  Raised rather than reported through *on_error* so a CLI run
            exits non-zero and its JSON says why; the GUI wraps this call and
            routes the message to ``on_error`` itself.
    """
    problems = params.validate()
    if problems:
        raise ValueError(" ".join(problems))

    output_dir = os.path.abspath(params.output_dir)
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Could not create the output directory: {exc}") from exc

    if not params.dry_run:
        demucs_engine.require_demucs()

    device = demucs_engine.device_for(params.device)
    # Recorded at INFO so the program log answers "which device did that run
    # use, and why" without re-reading the Setup tab; the reason is what makes a
    # CPU fallback auditable (a CPU-only torch build and a missing driver are
    # different problems with different fixes).
    logger.info("Stem separation device: %s - %s", device.label(), device.reason)
    processor = _build_processor()

    try:
        files = processor.discover_audio_files(dir_path, SUPPORTED_EXTENSIONS)
    except Exception as exc:  # noqa: BLE001 - re-raised as a fatal error
        on_error(failure_reason(exc))
        raise

    separated = [0]
    skipped = [0]
    errors = [0]
    written_count = [0]
    log_entries: list[str] = []
    claimed: set[str] = set()

    def _on_progress(
        n_separated: int,
        n_skipped: int,
        n_errors: int,
        display_text: str,
        log_text: str,
        files_written: int = 0,
    ) -> None:
        separated[0] += n_separated
        skipped[0] += n_skipped
        errors[0] += n_errors
        written_count[0] += files_written
        log_entries.append(log_text)
        on_progress(
            processed=separated[0] + skipped[0] + errors[0],
            total=len(files),
            separated=separated[0],
            skipped=skipped[0],
            errors=errors[0],
            display_text=display_text,
        )

    start = time.time()
    lock = threading.Lock()

    def _worker(name: str) -> None:
        slot_idx = slot_queue.get()
        try:
            if slot_vars:
                slot_vars[slot_idx].set(f"{DSP_LABEL}: {name[:25]}...")
            process_single_file(
                name,
                dir_path,
                params,
                claimed,
                lock,
                _on_progress,
            )
        finally:
            if slot_vars:
                slot_vars[slot_idx].set("IDLE")
            slot_queue.put(slot_idx)

    processor.process_batch(files, _worker)

    log_entries.insert(
        0,
        f"=== Stem separation — {len(files)} file(s) — "
        f"{'Dry Run' if params.dry_run else 'Live Update'} — "
        f"{demucs_engine.describe_device(device)} ===\n",
    )
    completion = {
        "total": len(files),
        "processed": separated[0] + skipped[0] + errors[0],
        "separated": separated[0],
        "files_written": written_count[0],
        "skipped": skipped[0],
        "errors": errors[0],
        "duration_secs": time.time() - start,
        "log_entries": log_entries,
        "output_dir": output_dir,
        "device": demucs_engine.describe_device(device),
    }
    on_complete(**completion)
