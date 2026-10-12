"""
file_processor.py
Per-file conversion worker orchestrated via BaseFileProcessor.process_batch.

No tkinter imports. All UI interaction via injected callbacks.

Changed in 1.0.1: two same-stem sources with different extensions in one
folder (e.g. song.flac + song.wav) both target song.<ext>; only the first
is converted and the collision is reported as a skip instead of silently
overwriting the first output.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import threading
import time
from collections.abc import Callable
from queue import Queue
from typing import Any

from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_file_delete_snapshot,
    use_batch,
)
from audio_suite_shared.constants import WORKER_TIMEOUT_SECS
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioFormatError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.lossless_gain import apply_track_gain
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)
from audio_suite_shared.suite_config import load_value
from audio_suite_shared.thread_safe_slot_var import ThreadSafeSlotVar

from .ffmpeg_params import WAV_DEPTH_CODECS, get_ffmpeg_params
from .formats import (
    LOSSLESS_FORMATS,
    can_convert,
    detect_format,
    discover_input_files,
)

logger = logging.getLogger(__name__)


def _claim_output_path(
    output_path: str,
    produced_outputs: set[str] | None,
    lock: threading.Lock,
) -> bool:
    """Reserve *output_path* for this run, atomically.

    Two same-stem sources with different extensions in one folder (e.g.
    ``song.flac`` and ``song.wav``) map to the same output path.  Only the
    first worker to claim it may convert; later workers skip so a completed
    conversion is never overwritten.  ``produced_outputs is None`` disables
    the guard, preserving the single-call API.

    Returns:
        True when the caller owns *output_path*; False when another worker
        already claimed it in this run.
    """
    if produced_outputs is None:
        return True
    with lock:
        if output_path in produced_outputs:
            return False
        produced_outputs.add(output_path)
        return True


def _release_output_path(
    output_path: str | None,
    produced_outputs: set[str] | None,
    lock: threading.Lock,
) -> None:
    """Release a claim from :func:`_claim_output_path` after a failed convert."""
    if produced_outputs is None or output_path is None:
        return
    with lock:
        produced_outputs.discard(output_path)


class MusicFormatConverterProcessor(BaseFileProcessor):
    def __init__(self) -> None:
        super().__init__(operation_type="format_conversion")


def _probe_wav_source(input_path: str) -> tuple[str | None, int]:
    """Return ``(sample_fmt, bits_per_raw_sample)`` for the source audio.

    Uses ffprobe; failure or absent audio stream yields ``(None, 0)``.

    Returns:
        Sample format string and raw bit depth, or ``(None, 0)`` on failure.
    """
    try:
        probe = run_secure_subprocess(
            "ffprobe",
            [
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=sample_fmt,bits_per_raw_sample",
                "-of",
                "json",
                input_path,
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, ValueError, SubprocessSecurityError, subprocess.TimeoutExpired):
        return None, 0

    if probe.returncode != 0:
        return None, 0

    try:
        stream = json.loads(probe.stdout)["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError):
        return None, 0

    sample_fmt = stream.get("sample_fmt") or None
    try:
        bits = int(stream.get("bits_per_raw_sample") or 0)
    except (TypeError, ValueError):
        bits = 0
    return sample_fmt, bits


def _wav_params_for(
    input_path: str, input_format: str, output_format: str, bit_depth: str = "auto"
) -> dict[str, Any]:
    """Build the extra ``get_ffmpeg_params`` kwargs for WAV output.

    Resolution order:
        1. An explicit ``bit_depth`` override ('16'/'24'/'32'/'float')
           wins unconditionally.
        2. A shared config override from the ``wav_bit_depth`` key wins
           next, unless the caller explicitly chose 'auto'.
        3. Lossy sources have no meaningful source depth, so they keep the
           historical 16-bit WAV behaviour (no probe).
        4. Lossless sources are probed so the WAV keeps the source depth
           (e.g. 24-bit FLAC -> pcm_s24le). Probe failure falls back to 16-bit.

    Returns:
        Keyword arguments to pass to ``get_ffmpeg_params``.
    """
    if output_format != "wav":
        return {}

    if bit_depth in WAV_DEPTH_CODECS:
        return {"wav_depth": bit_depth}

    override = load_value("wav_bit_depth", "auto")
    if override in WAV_DEPTH_CODECS:
        return {"wav_depth": override}

    if input_format in LOSSLESS_FORMATS:
        sample_fmt, bits = _probe_wav_source(input_path)
        if sample_fmt:
            return {
                "wav_depth": "auto",
                "source_sample_fmt": sample_fmt,
                "source_bits_per_sample": bits,
            }
    return {}


# ── Lossless-gain helper ──────────────────────────────────────────────────────

_NORMALIZE_TOLERANCE_DB: float = 0.5
"""Gain adjustments smaller than this (in dB) are skipped as inaudible."""


def _measure_lufs(file_path: str) -> float | None:
    """Measure integrated loudness (LUFS) of *file_path* via FFmpeg loudnorm.

    Returns:
        The integrated loudness in LUFS, or ``None`` if measurement failed.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i",
        file_path,
        "-af",
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]
    result = run_secure_subprocess(
        cmd[0],
        cmd[1:],
        capture_output=True,
        timeout=120,
        check=False,
    )
    # The loudnorm JSON block is the last {...} on stderr.
    json_blocks = re.findall(r"\{[^{}]*\}", result.stderr)
    if not json_blocks:
        return None
    try:
        data = json.loads(json_blocks[-1])
        val = float(data.get("input_i", "nan"))
    except (json.JSONDecodeError, ValueError, KeyError):
        return None
    return None if math.isinf(val) or math.isnan(val) else val


def _dry_run_report(
    filename: str,
    output_name: str,
    input_format: str,
    output_format: str,
    input_size: float,
    lossy_formats: list[str],
    delete_original: bool,
    normalize_mp3: bool,
    target_lufs: float,
    slot_vars: list[ThreadSafeSlotVar],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., Any],
) -> None:
    """Build and report the dry-run preview strings."""
    slot_vars[slot_idx].set(f"Simulating: {filename[:25]}...")
    output_size = (
        input_size * 3.5 if output_format not in lossy_formats else input_size * 0.8
    )
    display = (
        f"[DRY RUN] {filename} \u2192 {output_name} "
        f"(est. {input_size:.1f}MB \u2192 {output_size:.1f}MB)"
    )
    log = (
        f"[DRY RUN] {filename} | "
        f"{input_format.upper()} \u2192 {output_format.upper()} | "
        f"Est. Size: {input_size:.2f}MB \u2192 {output_size:.2f}MB"
    )
    if delete_original:
        display += " [WOULD DELETE ORIGINAL]"
        log += " | Would delete original"
    if normalize_mp3 and output_format == "mp3":
        display += " [WOULD NORMALIZE MP3]"
        log += f" | Would normalize to {target_lufs:.1f} LUFS"
    with lock:
        on_progress(
            n_converted=1,
            n_skipped=0,
            n_errors=0,
            display_text=display,
            log_text=log + "\n",
        )


def _convert_and_verify(
    input_path: str,
    output_path: str,
    output_format: str,
    quality: str,
    sample_rate: str,
    dither: bool,
    bit_depth: str,
    input_format: str,
    base_name: str,
    processor: MusicFormatConverterProcessor | None,
    slot_vars: list[ThreadSafeSlotVar],
    slot_idx: int,
) -> float:
    """Run ffmpeg conversion and return the output file size in MB."""
    output_subdir = os.path.dirname(output_path)
    if output_subdir:
        os.makedirs(output_subdir, exist_ok=True)

    slot_vars[slot_idx].set(f"Converting: {base_name[:25]}...")
    cmd = get_ffmpeg_params(
        input_path,
        output_path,
        output_format,
        quality,
        sample_rate=sample_rate,
        dither=dither,
        **_wav_params_for(input_path, input_format, output_format, bit_depth),
    )

    def _run_ffmpeg() -> subprocess.CompletedProcess[str]:
        return run_secure_subprocess(
            cmd[0],
            cmd[1:],
            capture_output=True,
            timeout=WORKER_TIMEOUT_SECS,
            check=False,
        )

    if processor:
        result = processor.run_with_retry(
            _run_ffmpeg,
            max_retries=3,
            label=f"convert_{base_name}",
        )
    else:
        result = _run_ffmpeg()

    if result.returncode != 0 or not os.path.exists(output_path):
        error_lines = [
            line
            for line in result.stderr.split("\n")
            if any(kw in line.lower() for kw in ("error", "invalid", "failed"))
        ]
        err_msg = error_lines[0] if error_lines else result.stderr[-200:]
        raise AudioExternalToolError(f"Conversion failed: {err_msg}", tool="ffmpeg")

    return os.path.getsize(output_path) / (1024 * 1024)


def _apply_post_gain(
    output_path: str,
    normalize_mp3: bool,
    output_format: str,
    target_lufs: float,
) -> str:
    """Apply MP3 loudness normalisation and return the gain status string."""
    if not (normalize_mp3 and output_format == "mp3"):
        return ""
    try:
        measured = _measure_lufs(output_path)
        if measured is None:
            return " [GAIN FAILED: measurement unavailable]"
        gain_needed = target_lufs - measured
        if abs(gain_needed) <= _NORMALIZE_TOLERANCE_DB:
            return f" [ALREADY AT {measured:.1f} LUFS]"
        apply_track_gain(output_path, gain_needed)
        return f" [GAIN APPLIED: {gain_needed:+.2f} dB]"
    except (AudioFormatError, OSError, SubprocessSecurityError) as exc:
        mapped = map_to_audio_error(exc)
        logger.warning(
            "Lossless-gain failed after conversion: %s", mapped, exc_info=True
        )
        return f" [GAIN FAILED: {user_message_for(mapped)[:30]}]"


def _delete_original(
    input_path: str,
    output_path: str,
    delete_original: bool,
) -> tuple[bool, str]:
    """Delete the source file after successful conversion.

    Returns ``(deleted, status_string)``.
    """
    if not (delete_original and os.path.exists(output_path)):
        return False, ""
    try:
        with open(input_path, "rb") as fh:
            original_bytes = fh.read()
        os.remove(input_path)
        record_file_delete_snapshot(input_path, original_bytes)
        return True, " [ORIGINAL DELETED]"
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.warning("Delete failed during conversion: %s", mapped, exc_info=True)
        return False, f" [DELETE FAILED: {user_message_for(mapped)[:30]}]"


def process_single_file(
    filename: str,
    input_dir: str,
    output_dir: str,
    output_format: str,
    quality: str,
    delete_original: bool,
    is_dry_run: bool,
    lossy_formats: list[str],
    slot_vars: list[ThreadSafeSlotVar],
    slot_queue: Queue[Any],
    lock: threading.Lock,
    on_progress: Callable[..., Any],
    processor: MusicFormatConverterProcessor | None = None,
    sample_rate: str = "source",
    bit_depth: str = "auto",
    normalize_mp3: bool = False,
    target_lufs: float = -16.0,
    dither: bool = True,
    produced_outputs: set[str] | None = None,
) -> None:
    """Acquire a slot, convert one audio file, release the slot.

    When *produced_outputs* is supplied (a live batch), the computed output
    path is claimed before conversion: a second source resolving to the same
    path is skipped rather than overwriting the first output.
    """
    slot_idx = slot_queue.get()
    input_path = os.path.join(input_dir, filename)
    claimed_output: str | None = None

    try:
        input_format = detect_format(filename)
        if not input_format:
            raise AudioFormatError("Unsupported or unknown format")

        slot_vars[slot_idx].set(f"Checking: {filename[:25]}...")

        ok, reason = can_convert(input_format, output_format)
        if not ok:
            display = f"[SKIPPED] {filename} - {reason}"
            log = f"[SKIPPED] {filename} - {reason}\n"
            with lock:
                on_progress(
                    n_converted=0,
                    n_skipped=1,
                    n_errors=0,
                    display_text=display,
                    log_text=log,
                )
            return

        base_name = os.path.splitext(filename)[0]
        output_name = f"{base_name}.{output_format}"
        output_path = os.path.join(output_dir, output_name)
        input_size = os.path.getsize(input_path) / (1024 * 1024)

        if is_dry_run:
            _dry_run_report(
                filename,
                output_name,
                input_format,
                output_format,
                input_size,
                lossy_formats,
                delete_original,
                normalize_mp3,
                target_lufs,
                slot_vars,
                slot_idx,
                lock,
                on_progress,
            )
            return

        if not _claim_output_path(output_path, produced_outputs, lock):
            display = (
                f"[SKIPPED] {filename} - output {output_name} already "
                "produced from another source in this run"
            )
            with lock:
                on_progress(
                    n_converted=0,
                    n_skipped=1,
                    n_errors=0,
                    display_text=display,
                    log_text=display + "\n",
                )
            return
        claimed_output = output_path

        output_size = _convert_and_verify(
            input_path,
            output_path,
            output_format,
            quality,
            sample_rate,
            dither,
            bit_depth,
            input_format,
            base_name,
            processor,
            slot_vars,
            slot_idx,
        )

        gain_status = _apply_post_gain(
            output_path,
            normalize_mp3,
            output_format,
            target_lufs,
        )

        deleted, delete_status = _delete_original(
            input_path,
            output_path,
            delete_original,
        )

        display = (
            f"[CONVERTED] {filename} \u2192 {output_name} "
            f"({input_size:.1f}MB \u2192 {output_size:.1f}MB)"
            f"{gain_status}{delete_status}"
        )
        log = (
            f"[CONVERTED] {filename} | "
            f"{input_format.upper()} \u2192 {output_format.upper()} | "
            f"Size: {input_size:.2f}MB \u2192 {output_size:.2f}MB"
        )
        if gain_status:
            log += f" | {gain_status.strip()}"
        if deleted:
            log += " | Original deleted"

        with lock:
            on_progress(
                n_converted=1,
                n_skipped=0,
                n_errors=0,
                display_text=display,
                log_text=log + "\n",
            )

    except subprocess.TimeoutExpired:
        _release_output_path(claimed_output, produced_outputs, lock)
        display = f"[ERROR] {filename}: Conversion timeout"
        with lock:
            on_progress(
                n_converted=0,
                n_skipped=0,
                n_errors=1,
                display_text=display,
                log_text=display + "\n",
            )

    except (
        OSError,
        ValueError,
        SubprocessSecurityError,
        subprocess.CalledProcessError,
        AudioFormatError,
        AudioExternalToolError,
    ) as exc:
        _release_output_path(claimed_output, produced_outputs, lock)
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        action = get_recovery_action(exc, "format_conversion")

        if action == RecoveryAction.SKIP:
            display = f"[SKIP] {filename}: {user_message_for(mapped)}"
            with lock:
                on_progress(
                    n_converted=0,
                    n_skipped=1,
                    n_errors=0,
                    display_text=display,
                    log_text=f"[SKIP] {filename}: {user_message_for(mapped)}\n",
                )
        else:
            display = f"[ERROR] {filename}: {user_message_for(mapped)}"
            with lock:
                on_progress(
                    n_converted=0,
                    n_skipped=0,
                    n_errors=1,
                    display_text=display,
                    log_text=f"[ERROR] {filename}: {user_message_for(mapped)}\n",
                )

    finally:
        slot_vars[slot_idx].set("IDLE")
        slot_queue.put(slot_idx)


@handle_audio_errors(reraise=False, context="format_converter_run_conversion")
def run_conversion(
    input_dir: str,
    output_dir: str,
    output_format: str,
    quality: str,
    delete_originals: bool,
    is_dry_run: bool,
    lossy_formats: list[str],
    slot_vars: list[ThreadSafeSlotVar],
    slot_queue: Queue[Any],
    on_progress: Callable[..., Any],
    on_complete: Callable[..., Any],
    on_error: Callable[..., Any],
    sample_rate: str = "source",
    bit_depth: str = "auto",
    normalize_mp3: bool = False,
    target_lufs: float = -16.0,
    dither: bool = True,
) -> None:
    """Scan directory recursively, convert every audio file it finds.

    Mixed source formats are supported: each file is validated against its
    own detected format, and per-format counts are reported to the caller.
    """
    processor = MusicFormatConverterProcessor()

    # Recursive discovery keeps each file's relative path so the output
    # tree mirrors the input instead of flattening every track together.
    try:
        files = discover_input_files(input_dir, recursive=True)
    except OSError as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
        return

    format_counts: dict[str, int] = {}
    for rel_path in files:
        fmt = detect_format(rel_path)
        if fmt:
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

    # Create output directory if needed
    if output_dir != input_dir and not is_dry_run:
        os.makedirs(output_dir, exist_ok=True)

    lock = threading.Lock()
    produced_outputs: set[str] = set()
    processed = [0]
    converted = [0]
    skipped = [0]
    errors = [0]
    log_entries: list[str] = []

    def _on_progress(
        n_converted: int,
        n_skipped: int,
        n_errors: int,
        display_text: str,
        log_text: str,
    ) -> None:
        processed[0] += 1
        converted[0] += n_converted
        skipped[0] += n_skipped
        errors[0] += n_errors
        log_entries.append(log_text)
        on_progress(
            processed=processed[0],
            total=len(files),
            converted=converted[0],
            skipped=skipped[0],
            errors=errors[0],
            display_text=display_text,
        )

    start = time.time()

    undo_batch: str | None = get_active_batch_id()

    def _process_with_undo(
        fname: str,
        in_dir: str,
        out_dir: str,
        out_fmt: str,
        qual: str,
        del_orig: bool,
        dry: bool,
        lossy: list[str],
        s_vars: list[ThreadSafeSlotVar],
        s_queue: Queue[Any],
        lck: threading.Lock,
        prog: Callable[..., Any],
        s_rate: str,
        b_depth: str,
        norm_mp3: bool,
        tgt_lufs: float,
        proc: MusicFormatConverterProcessor | None = None,
        dith: bool = True,
    ) -> None:
        with use_batch(undo_batch):
            process_single_file(
                fname,
                in_dir,
                out_dir,
                out_fmt,
                qual,
                del_orig,
                dry,
                lossy,
                s_vars,
                s_queue,
                lck,
                prog,
                proc,
                sample_rate=s_rate,
                bit_depth=b_depth,
                normalize_mp3=norm_mp3,
                target_lufs=tgt_lufs,
                dither=dith,
                produced_outputs=produced_outputs,
            )

    def _worker(name: str) -> object:
        _process_with_undo(
            name,
            input_dir,
            output_dir,
            output_format,
            quality,
            delete_originals,
            is_dry_run,
            lossy_formats,
            slot_vars,
            slot_queue,
            lock,
            _on_progress,
            sample_rate,
            bit_depth,
            normalize_mp3,
            target_lufs,
            processor,
            dither,
        )
        return None

    processor.process_batch(files, _worker)

    on_complete(
        total=len(files),
        processed=converted[0] + skipped[0] + errors[0],
        converted=converted[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.time() - start,
        log_entries=log_entries,
        output_dir=output_dir,
        format_counts=format_counts,
    )
