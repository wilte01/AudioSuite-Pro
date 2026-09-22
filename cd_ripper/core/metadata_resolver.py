"""
metadata_resolver.py  –  Format definitions, metadata construction, and
FFmpeg probing / streaming for CD ripping encoding pipelines.
"""

import logging as _logging
import re
import subprocess
from collections.abc import Callable
from typing import Any

from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_popen,
    run_secure_subprocess,
)

# ── Format definitions ────────────────────────────────────────────────────

FORMAT_OPTIONS = {
    "FLAC": {"ext": "flac", "codec_args": ["-c:a", "flac", "-compression_level", "8"]},
    "MP3": {"ext": "mp3", "codec_args": ["-c:a", "libmp3lame", "-q:a", "0"]},
    "OGG": {"ext": "ogg", "codec_args": ["-c:a", "libvorbis", "-q:a", "6"]},
    "M4A": {"ext": "m4a", "codec_args": ["-c:a", "aac", "-b:a", "256k"]},
    "WAV": {"ext": "wav", "codec_args": ["-c:a", "pcm_s16le"]},
    "Opus": {"ext": "opus", "codec_args": ["-c:a", "libopus", "-b:a", "192k"]},
}

MP3_QUALITY_ARGS = {
    "VBR V0 (best)": ["-c:a", "libmp3lame", "-q:a", "0"],
    "VBR V2": ["-c:a", "libmp3lame", "-q:a", "2"],
    "CBR 320 kbps": ["-c:a", "libmp3lame", "-b:a", "320k"],
    "CBR 256 kbps": ["-c:a", "libmp3lame", "-b:a", "256k"],
    "CBR 192 kbps": ["-c:a", "libmp3lame", "-b:a", "192k"],
}

FLAC_QUALITY_ARGS = {
    "Level 8 (max compression)": ["-c:a", "flac", "-compression_level", "8"],
    "Level 5 (balanced)": ["-c:a", "flac", "-compression_level", "5"],
    "Level 0 (fastest)": ["-c:a", "flac", "-compression_level", "0"],
}

OGG_QUALITY_ARGS = {
    "Quality 10 (highest)": ["-c:a", "libvorbis", "-q:a", "10"],
    "Quality 8 (very high)": ["-c:a", "libvorbis", "-q:a", "8"],
    "Quality 6 (high)": ["-c:a", "libvorbis", "-q:a", "6"],
    "Quality 5 (default)": ["-c:a", "libvorbis", "-q:a", "5"],
    "Quality 3 (medium)": ["-c:a", "libvorbis", "-q:a", "3"],
}

M4A_QUALITY_ARGS = {
    "320 kbps": ["-c:a", "aac", "-b:a", "320k"],
    "256 kbps": ["-c:a", "aac", "-b:a", "256k"],
    "192 kbps": ["-c:a", "aac", "-b:a", "192k"],
    "128 kbps": ["-c:a", "aac", "-b:a", "128k"],
}

OPUS_QUALITY_ARGS = {
    "320 kbps": ["-c:a", "libopus", "-b:a", "320k"],
    "192 kbps": ["-c:a", "libopus", "-b:a", "192k"],
    "128 kbps": ["-c:a", "libopus", "-b:a", "128k"],
    "96 kbps": ["-c:a", "libopus", "-b:a", "96k"],
    "64 kbps": ["-c:a", "libopus", "-b:a", "64k"],
}


# ── Quality option lookup ─────────────────────────────────────────────────


def get_quality_options(fmt: str) -> dict[str, list[str]] | None:
    if fmt == "MP3":
        return MP3_QUALITY_ARGS
    if fmt == "FLAC":
        return FLAC_QUALITY_ARGS
    if fmt == "OGG":
        return OGG_QUALITY_ARGS
    if fmt == "M4A":
        return M4A_QUALITY_ARGS
    if fmt == "Opus":
        return OPUS_QUALITY_ARGS
    return None


# ── Filename sanitisation ─────────────────────────────────────────────────


def _safe_filename(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name).strip()


# ── FFmpeg metadata argument builder ──────────────────────────────────────


def _build_metadata_args(track: dict[str, Any]) -> list[str]:
    args = []
    album_artist = track.get("album_artist", "") or track.get("artist", "")
    for key, val in [
        ("title", track.get("title", "")),
        ("artist", track.get("artist", "")),
        ("album_artist", album_artist),
        ("album", track.get("album", "")),
        ("date", track.get("year", "")),
        ("genre", track.get("genre", "")),
        ("track", str(track.get("number", ""))),
    ]:
        if val:
            args += ["-metadata", f"{key}={val}"]
    return args


# ── FFmpeg probing and streaming ──────────────────────────────────────────


def probe_ffmpeg(ffmpeg_path: str) -> dict[str, str]:
    info = {"version": "unknown"}
    try:
        r = run_secure_subprocess(
            ffmpeg_path, ["-version"], capture_output=True, timeout=10
        )
        for line in r.stdout.splitlines():
            if line.startswith("ffmpeg version"):
                info["version"] = line.split()[2]
                break
    except SubprocessSecurityError as e:
        info["version"] = f"security error: {e}"
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _logging.getLogger(__name__).debug("ffmpeg probe failed: %s", e, exc_info=True)
        info["version"] = f"probe error: {e}"
    return info


def _run_ffmpeg_streaming(
    ffmpeg: str,
    args: list[str],
    duration: float,
    progress_cb: Callable[[int, int, str], None],
    track_num: int,
    cancelled_fn: Callable[[], bool],
) -> tuple[int, str]:
    full_args = ["-y", "-hide_banner"] + args
    stderr_lines = []
    time_re = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
    try:
        proc = run_secure_popen(
            ffmpeg,
            full_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        assert proc.stderr is not None
        for line in proc.stderr:
            line = line.rstrip("\n\r")
            stderr_lines.append(line)
            if cancelled_fn():
                proc.terminate()
                proc.wait()
                return -3, "Cancelled by user"
            m = time_re.search(line)
            if m and duration > 0:
                h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                elapsed = h * 3600 + mn * 60 + s
                pct = min(int(elapsed / duration * 100), 99)
                progress_cb(track_num, pct, f"Encoding\u2026 {pct}%")
        proc.wait()
        return proc.returncode, "\n".join(stderr_lines)
    except SubprocessSecurityError as e:
        return -2, f"Security error: {e}"
    except FileNotFoundError:
        return -1, "FFmpeg executable not found"
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        _logging.getLogger(__name__).error(
            "_run_ffmpeg_streaming unexpected error: %s", e, exc_info=True
        )
        return -1, str(e)
