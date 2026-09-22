"""
core/ffmpeg_io.py
ffmpeg-backed decode/encode for audio formats pedalboard's AudioFile does
not support: Opus (.opus) and AAC/MPEG-4 (.m4a, .mp4).

Why this module exists
----------------------
pedalboard 0.9.23's AudioFile only reads {.wav, .aiff, .aif, .flac, .mp3,
.ogg, .bwf} and only writes {.wav, .aiff, .flac, .mp3, .ogg} (confirmed via
pedalboard.io.get_supported_read_formats()/get_supported_write_formats()).
Neither list includes .opus, .m4a or .mp4, so those formats are decoded to
raw PCM and re-encoded via an ffmpeg subprocess instead. The DSP chain in
processor.py is untouched — it always operates on a NumPy array regardless
of which path produced it.

Known format-specific behaviour (verified empirically, not assumed)
---------------------------------------------------------------------
* Opus: ffmpeg's raw-PCM decode of an Ogg/Opus stream already trims the
  codec's mandatory encoder pre-skip — the decoded sample count matches
  the original source exactly. No trimming needed on decode.
* AAC/M4A/MP4: ffmpeg's raw-PCM decode of an AAC stream does NOT trim the
  encoder's priming delay — it returns MORE samples than the container's
  declared duration (e.g. 128 extra samples for a 1s/48kHz clip in one
  test, 342 extra for a 2.5s/44.1kHz clip in another — the offset is NOT
  a fixed constant and must be computed per file). The true length is
  reliable when read via ffprobe's stream `duration` field; decoded PCM is
  trimmed to round(duration * sample_rate) samples from the START
  (trimming from the front was verified to misalign the signal; trimming
  the tail is correct).
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioFormatError,
    AudioMissingDependencyError,
)
from audio_suite_shared.subprocess_utils import get_startupinfo

logger = logging.getLogger(__name__)

# Extensions handled by this module instead of pedalboard.io.AudioFile.
# .mp4 is handled like .m4a (both MPEG-4 containers with AAC audio) so the
# enhancer/refinery accept the canonical format set end-to-end.
FFMPEG_EXTENSIONS: frozenset[str] = frozenset({".opus", ".m4a", ".mp4"})

# Default encode bitrates (kbps) used when the source bitrate can't be
# determined or falls outside a sane range.
_DEFAULT_OPUS_KBPS: int = 128
_DEFAULT_AAC_KBPS: int = 192
_MIN_KBPS: int = 32
_MAX_OPUS_KBPS: int = 256  # libopus has no real benefit much above this
_MAX_AAC_KBPS: int = 320


def _require_ffmpeg() -> str:
    """Return the path to the ffmpeg binary, or raise if not installed.

    Raises:
        AudioMissingDependencyError: If ffmpeg is not on PATH. Raised here
            explicitly (rather than letting subprocess's FileNotFoundError
            propagate) so it is NOT auto-mapped to AudioFileNotFoundError
            by map_to_audio_error — that mapping is for missing audio
            files, not a missing tool, and file_processor.py treats
            AudioFileNotFoundError as a silent SKIP, which would be
            misleading here (the file is fine; the tool is missing).
    """
    path = shutil.which("ffmpeg")
    if path is None:
        raise AudioMissingDependencyError(
            "ffmpeg is not installed or not on PATH — required for "
            ".opus/.m4a/.mp4 support. Install ffmpeg and ensure it is on PATH.",
            dependency="ffmpeg",
        )
    return path


def _require_ffprobe() -> str:
    """Return the path to the ffprobe binary, or raise if not installed."""
    path = shutil.which("ffprobe")
    if path is None:
        raise AudioMissingDependencyError(
            "ffprobe is not installed or not on PATH — required for "
            ".opus/.m4a/.mp4 support. Install ffmpeg (which includes ffprobe) "
            "and ensure it is on PATH.",
            dependency="ffprobe",
        )
    return path


def _probe_stream(path: Path) -> dict[str, Any]:
    """Return the first audio stream's ffprobe JSON metadata for path.

    Raises:
        AudioMissingDependencyError: If ffprobe is not installed.
        AudioExternalToolError: If ffprobe exits non-zero or returns no
            audio stream.
    """
    ffprobe = _require_ffprobe()
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-select_streams",
        "a:0",
        str(path),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            startupinfo=get_startupinfo(),
        )
    except subprocess.CalledProcessError as exc:
        raise AudioExternalToolError(
            f"ffprobe failed to read {path.name}",
            tool="ffprobe",
            returncode=exc.returncode,
            stderr=exc.stderr,
            original=exc,
        ) from exc

    data = json.loads(proc.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise AudioExternalToolError(
            f"ffprobe found no audio stream in {path.name}",
            tool="ffprobe",
        )
    stream_info: dict[Any, Any] = streams[0]
    return stream_info


def read_audio(path: Path) -> tuple[npt.NDArray[np.float32], int]:
    """Decode an Opus, M4A or MP4 file to a float32 PCM array via ffmpeg.

    Args:
        path: Path to a .opus/.m4a/.mp4 file.

    Returns:
        Tuple of (audio, sample_rate) where audio has shape
        (channels, frames), matching pedalboard.io.AudioFile's convention
        so callers (processor.py) don't need format-specific branching
        beyond choosing which read function to call.

    Raises:
        AudioMissingDependencyError: If ffmpeg/ffprobe is not installed.
        AudioExternalToolError: If ffmpeg/ffprobe fails to decode the file.
    """
    stream = _probe_stream(path)
    sample_rate = int(stream["sample_rate"])
    channels = int(stream["channels"])
    declared_duration = float(stream.get("duration", 0.0))

    ffmpeg = _require_ffmpeg()
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-",
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            startupinfo=get_startupinfo(),
        )
    except subprocess.CalledProcessError as exc:
        raise AudioExternalToolError(
            f"ffmpeg failed to decode {path.name}",
            tool="ffmpeg",
            returncode=exc.returncode,
            stderr=exc.stderr.decode("utf-8", errors="replace") if exc.stderr else None,
            original=exc,
        ) from exc

    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    audio = raw.reshape(-1, channels).T  # (frames, channels) -> (channels, frames)

    # AAC/M4A decode can include trailing encoder-priming samples beyond
    # the container's declared duration (verified: NOT a fixed constant,
    # must be computed per file). Opus decode does not have this problem
    # (verified: raw decode already matches source length exactly), but
    # trimming to the declared duration is a no-op for Opus in that case,
    # so applying it unconditionally for both formats is safe.
    if declared_duration > 0:
        expected_frames = round(declared_duration * sample_rate)
        if 0 < expected_frames < audio.shape[1]:
            audio = audio[:, :expected_frames]

    return audio, sample_rate


def write_audio(
    audio: npt.NDArray[np.float64] | npt.NDArray[np.float32],
    sample_rate: int,
    output_path: Path,
    bitrate_kbps: int = 0,
) -> None:
    """Encode a float PCM array to an Opus or M4A file via ffmpeg.

    Args:
        audio: Array of shape (channels, frames), any float dtype.
        sample_rate: Sample rate in Hz.
        output_path: Destination path; extension (.opus/.m4a/.mp4)
            determines the codec used.
        bitrate_kbps: Target bitrate. If 0 or out of a sane range, a
            format-specific default is used instead.

    Raises:
        AudioMissingDependencyError: If ffmpeg is not installed.
        AudioExternalToolError: If ffmpeg fails to encode.
        ValueError: If output_path's extension is not .opus/.m4a/.mp4.
    """
    suffix = output_path.suffix.lower()
    if suffix not in FFMPEG_EXTENSIONS:
        raise AudioFormatError(
            f"write_audio only supports {sorted(FFMPEG_EXTENSIONS)}, got {suffix!r}"
        )

    channels = audio.shape[0]
    pcm_bytes = np.ascontiguousarray(audio.T.astype(np.float32)).tobytes()

    ffmpeg = _require_ffmpeg()

    if suffix == ".opus":
        kbps = (
            bitrate_kbps
            if _MIN_KBPS <= bitrate_kbps <= _MAX_OPUS_KBPS
            else _DEFAULT_OPUS_KBPS
        )
        codec_args = ["-c:a", "libopus", "-b:a", f"{kbps}k"]
    else:  # .m4a / .mp4 (AAC in an MPEG-4 container)
        kbps = (
            bitrate_kbps
            if _MIN_KBPS <= bitrate_kbps <= _MAX_AAC_KBPS
            else _DEFAULT_AAC_KBPS
        )
        codec_args = ["-c:a", "aac", "-b:a", f"{kbps}k"]

    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "f32le",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-i",
        "-",
        *codec_args,
        str(output_path),
    ]
    try:
        subprocess.run(
            cmd,
            input=pcm_bytes,
            capture_output=True,
            check=True,
            startupinfo=get_startupinfo(),
        )
    except subprocess.CalledProcessError as exc:
        raise AudioExternalToolError(
            f"ffmpeg failed to encode {output_path.name}",
            tool="ffmpeg",
            returncode=exc.returncode,
            stderr=exc.stderr.decode("utf-8", errors="replace") if exc.stderr else None,
            original=exc,
        ) from exc
