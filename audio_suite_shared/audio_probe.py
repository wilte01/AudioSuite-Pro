"""audio_probe.py — the suite's one FFmpeg measurement path.

Changed in 2.4.2: new module (``PLAN_2026-11-03_2.4.2_audio_foundation.md``
WP-5.1, extended in WP-5.2).  ReplayGain and the Audio Normalizer both measure
through it now - the second needs ``loudnorm``'s raw input figures, which is
what :func:`loudnorm_inputs` exposes - and F-E1/F-S7 consume it rather than
adding a seventh FFmpeg measurement path.

Changed in 2.7.0: ``declared_depth`` is annotated ``Any`` rather than left
inferred.  ``audio.get(...) or audio.get(...)`` infers ``Any | None``, which
``--strict`` refuses to hand to ``int()``; the annotation states what the value
truly is - unvalidated ffprobe JSON - instead of narrowing it, so the runtime
behaviour and the ``in (None, "", "0")`` guard are unchanged.

Why one module
--------------
Six independent FFmpeg measurement implementations had grown up beside each
other (ReplayGain's ``ffmpeg_metrics``, the Refinery's ``measure``, the
Normalizer's ``loudness``, the Enhancer's ``ffmpeg_io``, the converter's
``ffmpeg_params`` and ``lossless_gain``).  Each owned its own argument list and
its own stderr parsing, so "what does this file measure?" depended on which tool
asked.  This module owns the answer: one chain per question, parsed once.

Decode policy
-------------
* Every subprocess runs through
  :func:`audio_suite_shared.secure_subprocess.run_secure_subprocess` — the
  executable allowlist, the argument validation and the timeout live there.
  This module imports ``subprocess`` only for its exception and result types.
* Stream metadata comes from ``ffprobe``; audio is decoded by
  ``ffmpeg -f null -``.  No ``pydub`` in the probe path: a decoded
  ``AudioSegment`` would put a second decode and a second sample-format
  conversion between the file and the number.
* Sample rates are not silently converted.  A caller that wants 48 kHz states
  it; the probe measures the file as it is.
* Bit depth is reported for integer-PCM and lossless streams only.  A lossy
  decoder's "bits per sample" describes its internal buffer, not the file.
* A container with no readable row in
  :data:`audio_suite_shared.audio_formats.FORMAT_MATRIX` is refused before any
  FFmpeg process starts, so a probe never "succeeds" on something the suite
  cannot read.  Read-only containers (``.ape``, ``.mpc``, ``.dsf``) *are*
  readable and are measured: the matrix advertises them as inputs, and refusing
  them here would silently drop analysis ReplayGain performs today.  The write
  refusal stays at the write seam (``audio_formats.get_export_args``).
* A non-finite reading (FFmpeg prints ``-inf`` for digital silence) is reported
  as an absent measurement rather than a number, because a fabricated ``0.0``
  LUFS would be tagged onto a file.
* No cache.  A measurement is one decode of one file; a caller that needs the
  same stream described twice in one batch passes the values along.  An
  unbounded module-level cache would keep file handles' worth of state alive
  for the life of a GUI process.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Any

from .audio_formats import FORMAT_MATRIX
from .constants import WORKER_TIMEOUT_SECS
from .exceptions import AudioExternalToolError, AudioFormatError
from .secure_subprocess import run_secure_subprocess

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Executable names resolved through ``PATH``.  A caller that ships its own
#: binary beside its package (ReplayGain's legacy ``ffmpeg.exe``) passes the
#: resolved path in, so the probe never guesses which one is meant.
FFMPEG_EXECUTABLE = "ffmpeg"
FFPROBE_EXECUTABLE = "ffprobe"

#: The input length FFmpeg prints once per input, in its banner.
_DURATION_RE = re.compile(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)")

#: The ``ebur128`` summary, anchored at line start.  The filter also prints one
#: progress line per 100 ms prefixed with ``[Parsed_ebur128_0 @ ...]``; those
#: carry ``I:`` and ``LRA:`` fields too, and only the summary is authoritative.
_INTEGRATED_RE = re.compile(r"^\s*I:\s+([-+]?\d+(?:\.\d+)?)\s+LUFS", re.MULTILINE)
_THRESHOLD_RE = re.compile(
    r"^\s*Threshold:\s+([-+]?\d+(?:\.\d+)?)\s+LUFS", re.MULTILINE
)
_LRA_RE = re.compile(r"^\s*LRA:\s+([-+]?\d+(?:\.\d+)?)\s+LU", re.MULTILINE)
_TRUE_PEAK_RE = re.compile(r"^\s*Peak:\s+([-+]?\d+(?:\.\d+)?)\s+dBFS", re.MULTILINE)

#: ``astats`` prints a per-channel block and then one overall block; the overall
#: figures are the file's, and are found by splitting on this marker.
_ASTATS_OVERALL_MARKER = "] Overall"
_ASTATS_PEAK_RE = re.compile(r"Peak level dB:\s+([-+]?\d+(?:\.\d+)?)")
_ASTATS_RMS_RE = re.compile(r"RMS level dB:\s+([-+]?\d+(?:\.\d+)?)")

#: The one filter chain this suite uses to read EBU R128 loudness.
_EBUR128_CHAIN = "ebur128=peak=true"


@dataclass(frozen=True)
class StreamInfo:
    """What one ``ffprobe`` call says about a file's audio stream.

    Attributes:
        container: ``format_name`` as FFmpeg reports it (``wav``, ``mp3``).
        codec: The audio stream's codec name (``pcm_s16le``, ``flac``).
        sample_rate: Sample rate in Hz.
        channels: Channel count.
        bit_depth: Bits per sample, for integer-PCM and lossless streams only;
            ``None`` for lossy codecs, whose decoder buffer size is not the
            file's depth.
        duration_sec: Stream length in seconds.
        bitrate_kbps: Container bitrate in kbit/s, ``0`` when unreported.
    """

    container: str
    codec: str
    sample_rate: int
    channels: int
    bit_depth: int | None
    duration_sec: float
    bitrate_kbps: int


@dataclass(frozen=True)
class LevelMetrics:
    """Peak and crest figures for one file.

    Attributes:
        sample_peak_dbfs: The loudest decoded sample, in dBFS.
        true_peak_dbtp: The oversampled peak, in dBFS units as FFmpeg reports
            it (the ``ebur128`` true-peak figure).
        crest_factor_db: ``sample_peak_dbfs - RMS level``, the headroom between
            the average and the peak level.
    """

    sample_peak_dbfs: float
    true_peak_dbtp: float
    crest_factor_db: float


@dataclass(frozen=True)
class LoudnessMetrics:
    """EBU R128 measurements for one file or one album.

    Attributes:
        integrated_lufs: Gated integrated loudness.  Always present for a
            successful measurement — a file FFmpeg cannot gate raises instead,
            because an absent loudness is not ``0.0`` LUFS.
        loudness_range_lu: Loudness range in LU, or ``None`` when FFmpeg
            printed no range (a stream too short to gate).
        true_peak_dbtp: Oversampled peak in dBFS units, or ``None`` when
            FFmpeg printed none.
        threshold_lufs: The integrated measurement's relative gate, or ``None``.
        duration_sec: The input duration read from the same pass's banner (or
            one ``ffprobe`` call when the banner omitted it), or ``None``.  It
            is part of this result so a caller needs one decode, not two.
    """

    integrated_lufs: float
    loudness_range_lu: float | None
    true_peak_dbtp: float | None
    threshold_lufs: float | None
    duration_sec: float | None


def _file_name(path: str) -> str:
    """Return the file's display name for messages."""
    return os.path.basename(path) or path


def _require_readable(path: str) -> None:
    """Refuse a container the capability matrix cannot read.

    Args:
        path: Path about to be probed.

    Raises:
        AudioFormatError: The extension has no readable row in
            :data:`audio_suite_shared.audio_formats.FORMAT_MATRIX`.
    """
    extension = os.path.splitext(path)[1].lower()
    capability = FORMAT_MATRIX.get(extension)
    if capability is not None and capability.readable:
        return
    nominated = extension or "no extension"
    raise AudioFormatError(
        f"'{_file_name(path)}' is not a container the suite can read: "
        f"{nominated} has no readable row in the capability matrix.",
        context={"file": path, "extension": extension},
    )


def _run(
    executable: str, args: list[str], *, path: str
) -> subprocess.CompletedProcess[str]:
    """Run one FFmpeg-family command through the secure wrapper.

    Args:
        executable: Executable name, already resolved by the caller.
        args: Arguments, without the executable.
        path: The audio file being measured, for messages.

    Returns:
        The completed process, with ``stdout``/``stderr`` decoded as text.

    Raises:
        AudioExternalToolError: The executable is missing, timed out, or could
            not be run at all.
        SubprocessSecurityError: The wrapper refused the executable or an
            argument.
    """
    try:
        result: subprocess.CompletedProcess[str] = run_secure_subprocess(
            executable,
            args,
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            timeout=WORKER_TIMEOUT_SECS,
            check=False,
            log_failure=False,
        )
    except FileNotFoundError as exc:
        raise AudioExternalToolError(
            f"'{executable}' was not found on PATH.",
            tool=executable,
            original=exc,
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioExternalToolError(
            f"'{executable}' timed out measuring '{_file_name(path)}'.",
            tool=executable,
            original=exc,
        ) from exc
    except (OSError, ValueError) as exc:
        raise AudioExternalToolError(
            f"'{executable}' could not measure '{_file_name(path)}': {exc}",
            tool=executable,
            original=exc,
        ) from exc
    return result


def _duration_from_banner(stderr: str) -> float | None:
    """Read the input duration FFmpeg printed in its banner.

    Args:
        stderr: FFmpeg's stderr.

    Returns:
        The duration in seconds, or ``None`` when the banner carried none.
    """
    match = _DURATION_RE.search(stderr)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _probe_duration_seconds(path: str) -> float | None:
    """Ask ``ffprobe`` for the container duration.

    Only reached when the input banner carried no ``Duration:`` line — a pipe
    or an unusual container.  A probe failure is ``None``, never a guessed
    length: album gain is duration-weighted, so a wrong length is a wrong tag.

    Args:
        path: Path to the audio file.

    Returns:
        The duration in seconds, or ``None``.
    """
    try:
        result = _run(
            FFPROBE_EXECUTABLE,
            [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                os.path.normpath(path),
            ],
            path=path,
        )
    except AudioExternalToolError as exc:
        logger.warning("Could not read the duration of %s: %s", path, exc)
        return None
    text = (result.stdout or "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        logger.warning("FFprobe reported a non-numeric duration for %s", path)
        return None


def _duration_seconds(stderr: str, path: str) -> float | None:
    """Return the input duration from the banner, or from one ffprobe call.

    Args:
        stderr: FFmpeg's stderr from the measurement pass.
        path: The measured file.

    Returns:
        The duration in seconds, or ``None`` when neither source reports it.
    """
    duration = _duration_from_banner(stderr)
    if duration is None:
        duration = _probe_duration_seconds(path)
    return duration


def _last_float(pattern: re.Pattern[str], text: str) -> float | None:
    """Return the last value *pattern* captured, or ``None``."""
    matches = pattern.findall(text)
    return float(matches[-1]) if matches else None


def _first_float(pattern: re.Pattern[str], text: str) -> float | None:
    """Return the first value *pattern* captured, or ``None``."""
    matches = pattern.findall(text)
    return float(matches[0]) if matches else None


def _concat_list_line(path: str) -> str:
    """Format one FFmpeg concat-demuxer ``file`` directive.

    Args:
        path: Absolute path to an audio file.

    Returns:
        One ``file '<path>'`` line, newline-terminated.  Paths use forward
        slashes so the directive is identical on Windows and POSIX hosts.
    """
    escaped = os.path.normpath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _reports_bit_depth(path: str, codec: str) -> bool:
    """Return whether a stream's declared sample size describes the file.

    A lossy decoder reports the size of its internal buffer, which is not the
    source's bit depth; only integer-PCM and lossless containers are trusted.

    Args:
        path: The file being probed, for its matrix row.
        codec: The stream's codec name.

    Returns:
        True when the declared figure describes the file.
    """
    if codec.startswith("pcm_"):
        return True
    row = FORMAT_MATRIX.get(os.path.splitext(path)[1].lower())
    return bool(row is not None and row.lossless)


def probe_stream(path: str, *, ffprobe: str | None = None) -> StreamInfo:
    """Describe a file's audio stream with one ``ffprobe`` call.

    Args:
        path: Path to the audio file.
        ffprobe: Executable to use; defaults to ``ffprobe`` on ``PATH``.

    Returns:
        The stream description.

    Raises:
        AudioFormatError: The container is not readable, has no audio stream,
            or FFprobe returned an unparseable description.
        AudioExternalToolError: FFprobe could not be run.
    """
    _require_readable(path)
    executable = ffprobe or FFPROBE_EXECUTABLE
    result = _run(
        executable,
        [
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-print_format",
            "json",
            os.path.normpath(path),
        ],
        path=path,
    )

    payload = (result.stdout or "").strip()
    try:
        described: Any = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AudioFormatError(
            f"FFprobe returned no readable stream description for "
            f"'{_file_name(path)}'.",
            context={"file": path},
            original=exc,
        ) from exc

    streams = described.get("streams") or [] if isinstance(described, dict) else []
    audio = next(
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == "audio"
        ),
        None,
    )
    if audio is None:
        raise AudioFormatError(
            f"'{_file_name(path)}' has no audio stream.",
            context={"file": path},
        )

    container_info = described.get("format") or {}
    container = str(container_info.get("format_name", ""))
    codec = str(audio.get("codec_name", ""))

    declared_depth: Any = audio.get("bits_per_raw_sample") or audio.get(
        "bits_per_sample"
    )
    bit_depth: int | None = None
    if declared_depth not in (None, "", "0"):
        try:
            depth = int(declared_depth)
        except (TypeError, ValueError):
            depth = 0
        if depth > 0 and _reports_bit_depth(path, codec):
            bit_depth = depth

    duration = container_info.get("duration") or audio.get("duration")
    if duration is None:
        raise AudioFormatError(
            f"'{_file_name(path)}' reports no duration.",
            context={"file": path},
        )
    bitrate = container_info.get("bit_rate") or 0
    try:
        bitrate_kbps = int(bitrate) // 1000
    except (TypeError, ValueError):
        bitrate_kbps = 0

    return StreamInfo(
        container=container,
        codec=codec,
        sample_rate=int(audio.get("sample_rate") or 0),
        channels=int(audio.get("channels") or 0),
        bit_depth=bit_depth,
        duration_sec=float(duration),
        bitrate_kbps=bitrate_kbps,
    )


def measure_levels(path: str, *, ffmpeg: str | None = None) -> LevelMetrics:
    """Measure a file's sample peak, true peak and crest factor.

    Args:
        path: Path to the audio file.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The level figures.

    Raises:
        AudioFormatError: The container is not readable, or FFmpeg printed no
            level summary for it.
        AudioExternalToolError: FFmpeg could not be run.
    """
    _require_readable(path)
    executable = ffmpeg or FFMPEG_EXECUTABLE
    result = _run(
        executable,
        [
            "-hide_banner",
            "-i",
            os.path.normpath(path),
            "-af",
            f"{_EBUR128_CHAIN},astats=metadata=1:reset=0",
            "-f",
            "null",
            "-",
        ],
        path=path,
    )
    stderr = result.stderr or ""

    sections = stderr.split(_ASTATS_OVERALL_MARKER, 1)
    if len(sections) < 2:
        raise AudioFormatError(
            f"FFmpeg printed no level summary for '{_file_name(path)}'.",
            context={"file": path, "returncode": result.returncode},
        )
    overall = sections[1]
    sample_peak = _last_float(_ASTATS_PEAK_RE, overall)
    rms = _last_float(_ASTATS_RMS_RE, overall)
    if sample_peak is None or rms is None:
        raise AudioFormatError(
            f"FFmpeg printed an incomplete level summary for '{_file_name(path)}'.",
            context={"file": path, "returncode": result.returncode},
        )
    true_peak = _last_float(_TRUE_PEAK_RE, stderr)
    return LevelMetrics(
        sample_peak_dbfs=sample_peak,
        true_peak_dbtp=true_peak if true_peak is not None else sample_peak,
        crest_factor_db=sample_peak - rms,
    )


def measure_loudness(
    path: str,
    *,
    target: float | None = None,
    true_peak: float = -1.5,
    lra: float = 11,
    ffmpeg: str | None = None,
) -> LoudnessMetrics:
    """Measure one file's EBU R128 loudness.

    Two filter chains, one question.  ``target=None`` uses ``ebur128`` — the
    chain ReplayGain has always used, which needs no target to *measure*.
    Passing ``target`` uses the ``loudnorm`` analysis pass instead, because that
    filter cannot report its input figures without a target; it is the chain the
    Audio Normalizer runs, and its ``input_i`` is what that tool calls the
    file's loudness.

    Args:
        path: Path to the audio file.
        target: Integrated-loudness target for the ``loudnorm`` chain, or
            ``None`` to measure with ``ebur128``.
        true_peak: True-peak ceiling for the ``loudnorm`` chain.
        lra: Loudness-range target for the ``loudnorm`` chain.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The measurements, including the duration read from the same pass.

    Raises:
        AudioFormatError: The container is not readable, or FFmpeg printed no
            integrated loudness for it.
        AudioExternalToolError: FFmpeg could not be run.
    """
    _require_readable(path)
    if target is None:
        chain = _EBUR128_CHAIN
    else:
        chain = _loudnorm_chain(target, true_peak, lra)

    result = _filter_pass(path, chain, ffmpeg)
    stderr = result.stderr or ""
    duration = _duration_seconds(stderr, path)

    if target is None:
        integrated = _last_float(_INTEGRATED_RE, stderr)
        if integrated is None:
            raise AudioFormatError(
                f"FFmpeg printed no integrated loudness for '{_file_name(path)}'.",
                context={"file": path, "returncode": result.returncode},
            )
        return LoudnessMetrics(
            integrated_lufs=integrated,
            loudness_range_lu=_first_float(_LRA_RE, stderr),
            true_peak_dbtp=_last_float(_TRUE_PEAK_RE, stderr),
            threshold_lufs=_first_float(_THRESHOLD_RE, stderr),
            duration_sec=duration,
        )

    figures = _loudnorm_figures(stderr)
    integrated = figures.get("input_i") if figures is not None else None
    if figures is None or integrated is None:
        raise AudioFormatError(
            f"FFmpeg printed no loudnorm analysis for '{_file_name(path)}'.",
            context={"file": path, "returncode": result.returncode},
        )
    return LoudnessMetrics(
        integrated_lufs=integrated,
        loudness_range_lu=figures.get("input_lra"),
        true_peak_dbtp=figures.get("input_tp"),
        threshold_lufs=figures.get("input_thresh"),
        duration_sec=duration,
    )


def _loudnorm_figures(stderr: str) -> dict[str, float | None] | None:
    """Read the ``loudnorm`` analysis block from FFmpeg's stderr.

    FFmpeg prints several ``{...}`` blocks (stream info, metadata) before the
    analysis, so the last block carrying ``input_i`` is the measurement.

    Args:
        stderr: FFmpeg's stderr from the analysis pass.

    Returns:
        The input figures, or ``None`` when no analysis block was printed.
    """
    for block in reversed(re.findall(r"\{[^{}]*\}", stderr)):
        try:
            parsed: Any = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(parsed, dict) or "input_i" not in parsed:
            continue
        return {
            "input_i": _finite_or_none(parsed.get("input_i")),
            "input_tp": _finite_or_none(parsed.get("input_tp")),
            "input_lra": _finite_or_none(parsed.get("input_lra")),
            "input_thresh": _finite_or_none(parsed.get("input_thresh")),
            "target_offset": _finite_or_none(parsed.get("target_offset")),
        }
    return None


def _finite_or_none(value: Any) -> float | None:
    """Convert a JSON figure, treating ``-inf``/``inf``/``nan`` as absent.

    ``loudnorm`` reports digital silence as ``-inf``; a caller that received
    that as a number could tag it or normalise against it.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


#: What a peak FFmpeg printed as ``-inf`` becomes.  A digital-silence pass
#: reports no measurable peak; the normaliser has always published the floor
#: for that case, and changing a shipped report value is not this migration's
#: business.
_LOUDNORM_PEAK_FLOOR_DB = -70.0

#: ``loudnorm``'s second-pass summary prints this line on current FFmpeg; some
#: builds print the figure as a JSON ``output_tp`` instead.
_OUTPUT_TRUE_PEAK_RE = re.compile(
    r"Output True Peak:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dBTP"
)


def _loudnorm_chain(target: float, true_peak: float, lra: float) -> str:
    """Return the ``loudnorm`` analysis chain for these targets."""
    return f"loudnorm=I={target}:TP={true_peak}:LRA={lra}:print_format=json"


def _filter_pass(
    path: str, chain: str, ffmpeg: str | None
) -> subprocess.CompletedProcess[str]:
    """Decode one file through one filter chain and return the process.

    Args:
        path: Path to the audio file.
        chain: The ``-af`` filtergraph.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The completed process; a measurement reads its stderr.
    """
    return _run(
        ffmpeg or FFMPEG_EXECUTABLE,
        [
            "-hide_banner",
            "-i",
            os.path.normpath(path),
            "-af",
            chain,
            "-f",
            "null",
            "-",
        ],
        path=path,
    )


def loudnorm_inputs(
    path: str,
    *,
    target: float,
    true_peak: float = -1.5,
    lra: float = 11,
    ffmpeg: str | None = None,
) -> dict[str, float | None] | None:
    """Read the ``loudnorm`` analysis block for one file.

    This is the raw figures, keyed as FFmpeg prints them (``input_i``,
    ``input_tp``, ``input_lra``, ``input_thresh``, ``target_offset``), because
    the Audio Normalizer feeds every one of them into its second pass.  A
    non-finite figure is ``None``; the whole result is ``None`` when FFmpeg
    printed no analysis block at all.

    :func:`measure_loudness` is the same pass with an error contract applied
    (a file it cannot measure raises): this entry point is for a caller that
    has a defined answer for an absent figure, which is what the normaliser's
    floor defaults are.

    Args:
        path: Path to the audio file.
        target: Integrated-loudness target for the analysis.
        true_peak: True-peak ceiling for the analysis.
        lra: Loudness-range target for the analysis.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The input figures, or ``None`` when no analysis block was printed.

    Raises:
        AudioFormatError: The container is not readable.
        AudioExternalToolError: FFmpeg could not be run.
    """
    _require_readable(path)
    result = _filter_pass(path, _loudnorm_chain(target, true_peak, lra), ffmpeg)
    figures = _loudnorm_figures(result.stderr or "")
    if figures is None:
        logger.warning("FFmpeg printed no loudnorm analysis for %s", path)
    return figures


def achieved_true_peak(stderr: str) -> float | None:
    """Read the true peak ``loudnorm``'s second pass reports.

    The second pass runs with ``print_format=summary``, which prints either an
    ``Output True Peak: -1.3 dBTP`` line (current FFmpeg) or a JSON block
    carrying ``output_tp`` (some builds).  Two passes with different ceilings
    can measure the same input, so this figure is the only evidence that the
    requested ceiling was reached and retained.

    Args:
        stderr: FFmpeg's stderr from the encode pass.

    Returns:
        The achieved true peak in dBTP, ``_LOUDNORM_PEAK_FLOOR_DB`` when FFmpeg
        printed a non-finite one, or ``None`` when it printed no output peak.
    """
    if not isinstance(stderr, str):
        return None

    text_match = _OUTPUT_TRUE_PEAK_RE.search(stderr)
    if text_match:
        return _printed_peak(text_match.group(1))

    for block in reversed(re.findall(r"\{[^{}]*\}", stderr)):
        try:
            parsed: Any = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict) and "output_tp" in parsed:
            return _printed_peak(parsed.get("output_tp"))
    return None


def _printed_peak(value: Any) -> float:
    """Return a printed peak, mapping a non-finite one to the floor."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _LOUDNORM_PEAK_FLOOR_DB
    if number != number or number in (float("inf"), float("-inf")):
        return _LOUDNORM_PEAK_FLOOR_DB
    return number


def measure_album_loudness(
    paths: list[str], *, ffmpeg: str | None = None
) -> LoudnessMetrics:
    """Measure a folder's tracks as one combined signal, in a single pass.

    ReplayGain defines album loudness as the integrated loudness of the album's
    combined signal, so the concat demuxer feeds every track through
    ``ebur128`` as one stream.

    Args:
        paths: Absolute paths of the tracks, in album order.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The combined measurements.  ``duration_sec`` is ``None``: the combined
        signal's length is the sum of its parts and is not one track's.

    Raises:
        AudioFormatError: No paths were given, one of them is not readable, or
            FFmpeg printed no combined loudness.
        AudioExternalToolError: FFmpeg could not be run.
    """
    if not paths:
        raise AudioFormatError(
            "An album measurement needs at least one track.",
            context={"paths": []},
        )
    for path in paths:
        _require_readable(path)

    executable = ffmpeg or FFMPEG_EXECUTABLE
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".concat.txt", delete=False, encoding="utf-8"
    )
    try:
        with handle as stream:
            for path in paths:
                stream.write(_concat_list_line(path))
        result = _run(
            executable,
            [
                "-hide_banner",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                handle.name,
                "-af",
                _EBUR128_CHAIN,
                "-f",
                "null",
                "-",
            ],
            path=paths[0],
        )
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass

    stderr = result.stderr or ""
    integrated = _last_float(_INTEGRATED_RE, stderr)
    if integrated is None:
        raise AudioFormatError(
            f"FFmpeg printed no combined album loudness for {len(paths)} track(s).",
            context={"paths": paths, "returncode": result.returncode},
        )
    return LoudnessMetrics(
        integrated_lufs=integrated,
        loudness_range_lu=_first_float(_LRA_RE, stderr),
        true_peak_dbtp=_last_float(_TRUE_PEAK_RE, stderr),
        threshold_lufs=_first_float(_THRESHOLD_RE, stderr),
        duration_sec=None,
    )


def decoded_duration(path: str, *, ffmpeg: str | None = None) -> float:
    """Return a file's duration, measured by decoding it once.

    Args:
        path: Path to the audio file.
        ffmpeg: Executable to use; defaults to ``ffmpeg`` on ``PATH``.

    Returns:
        The duration in seconds.

    Raises:
        AudioFormatError: The container is not readable, or FFmpeg and FFprobe
            both reported no duration.
        AudioExternalToolError: FFmpeg could not be run.
    """
    metrics = measure_loudness(path, ffmpeg=ffmpeg)
    if metrics.duration_sec is None:
        raise AudioFormatError(
            f"FFmpeg reported no duration for '{_file_name(path)}'.",
            context={"file": path},
        )
    return metrics.duration_sec
