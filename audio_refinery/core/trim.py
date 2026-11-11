"""trim.py — exact time-range trimming for the Refinery's Trim stage.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E3).

Two ways to cut a range out of a file
-------------------------------------
The Trim stage used to answer one question: "where does the silence end?"  An
exact range answers a different one - "give me 12.000 s to 30.000 s" - and the
two cannot share a write path, because a stream copy never decodes the audio
the in-memory stage chain works on.

* **Re-encode** (default) slices the decoded segment by millisecond offset, so
  the cut is sample-accurate and the pipeline's single encode writes the depth
  the source had (``audio_formats.preserve_depth_params``).
* **Stream copy** (``copy_mode``) asks FFmpeg to copy the source's own frames,
  starting at ``-ss`` for the requested length.  Nothing is decoded and nothing
  is re-encoded, so the range lands on the container's **frame** boundaries, not
  on the requested millisecond.  :func:`copy_trim` therefore reads the written
  file back with ``ffprobe`` and returns what it actually contains; the stage
  message reports that measured length and the drift, because one the user was
  not told about reads as a bug.

Copy mode is a whole-file operation, so it cannot run beside a stage that must
decode the audio to do its work - see :func:`check_copy_mode`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydub import AudioSegment

from audio_suite_shared import audio_probe
from audio_suite_shared.constants import WORKER_TIMEOUT_SECS
from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.secure_subprocess import run_secure_subprocess

from .models import EXACT_TRIM_MODE, StageConfig, TrimParams

#: Containers whose audio frames can be copied without re-encoding.  A copy on
#: any other container is refused rather than silently re-encoded: WAV/AIFF and
#: the read-only formats keep the re-encode path, and the message says so.
COPY_EXTENSIONS: tuple[str, ...] = (".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus")


@dataclass(frozen=True)
class ExactRange:
    """A resolved, validated millisecond range within one file.

    Attributes:
        start_ms: First kept millisecond.
        end_ms: First millisecond *after* the kept audio.
        duration_ms: ``end_ms - start_ms``, carried so callers cannot disagree
            about the requested length.
    """

    start_ms: int
    end_ms: int
    duration_ms: int


def _seconds(ms: int) -> str:
    """Render milliseconds as FFmpeg's decimal seconds."""
    return f"{ms / 1000:.3f}"


def resolve_range(params: TrimParams, source_duration_ms: int) -> ExactRange:
    """Validate the configured range against *source_duration_ms*.

    Args:
        params: The Trim stage's parameters; ``end_ms`` and ``duration_ms`` are
            mutually exclusive, and ``start_ms`` defaults to zero.
        source_duration_ms: The length the range is measured against - the
            decoded segment for a re-encode, the probed file for a copy.

    Returns:
        The validated range.

    Raises:
        AudioConfigValueError: No range is configured, both an end and a
            duration are, a value is negative or non-positive, or the range
            runs past the end of the source.
    """
    start = 0 if params.start_ms is None else params.start_ms
    if start < 0:
        raise AudioConfigValueError(
            f"The exact trim start must be zero or later, got {start} ms.",
            context={"start_ms": start},
        )
    if params.end_ms is not None and params.duration_ms is not None:
        raise AudioConfigValueError(
            "Set either the exact trim end or its duration, not both.",
            context={"end_ms": params.end_ms, "duration_ms": params.duration_ms},
        )
    if params.end_ms is None and params.duration_ms is None:
        raise AudioConfigValueError(
            "An exact trim needs an end or a duration to cut to.",
            context={"start_ms": start},
        )

    if params.end_ms is not None:
        end = params.end_ms
        if end <= start:
            raise AudioConfigValueError(
                f"The exact trim end ({end} ms) must be after its start ({start} ms).",
                context={"start_ms": start, "end_ms": end},
            )
        duration = end - start
    else:
        duration = int(params.duration_ms or 0)
        if duration <= 0:
            raise AudioConfigValueError(
                f"The exact trim duration must be positive, got {duration} ms.",
                context={"duration_ms": duration},
            )
        end = start + duration

    # The decode is the authority for a re-encode, and it can be a few
    # milliseconds shorter than the container's declared length.
    if end > source_duration_ms:
        raise AudioConfigValueError(
            f"The exact trim range ends at {end} ms but the audio is only "
            f"{source_duration_ms} ms long.",
            context={"end_ms": end, "source_duration_ms": source_duration_ms},
        )
    return ExactRange(start_ms=start, end_ms=end, duration_ms=duration)


def slice_segment(audio: AudioSegment, exact_range: ExactRange) -> AudioSegment:
    """Return the requested slice of *audio*, sample-accurate.

    ``pydub`` addresses a segment by millisecond, which is the unit the range is
    configured in, so the cut is exact rather than rounded.
    """
    return audio[exact_range.start_ms : exact_range.end_ms]  # noqa: E203


def probe_duration_ms(path: Path) -> float:
    """Return the measured length of *path* in milliseconds.

    Raises:
        AudioFormatError: The file cannot be probed (see
            :func:`audio_suite_shared.audio_probe.probe_stream`).
        AudioExternalToolError: ``ffprobe`` could not be run.
    """
    return audio_probe.probe_stream(str(path)).duration_sec * 1000.0


def check_copy_extension(path: Path) -> None:
    """Refuse a copy mode trim on a container that cannot take one.

    Raises:
        AudioConfigValueError: The extension is outside
            :data:`COPY_EXTENSIONS`.
    """
    ext = path.suffix.lower()
    if ext in COPY_EXTENSIONS:
        return
    supported = ", ".join(COPY_EXTENSIONS)
    raise AudioConfigValueError(
        f"Copy mode cannot cut {ext or 'this file'} without re-encoding it. "
        f"It supports {supported}; turn copy mode off to trim it exactly "
        "with a re-encode.",
        context={"file": str(path), "extension": ext},
    )


def check_copy_mode(config: StageConfig) -> None:
    """Refuse copy mode when another stage has to decode the audio.

    A stream copy writes the source's own frames, so no stage that works on
    decoded samples can run in the same pass.  Refusing before the first file is
    touched is the only honest outcome: silently dropping the other stages, or
    silently re-encoding and calling it a copy, would both misreport the run.

    Args:
        config: The run's ``StageConfig``.

    Raises:
        AudioConfigValueError: Copy mode is requested beside a decoding stage.
    """
    trim_params = config.trim_params
    if trim_params.mode != EXACT_TRIM_MODE or not trim_params.copy_mode:
        return
    decoding = [
        label
        for label, enabled in (
            ("Declick", config.declick),
            ("Noise Reduction", config.reduce_noise),
            # Changed in 2.7.0: the EQ stage renders decoded samples too, so a
            # stream copy beside it would silently drop the rack (F-S1).
            ("EQ", config.eq),
            ("Enhance", config.enhance),
            ("Normalise", config.normalise),
        )
        if enabled
    ]
    if not decoding:
        return
    raise AudioConfigValueError(
        "Copy mode writes the source's own frames, so it cannot run with the "
        f"{', '.join(decoding)} stage enabled. Turn copy mode off to trim with "
        "a re-encode, or disable those stages.",
        context={"stages": decoding},
    )


def copy_trim(source: Path, destination: Path, exact_range: ExactRange) -> float:
    """Cut *exact_range* out of *source* into *destination* without re-encoding.

    Args:
        source: File to read.
        destination: File to write; its extension selects the container, so it
            must be the caller's final extension (a temp file with the same
            suffix is the usual choice).
        exact_range: The validated range to keep.

    Returns:
        The duration ``ffprobe`` measures in the written file, in milliseconds.

    Raises:
        AudioProcessingError: FFmpeg produced no audio for the range.
        AudioFormatError: The written file cannot be probed.
        AudioExternalToolError: FFmpeg or FFprobe could not be run.
    """
    # Changed in 2.5.0: the resolver moved to audio_suite_shared.ffmpeg (D-38).
    from audio_suite_shared.exceptions import AudioProcessingError
    from audio_suite_shared.ffmpeg import FFMPEG_PATH

    run_secure_subprocess(
        FFMPEG_PATH,
        [
            "-hide_banner",
            "-nostdin",
            "-y",
            # Input-side seek: with -c copy FFmpeg starts at the frame that
            # contains the requested time, which is why the result is measured
            # rather than assumed.
            "-ss",
            _seconds(exact_range.start_ms),
            "-i",
            str(source),
            "-t",
            _seconds(exact_range.duration_ms),
            # Every stream (embedded art included) and the container's tags.
            "-map",
            "0",
            "-map_metadata",
            "0",
            "-c",
            "copy",
            str(destination),
        ],
        timeout=WORKER_TIMEOUT_SECS,
    )
    measured = probe_duration_ms(destination)
    if measured <= 0:
        raise AudioProcessingError(
            "FFmpeg wrote no audio for the requested range.",
            context={
                "file": os.path.basename(str(source)),
                "start_ms": exact_range.start_ms,
                "duration_ms": exact_range.duration_ms,
            },
        )
    return measured


def exact_trim_message(
    exact_range: ExactRange, measured_ms: float, *, copy_mode: bool
) -> str:
    """Describe what an exact trim actually produced.

    ``measured_ms`` is the length read back from the output for a copy; a
    re-encode passes the sliced segment's own length.  A copy that lands on the
    next frame boundary says so, with the drift, instead of reporting the
    requested length it did not deliver.
    """
    span = f"{_seconds(exact_range.start_ms)}-{_seconds(exact_range.end_ms)} s"
    if not copy_mode:
        return (
            f"Exact trim to {_seconds(exact_range.duration_ms)} s ({span}), "
            "sample-accurate re-encode"
        )
    drift = measured_ms - exact_range.duration_ms
    kept = f"{measured_ms / 1000:.3f} s"
    if abs(drift) < 1.0:
        return f"Exact trim to {kept} ({span}), frame-accurate stream copy"
    return (
        f"Exact trim to {kept} ({span}), frame-accurate stream copy "
        f"({drift:+.0f} ms of frame rounding)"
    )


def exact_preview_message(exact_range: ExactRange) -> str:
    """Describe an exact trim a Dry Run would perform."""
    span = f"{_seconds(exact_range.start_ms)}-{_seconds(exact_range.end_ms)} s"
    return f"Would trim to {_seconds(exact_range.duration_ms)} s ({span})"
