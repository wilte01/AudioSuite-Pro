"""album.py — album-mode loudness: one gain for a folder, applied per track.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E1).

Why a plan
----------
Per-file normalisation answers "how loud is *this* track?" and moves it to the
target.  An album is a different question: its loudness is the integrated
loudness of the *combined* signal (ReplayGain's own definition, which
``audio_suite_shared.audio_probe.measure_album_loudness`` already measures for
ReplayGain), and every track then moves by that one gain.  Measuring each track
and normalising it to the target would flatten the album's dynamics — the quiet
interlude and the loud finale would end up equally loud, which is the opposite
of what an album is.

So the plan is built once, for the folder, and consumed per track:

* :func:`build_album_plan` measures the album in one pass and each track's true
  peak, then gives every track the album gain.
* A track whose peak plus that gain would exceed the ceiling gets its *own*
  gain reduced, and is marked ``limited``.  The album's other tracks are never
  touched: silently re-targeting the album to protect one track would change
  the level of every file the user did not ask about.
* An album already within tolerance plans zero gains and says so, which is what
  keeps the Refinery's no-op rule intact — a zero gain writes nothing.

:func:`apply_album_gain` then writes one static gain.  It decodes nothing (the
plan already measured), pins the source's own sample rate and bit depth through
the normaliser's export arguments, and keeps the tags.  When a track is
``limited`` a limiter is inserted rather than a clamp, so the ceiling is held
without distorting the waveform's shape.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from audio_suite_shared import audio_formats, audio_probe
from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.exceptions import AudioFormatError

# Changed in 2.5.0: the resolver moved to audio_suite_shared.ffmpeg (D-38).
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.secure_subprocess import run_secure_subprocess
from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

from .normalizer import _codec_args, _preserve_args

#: A gain this small is not a change.  Writing the file would re-encode it for
#: nothing, and the pipeline's no-op rule is what keeps a re-run byte-identical.
GAIN_EPSILON_DB = 0.01


@dataclass(frozen=True)
class AlbumPlan:
    """One album's loudness decision, for every track in the folder.

    Attributes:
        album_lufs: Integrated loudness of the folder's combined signal.
        target_lufs: The integrated-loudness target the album was planned for.
        true_peak_ceiling: The true-peak ceiling in dBTP every track must hold.
        gains: Planned gain in dB per track, keyed by :func:`plan_key`.
        limited: Whether the ceiling, not the album, decided that track's gain.
        album_true_peak: The combined signal's true peak, when FFmpeg reported
            one; ``None`` when it printed none.
        notes: Human-readable remarks for the run log — a limited track, an
            album already on target, a track with no measurable peak.
    """

    album_lufs: float
    target_lufs: float
    true_peak_ceiling: float
    gains: dict[str, float]
    limited: dict[str, bool]
    album_true_peak: float | None
    notes: tuple[str, ...] = ()


def plan_key(path: str | os.PathLike[str]) -> str:
    """Return the key a plan stores *path* under.

    One spelling for both sides of the plan: ``C:/Music/a.wav`` and
    ``C:\\Music\\a.wav`` must not be two different tracks.
    """
    return os.path.normpath(str(path))


def _track_true_peak(path: str) -> tuple[float | None, str | None]:
    """Measure one track's true peak for the ceiling check.

    Returns:
        ``(peak_dbtp, problem)``.  A track FFmpeg cannot gate (digital silence)
        has no peak to compare, so the ceiling cannot limit it; the reason is
        returned for the plan's notes rather than raised, because one silent
        track must not abort an album.
    """
    try:
        measured = audio_probe.measure_loudness(path, ffmpeg=FFMPEG_PATH)
    except AudioFormatError as exc:
        return None, f"{os.path.basename(path)}: no true peak available ({exc})"
    return measured.true_peak_dbtp, None


def build_album_plan(
    paths: Sequence[str | os.PathLike[str]],
    *,
    target_lufs: float,
    true_peak_ceiling: float = -1.5,
    tolerance: float = 0.5,
) -> AlbumPlan:
    """Measure one folder as an album and decide every track's gain.

    Args:
        paths: The folder's tracks, in album order.
        target_lufs: Integrated-loudness target for the album.
        true_peak_ceiling: True-peak ceiling in dBTP.
        tolerance: A difference this small between the album and the target is
            no adjustment at all, matching the per-file stage's rule.

    Returns:
        The plan.  ``gains`` carries one entry per track and ``limited`` says
        which of those the ceiling decided.

    Raises:
        AudioFormatError: No paths were given, one is unreadable, or the
            combined signal could not be measured.
        AudioExternalToolError: FFmpeg could not be run.
    """
    keys = [plan_key(path) for path in paths]
    album = audio_probe.measure_album_loudness(keys, ffmpeg=FFMPEG_PATH)

    notes: list[str] = []
    if abs(target_lufs - album.integrated_lufs) <= tolerance:
        notes.append(
            f"Album loudness {album.integrated_lufs:.1f} LUFS is already within "
            f"{tolerance:g} LU of the {target_lufs:.1f} LUFS target - "
            "nothing to apply."
        )
        return AlbumPlan(
            album_lufs=album.integrated_lufs,
            target_lufs=target_lufs,
            true_peak_ceiling=true_peak_ceiling,
            gains={key: 0.0 for key in keys},
            limited={key: False for key in keys},
            album_true_peak=album.true_peak_dbtp,
            notes=tuple(notes),
        )

    album_gain = target_lufs - album.integrated_lufs
    gains: dict[str, float] = {}
    limited: dict[str, bool] = {}
    limited_tracks: list[str] = []

    for key in keys:
        peak, problem = _track_true_peak(key)
        if problem is not None:
            notes.append(problem)
        gain = album_gain
        is_limited = False
        if peak is not None and peak + gain > true_peak_ceiling:
            # Only this track's gain moves.  Never the album's.
            gain = true_peak_ceiling - peak
            is_limited = True
            limited_tracks.append(os.path.basename(key))
        gains[key] = gain
        limited[key] = is_limited

    if limited_tracks:
        notes.append(
            f"{len(limited_tracks)} track(s) limited to the "
            f"{true_peak_ceiling:g} dBTP ceiling: {', '.join(limited_tracks)}; "
            "the album gain for the other tracks is unchanged."
        )

    return AlbumPlan(
        album_lufs=album.integrated_lufs,
        target_lufs=target_lufs,
        true_peak_ceiling=true_peak_ceiling,
        gains=gains,
        limited=limited,
        album_true_peak=album.true_peak_dbtp,
        notes=tuple(notes),
    )


def _gain_chain(gain_db: float, *, limit: bool, true_peak_ceiling: float) -> str:
    """Return the ``-af`` chain for one static album gain.

    A limited track gets ``alimiter`` rather than a clamp: the ceiling is held
    by reducing peaks above it, not by flattening every sample at it.
    """
    chain = f"volume={gain_db:.2f}dB"
    if limit:
        linear = 10 ** (true_peak_ceiling / 20.0)
        chain += f",alimiter=limit={linear:.4f}:level=false"
    return chain


def _static_gain_codec(
    file_path: str, *, lossless_output: bool
) -> tuple[str, list[str]]:
    """Resolve the encoder one static-gain rewrite uses.

    Album mode writes through the normaliser's tuned encoders only, so a
    container without one is refused with exactly the message a per-file
    normalise gives.  A peak target is lossless-first and has to reach
    WAV/AIFF, which the normaliser deliberately refuses, so it asks the shared
    format matrix for the container's own PCM encoder rather than adding a
    second codec table here.

    Args:
        file_path: The file being written; only its extension is read.
        lossless_output: Look beyond the normaliser's encoders to the matrix.

    Returns:
        Tuple of FFmpeg codec name and parameter list.

    Raises:
        AudioFormatError: No encoder covers the destination.
    """
    try:
        return _codec_args(file_path)
    except AudioFormatError:
        if not lossless_output:
            raise
        ext = os.path.splitext(file_path)[1]
        return audio_formats.ffmpeg_encoder_args(ext)


def apply_static_gain(
    path: str,
    gain_db: float,
    *,
    output: str | None = None,
    dry_run: bool = False,
    limit: bool = False,
    true_peak_ceiling: float = -1.5,
    record_snapshot: bool = True,
    lossless_output: bool = False,
) -> bool:
    """Apply one static gain to one file, optionally holding a ceiling.

    This is the suite's one implementation of "move this file by a fixed number
    of dB": it reads the source's tags and audio parameters, re-encodes once and
    swaps the result in atomically.  ``limit`` inserts ``alimiter``, so a gain
    that would pass the ceiling is held rather than clamped.

    Changed in 2.6.0 (F-E2): split out of :func:`apply_album_gain`, which was
    its only caller; the Refinery's peak-target mode is the second, so the
    limiter, the tag rewrite and the depth preservation have one home.

    Args:
        path: The source file.
        gain_db: The static gain to apply, in dB.
        output: Where to write; ``None`` replaces *path* in place.
        dry_run: Plan only — nothing is written and ``False`` is returned.
        limit: Insert the limiter, because the ceiling decided this gain.
        true_peak_ceiling: The ceiling the limiter holds, in dBTP.
        record_snapshot: Record an undo snapshot against the output.  The
            Refinery pipeline records its own, so it passes ``False``.
        lossless_output: Write a container the normaliser has no tuned encoder
            for (WAV/AIFF) through the shared format matrix.  Off by default,
            so album mode keeps refusing those containers; the Refinery's
            peak target turns it on because it is lossless-first.

    Returns:
        ``True`` when a file was written, ``False`` when the gain was too small
        to matter or the run was a dry run.

    Raises:
        AudioFormatError: The destination has no encoder.
        subprocess.CalledProcessError: FFmpeg rejected the encode.
        Exception: Any other IO or mutagen error; the temp file is removed.
    """
    if abs(gain_db) < GAIN_EPSILON_DB or dry_run:
        return False

    destination = output or path
    codec, extra = _static_gain_codec(destination, lossless_output=lossless_output)
    ext = os.path.splitext(destination)[1].lower()
    # A peak rewrite may write a container the normaliser has no tuned encoder
    # for; the shared matrix's own PCM codec for the source's depth keeps a
    # 24-bit WAV/AIFF at 24 bits (the WAV/AIFF muxers otherwise default to 16).
    depth_args = (
        audio_formats.preserve_depth_params(ext, path) if lossless_output else []
    )
    temp_out = destination + f".albtmp{ext}"
    # Tags and audio parameters come from the source: on a copy-out run the
    # destination does not exist yet, so reading it would silently lose the
    # tags and the source's own sample rate.
    original_tags = read_tags_raw(path)

    command = [
        FFMPEG_PATH,
        "-hide_banner",
        "-y",
        "-i",
        path,
        "-af",
        _gain_chain(gain_db, limit=limit, true_peak_ceiling=true_peak_ceiling),
        "-c:a",
        codec,
        *extra,
        *_preserve_args(path, codec),
        *depth_args,
        temp_out,
    ]

    try:
        run_secure_subprocess(command[0], command[1:], capture_output=True, check=True)
        write_tags_raw(temp_out, original_tags, record_snapshot=False)
        if record_snapshot:
            record_tag_edit_snapshot(destination, "album_gain")
        os.replace(temp_out, destination)
    except Exception:
        if os.path.exists(temp_out):
            os.remove(temp_out)
        raise
    return True


def apply_album_gain(
    path: str,
    gain_db: float,
    *,
    output: str | None = None,
    dry_run: bool = False,
    limit: bool = False,
    true_peak_ceiling: float = -1.5,
    record_snapshot: bool = True,
) -> bool:
    """Apply one planned album gain to one track.

    A thin name over :func:`apply_static_gain`: the album caller reads what it
    means, and exactly one implementation stands behind both.

    Args:
        path: The source track.
        gain_db: The gain the plan decided for it.
        output: Where to write; ``None`` replaces *path* in place.
        dry_run: Plan only - nothing is written and ``False`` is returned.
        limit: Insert the limiter, because the ceiling decided this gain.
        true_peak_ceiling: The ceiling the limiter holds, in dBTP.
        record_snapshot: Record an undo snapshot against the output.  The
            Refinery pipeline records its own, so it passes ``False``.

    Returns:
        ``True`` when a file was written, ``False`` when the gain was too small
        to matter or the run was a dry run.
    """
    return apply_static_gain(
        path,
        gain_db,
        output=output,
        dry_run=dry_run,
        limit=limit,
        true_peak_ceiling=true_peak_ceiling,
        record_snapshot=record_snapshot,
    )


def plan_payload(plan: AlbumPlan) -> dict[str, Any]:
    """Return a JSON-ready view of *plan* for a run report or a log line."""
    return {
        "album_lufs": round(plan.album_lufs, 2),
        "target_lufs": plan.target_lufs,
        "true_peak_ceiling": plan.true_peak_ceiling,
        "album_true_peak": plan.album_true_peak,
        "gains": {key: round(gain, 2) for key, gain in plan.gains.items()},
        "limited": dict(plan.limited),
        "notes": list(plan.notes),
    }
