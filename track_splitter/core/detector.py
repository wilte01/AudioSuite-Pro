"""detector.py — find silent runs with FFmpeg's ``silencedetect`` filter.

The detector runs FFmpeg once per file with ``-af silencedetect`` and parses the
filter's own report from stderr, so the thresholds are FFmpeg's documented
semantics (``noise`` is a level relative to full scale, ``d`` a minimum run
length) rather than a re-invented envelope follower.  :func:`parse_gaps` is
pure, so the parser is tested against recorded output without spawning
anything.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

import re
from pathlib import Path

from audio_suite_shared import audio_probe
from audio_suite_shared.constants import WORKER_TIMEOUT_SECS
from audio_suite_shared.exceptions import AudioExternalToolError
from audio_suite_shared.secure_subprocess import run_secure_subprocess

from .models import Gap, SplitSettings

_EVENT = re.compile(r"silence_(start|end):\s*(-?\d+(?:\.\d+)?)")


def parse_gaps(report: str, total_ms: int) -> list[Gap]:
    """Turn an FFmpeg ``silencedetect`` report into gap runs.

    Args:
        report: FFmpeg's stderr text.
        total_ms: The file's length, used for a silent tail the filter leaves
            open (FFmpeg prints ``silence_end`` only when audio follows the
            run).

    Returns:
        The silent runs, in file order, in whole milliseconds.  Empty runs and
        runs outside the file are dropped.
    """
    gaps: list[Gap] = []
    open_start: int | None = None
    for match in _EVENT.finditer(report):
        position = int(round(max(float(match.group(2)), 0.0) * 1000.0))
        if match.group(1) == "start":
            open_start = position
            continue
        if open_start is None:
            continue
        gaps.append(Gap(start_ms=open_start, end_ms=min(position, total_ms)))
        open_start = None
    if open_start is not None and open_start < total_ms:
        gaps.append(Gap(start_ms=open_start, end_ms=total_ms))
    return [gap for gap in gaps if gap.duration_ms > 0]


def detect_gaps(
    source: Path,
    settings: SplitSettings,
    *,
    total_ms: int | None = None,
) -> list[Gap]:
    """Detect the silent runs inside *source*.

    Args:
        source: File to analyse.
        settings: Supplies ``silence_db`` and ``min_silence_ms``.
        total_ms: The file's length when the caller already measured it; when
            omitted it is probed here.

    Returns:
        The silent runs, in file order.

    Raises:
        AudioFormatError: The file cannot be probed.
        AudioExternalToolError: FFmpeg could not run, or wrote an unreadable
            report (a file FFmpeg cannot decode).
    """
    from audio_normalizer.utils.ffmpeg_finder import FFMPEG_PATH

    length_ms = (
        total_ms
        if total_ms is not None
        else int(round(audio_probe.probe_stream(str(source)).duration_sec * 1000.0))
    )
    filter_spec = (
        f"silencedetect=noise={settings.silence_db:g}dB:"
        f"d={settings.min_silence_ms / 1000:.3f}"
    )
    proc = run_secure_subprocess(
        FFMPEG_PATH,
        [
            "-hide_banner",
            "-nostats",
            "-nostdin",
            "-i",
            str(source),
            "-af",
            filter_spec,
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        check=False,
        timeout=WORKER_TIMEOUT_SECS,
    )
    report = f"{proc.stderr or ''}{proc.stdout or ''}"
    if proc.returncode != 0 and "silence_" not in report:
        raise AudioExternalToolError(
            f"FFmpeg could not analyse {source.name!r} for silent gaps.",
            tool=FFMPEG_PATH,
            returncode=proc.returncode,
            stderr=(proc.stderr or "").strip() or None,
        )
    return parse_gaps(report, length_ms)
