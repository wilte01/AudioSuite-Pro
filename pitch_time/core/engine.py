"""engine.py — process a folder of files through the shared transforms.

Decoding and writing stay with the suite's own paths: pydub for the container
(the source's channel count and sample rate are never converted) and
``audio_formats.get_export_args`` / ``preserve_depth_params`` for the encoder
parameters, so a 24-bit WAV does not come back as 16-bit.  The transforms
themselves are ``audio_suite_shared.dsp_time_pitch``; the tags come across
through ``audio_suite_shared.tag_copy``.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment

from audio_suite_shared.audio_formats import (
    SUPPORTED_EXTENSIONS,
    export_segment,
    is_read_only_extension,
)
from audio_suite_shared.dsp_time_pitch import (
    TimePitchResult,
    pitch_shift,
    time_stretch,
)
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.tag_copy import copy_easy_tags

from .models import MODE_PITCH, PitchTimeSettings, output_name

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Extensions the tool processes: every format the suite can read.
INPUT_EXTENSIONS: tuple[str, ...] = tuple(SUPPORTED_EXTENSIONS)

#: The run report's names, one per mode.  The file a run names is the one View
#: Log opens, and a dry run must not overwrite a live run's report.
REPORT_NAMES: dict[bool, str] = {
    True: "pitch_time_dry_run_log.txt",
    False: "pitch_time_sync_log.txt",
}


@dataclass(frozen=True)
class FileOutcome:
    """What one file's run produced.

    Attributes:
        source: The file read.
        output: The file written (or that a dry run would write).
        original_seconds: The source's measured length.
        processed_seconds: The render's measured length.
        written: False for a dry run.
    """

    source: Path
    output: Path
    original_seconds: float
    processed_seconds: float
    written: bool


def output_path_for(source: Path, settings: PitchTimeSettings) -> Path:
    """Return the path a run writes for *source*."""
    return source.with_name(output_name(source.name, settings))


def _decode(source: Path) -> tuple[npt.NDArray[np.float32], int, int, int]:
    """Decode *source* without changing its rate or channel count.

    Args:
        source: The file to read.

    Returns:
        ``(signal, sample_rate, channels, sample_width)`` where *signal* is
        ``(n,)`` mono or ``(channels, n)`` float32 in [-1, 1].

    Raises:
        AudioSuiteError: The container cannot be decoded.
        OSError: The file cannot be read.
    """
    segment = AudioSegment.from_file(str(source))
    raw = np.asarray(segment.get_array_of_samples(), dtype=np.float64)
    scale = float(1 << (8 * segment.sample_width - 1))
    channels_first: npt.NDArray[np.float64]
    if segment.channels > 1:
        channels_first = raw.reshape(-1, segment.channels).T
    else:
        channels_first = raw.reshape(-1)
    signal = (channels_first / scale).astype(np.float32)
    return signal, int(segment.frame_rate), int(segment.channels), segment.sample_width


def _pcm_bytes(interleaved: npt.NDArray[np.float64], width: int) -> bytes:
    """Pack *interleaved* float samples as integer PCM of *width* bytes.

    pydub passes the segment's raw bytes straight to FFmpeg, so the packing
    must match the width it is told about; a 3-byte (24-bit) sample is written
    as three little-endian bytes, which is the layout pydub itself uses.
    """
    scale = float((1 << (8 * width - 1)) - 1)
    clipped = np.clip(interleaved, -1.0, 1.0)
    if width == 3:
        wide = np.round(clipped * scale).astype(np.int32)
        packed: bytes = (
            wide.astype("<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()
        )
        return packed
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}[width]
    whole: bytes = np.round(clipped * scale).astype(dtype).tobytes()
    return whole


def _write(
    result: TimePitchResult,
    *,
    source: Path,
    destination: Path,
    sample_rate: int,
    channels: int,
    sample_width: int,
) -> None:
    """Encode the render to *destination*, keeping the source's own stream shape."""
    audio = np.asarray(result.audio, dtype=np.float64)
    interleaved = audio if audio.ndim == 1 else audio.T.reshape(-1)
    segment = AudioSegment(
        data=_pcm_bytes(interleaved, sample_width),
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels,
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    export_segment(segment, destination, str(source))


def _transform(
    signal: npt.NDArray[np.float32], settings: PitchTimeSettings, sample_rate: int
) -> TimePitchResult:
    """Apply the setting's one transform to a decoded signal."""
    if settings.mode == MODE_PITCH:
        return pitch_shift(signal, settings.semitones, sample_rate=sample_rate)
    return time_stretch(signal, settings.rate, sample_rate=sample_rate)


def process_file(
    source: Path, settings: PitchTimeSettings, *, dry_run: bool = False
) -> FileOutcome:
    """Process one file and report both measured lengths.

    Args:
        source: The file to read.
        settings: The run's settings.
        dry_run: Measure the render but write neither audio nor tags.

    Returns:
        The outcome, including the path written (or that a dry run would write).

    Raises:
        AudioSuiteError: The file cannot be decoded or the container has no
            writable export path.
        OSError: The file cannot be read or written.
    """
    signal, sample_rate, channels, sample_width = _decode(source)
    result = _transform(signal, settings, sample_rate)
    destination = output_path_for(source, settings)
    if dry_run:
        return FileOutcome(
            source=source,
            output=destination,
            original_seconds=result.original_seconds,
            processed_seconds=result.processed_seconds,
            written=False,
        )
    _write(
        result,
        source=source,
        destination=destination,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )
    copy_easy_tags(source, destination)
    return FileOutcome(
        source=source,
        output=destination,
        original_seconds=result.original_seconds,
        processed_seconds=result.processed_seconds,
        written=True,
    )


def _report_lines(
    folder: Path,
    settings: PitchTimeSettings,
    body: list[str],
    *,
    dry_run: bool,
    written: int,
    skipped: int,
    errors: int,
    elapsed: float,
) -> list[str]:
    """Build the run report's lines, in the suite's documented shape."""
    header = [
        "PITCH / TIME REPORT\n",
        f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
        f"Folder: {folder}\n",
        f"Setting: {settings.description}\n",
        "=" * 60 + "\n",
    ]
    summary = [
        "\n" + "=" * 60 + "\n",
        "SUMMARY:\n",
        f"Files: {written + skipped + errors}\n",
        f"Written: {written}\n",
        f"Skipped: {skipped}\n",
        f"Errors: {errors}\n",
        f"Time: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}\n",
    ]
    return [*header, *body, *summary]


def discover(directory: Path) -> list[Path]:
    """Return the folder's processable audio files, sorted by name.

    A read-only container (``.ape``, ``.mpc``, ``.dsf``) is discovered and then
    skipped by the run with its reason, rather than dropped silently.
    """
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in INPUT_EXTENSIONS
    )


def run_pitch_time(
    directory: str,
    *,
    settings: PitchTimeSettings | None = None,
    dry_run: bool = False,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
    **_ignored: Any,
) -> None:
    """Process one folder through the setting's transform.

    Args:
        directory: Folder holding the files.
        settings: The run's settings; the model's defaults when omitted.
        dry_run: Measure and report, but write neither audio nor tags.
        on_progress: Called per file with ``processed``/``total``/``skipped``/
            ``errors``/``display_text``.
        on_complete: Called once with the run's counters, ``written`` and the
            setting it applied.
        on_error: Called with one message when no run can start at all.

    The report is written beside the files and a failed write is logged, never
    raised: by then the audio work has already happened.
    """
    folder = Path(directory)
    active = settings or PitchTimeSettings()
    started = time.monotonic()
    if on_error is None:
        on_error = lambda _message: None  # noqa: E731 - a no-op default seam
    if not folder.is_dir():
        on_error(f"The folder {directory!r} does not exist.")
        return
    files = discover(folder)
    if not files:
        on_error(
            f"The folder {folder} holds no supported audio files "
            f"({', '.join(INPUT_EXTENSIONS[:4])}, ...)."
        )
        return

    body: list[str] = []
    written = skipped = errors = 0
    for index, source in enumerate(files, start=1):
        if is_read_only_extension(source.name):
            skipped += 1
            body.append(f"{source.resolve()}  SKIPPED (read-only container)\n")
        elif active.is_neutral:
            skipped += 1
            body.append(
                f"{source.resolve()}  SKIPPED (no change requested: "
                f"{active.description})\n"
            )
        else:
            try:
                outcome = process_file(source, active, dry_run=dry_run)
            except (AudioSuiteError, OSError, ValueError) as exc:
                errors += 1
                message = getattr(exc, "message", None) or str(exc)
                body.append(f"{source.resolve()}  ERROR  {message}\n")
            else:
                written += 1 if outcome.written else 0
                verb = "would write" if dry_run else "wrote"
                body.append(
                    f"{source.resolve()}  {outcome.original_seconds:.3f} s -> "
                    f"{outcome.processed_seconds:.3f} s  {verb} "
                    f"{outcome.output.name}\n"
                )
        if on_progress is not None:
            on_progress(
                processed=index,
                total=len(files),
                skipped=skipped,
                errors=errors,
                display_text=f"{source.name}",
            )

    elapsed = time.monotonic() - started
    report_path = folder / REPORT_NAMES[dry_run]
    lines = _report_lines(
        folder,
        active,
        body,
        dry_run=dry_run,
        written=written,
        skipped=skipped,
        errors=errors,
        elapsed=elapsed,
    )
    try:
        report_path.write_text("".join(lines), encoding="utf-8")
    except OSError:  # pragma: no cover - depends on the folder's permissions
        logger.error("Could not write the run report", exc_info=True)

    if on_complete is not None:
        on_complete(
            total=len(files),
            processed=len(files),
            skipped=skipped,
            errors=errors,
            duration_secs=elapsed,
            log_entries=[line.rstrip("\n") for line in body],
            written=written,
            mode=active.mode,
            rate=active.rate,
            semitones=active.semitones,
            report=str(report_path),
        )
