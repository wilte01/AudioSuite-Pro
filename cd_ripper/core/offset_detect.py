"""offset_detect.py — measure a drive's read offset against the AccurateRip DB.

The read offset is discovered empirically from the disc in the drive: read
each non-last track once with generous context on both sides, then sweep
every candidate frame shift and score how many track windows match the
AccurateRip database. The v1 score is O(1) per candidate via modular prefix
sums (exact production skip semantics); the winning shift is then confirmed
with the REAL ``compute_track_checksums`` + ``verify_track`` across every
track before it is reported.

The margin reads intentionally avoid the lead-out: the final track reads
with a 16-sector lookback but no lookahead (drives refuse reads past the
end of the disc), which still leaves enough raw context to grade every
candidate shift since the offset never exceeds one sector. With a
multi-track disc the sweep is unanimous across the graded tracks before the
confirm phase runs; a candidate that is not unanimous is discarded and
nothing is persisted. Requires a live CD in the drive and a reachable
AccurateRip DB.
"""

from __future__ import annotations

import ctypes
import logging
from collections.abc import Callable, Sequence
from typing import TypeAlias

import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import AudioIOError
from cd_ripper.core.accuraterip import (
    EDGE_SKIP_FRAMES,
    FIRST_TRACK_SKIP_FRAMES,
    FRAMES_PER_SECTOR,
    DBEntry,
    VerificationStatus,
    compute_track_checksums,
    verify_track,
)
from cd_ripper.core.drive_handler import SECTOR_SIZE, _open_device, _read_cd_scsi
from cd_ripper.core.read_offset import (
    TrackReadLayout,
    aligned_track_pcm,
    compute_track_read_layout,
    pad_tail_shortfall,
)

logger = logging.getLogger(__name__)
MASK32 = 0xFFFFFFFF
MARGIN_SECTORS = 16
SEARCH_BAND_FRAMES = FRAMES_PER_SECTOR

_GradedRead: TypeAlias = tuple[
    int,
    int,
    npt.NDArray[np.uint64],
    npt.NDArray[np.uint64],
    int,
    int,
    int,
    int,
]


def _read_raw_range(drive_letter: str, lba: int, count: int) -> bytes | None:
    """Single-pass, unverified raw READ CD of ``count`` sectors from ``lba``.

    Returns ``None`` when the drive rejects the range (e.g. attempts to read
    past the lead-out), so callers can degrade gracefully.
    """
    try:
        handle = _open_device(drive_letter)
    except (AudioIOError, OSError, RuntimeError):
        return None
    try:
        out = bytearray()
        buf = ctypes.create_string_buffer(128 * SECTOR_SIZE)
        done = 0
        while done < count:
            c = min(128, count - done)
            _read_cd_scsi(handle, lba + done, c, buf, lambda _msg: None)
            out += buf.raw[: c * SECTOR_SIZE]
            done += c
        return bytes(out)
    except (AudioIOError, OSError, RuntimeError):
        logger.warning(
            "Read-offset scan read at LBA %d (+%d sectors) failed",
            lba,
            count,
            exc_info=True,
        )
        return None
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _prefix_arrays(
    frames_bytes: bytes,
) -> tuple[npt.NDArray[np.uint64], npt.NDArray[np.uint64], int]:
    """Modular prefix sums for O(1) v1 evaluation.

    ``Pj[i] = sum_{k<i} (k*v[k] mod 2^32)`` and ``Pw[i] = sum_{k<i} v[k]``,
    both in uint64 so a long track's cumsum stays inside uint64; per-window
    reductions to mod 2^32 happen at evaluation time.
    """
    v: npt.NDArray[np.uint32] = np.frombuffer(frames_bytes, dtype="<u4")
    n = int(v.size)
    vu: npt.NDArray[np.uint64] = v.astype(np.uint64)
    j: npt.NDArray[np.uint64] = np.arange(n, dtype=np.uint64)
    pj: npt.NDArray[np.uint64] = np.empty(n + 1, dtype=np.uint64)
    pw: npt.NDArray[np.uint64] = np.empty(n + 1, dtype=np.uint64)
    pj[0] = 0
    pw[0] = 0
    pj[1:] = np.cumsum((j * vu) & np.uint64(MASK32), dtype=np.uint64)
    pw[1:] = np.cumsum(vu, dtype=np.uint64)
    return pj, pw, n


def _v1_fast(
    pj: npt.NDArray[np.uint64],
    pw: npt.NDArray[np.uint64],
    s: int,
    start_idx: int,
    end_idx: int,
) -> int:
    """Production v1 for the window ``E[s : s + frames_total]`` at shift ``s``.

    Mirrors the production checksum: hashed frame ``k`` of the read buffer
    contributes ``(k - s + 1) * v[k]`` (positions restart at 1 per track),
    so ``v1 = (Pj[b] - Pj[a]) - (s - 1) * (Pw[b] - Pw[a]) mod 2^32``.
    """
    a = s + start_idx
    b = s + end_idx
    dj = int(pj[b]) - int(pj[a])
    dw = (int(pw[b]) - int(pw[a])) & MASK32
    return (dj - ((s - 1) & MASK32) * dw) & MASK32


def _window_bounds(
    frames_total: int, track_number: int, track_count: int
) -> tuple[int, int]:
    """The checksum's hashed sub-window, matching the production semantics."""
    start = FIRST_TRACK_SKIP_FRAMES if track_number == 1 else 0
    end = frames_total - (EDGE_SKIP_FRAMES if track_number == track_count else 0)
    return start, max(end, 0)


def _db_v1_set(entries: Sequence[DBEntry], track_index: int) -> set[int]:
    return {e.tracks[track_index].crc1 for e in entries if track_index < len(e.tracks)}


def detect_read_offset_frames(
    drive_letter: str,
    toc: Sequence[dict[str, int]],
    entries: Sequence[DBEntry],
    log_cb: Callable[[str], None],
) -> int | None:
    """Measure the drive's read offset (frames) against ``entries``.

    Reads each track once with 16-sector margin (no lead-out reads on the final
    track), sweeps every candidate frame shift in
    ``[-(sectors), +(sectors)]``, and requires a unanimous match across the
    evaluable tracks; the winner is re-confirmed with the production
    ``compute_track_checksums`` + ``verify_track`` on every track before being
    returned.

    Args:
        drive_letter: Bare drive letter (or 'D:' form).
        toc: Disc TOC from ``read_toc`` (track order and 1-based numbers).
        entries: AccurateRip ``DBEntry`` records for this disc.
        log_cb: Progress/log sink.

    Returns:
        The unanimous offset in whole frames, or ``None`` when no candidate
        is conclusive (ambiguous sweep or a confirmation failure) — callers
        must not persist anything.
    """
    track_count = len(toc)
    if track_count == 0:
        return None

    graded: list[_GradedRead] = []
    for idx, t in enumerate(toc):
        start_lba = t["start_lba"]
        sectors = t["sectors"]
        lookback = min(MARGIN_SECTORS, start_lba)
        lookahead = MARGIN_SECTORS if idx < track_count - 1 else 0
        ext = _read_raw_range(
            drive_letter, start_lba - lookback, lookback + sectors + lookahead
        )
        if ext is None:
            log_cb(f"[Offset] Track {t['number']:02d}: unreadable, skipped for grading")
            continue
        pj, pw, n_frames = _prefix_arrays(ext)
        frames_total = sectors * FRAMES_PER_SECTOR
        start_idx, end_idx = _window_bounds(frames_total, t["number"], track_count)
        graded.append(
            (
                idx,
                lookback * FRAMES_PER_SECTOR,
                pj,
                pw,
                n_frames,
                start_idx,
                end_idx,
                frames_total,
            )
        )

    if not graded:
        return None

    match_counts: dict[int, int] = {}
    eval_counts: dict[int, int] = {}
    for reader in graded:
        gidx, base, pj, pw, n_frames, start_idx, end_idx, frames_total = reader
        db_v1 = _db_v1_set(entries, gidx)
        if not db_v1:
            continue
        for candidate in range(-SEARCH_BAND_FRAMES, SEARCH_BAND_FRAMES + 1):
            s = base + candidate
            # Grade on the frames the checksum actually hashes: the last
            # track's final 2940 frames are skipped by AccurateRip, so a
            # candidate whose un-hashed tail spills past the read margin is
            # still fully comparable (and the true candidate for the final
            # track is only evaluable this way when lookahead is 0).
            if s < 0 or s + end_idx > n_frames:
                continue
            eval_counts[candidate] = eval_counts.get(candidate, 0) + 1
            if _v1_fast(pj, pw, s, start_idx, end_idx) in db_v1:
                match_counts[candidate] = match_counts.get(candidate, 0) + 1

    if not eval_counts:
        return None
    best = max(eval_counts, key=lambda candidate: match_counts.get(candidate, 0))
    if match_counts.get(best, 0) < eval_counts[best]:
        log_cb(
            f"[Offset] no unanimous candidate (best {best:+d}: "
            f"{match_counts.get(best, 0)}/{eval_counts[best]} graded tracks)"
        )
        return None
    log_cb(f"[Offset] candidate {best:+d} frames unanimous across graded tracks")

    return _confirm_with_production(drive_letter, toc, entries, best, log_cb)


def _confirm_with_production(
    drive_letter: str,
    toc: Sequence[dict[str, int]],
    entries: Sequence[DBEntry],
    offset_frames: int,
    log_cb: Callable[[str], None],
) -> int | None:
    """Re-verify ``offset_frames`` with the real checksum pipeline on every track."""
    track_count = len(toc)
    for idx, t in enumerate(toc):
        layout: TrackReadLayout = compute_track_read_layout(
            t["start_lba"], t["sectors"], offset_frames, idx == track_count - 1
        )
        ext = _read_raw_range(drive_letter, layout.read_start_lba, layout.read_sectors)
        if ext is None or len(ext) <= layout.skip_bytes:
            log_cb(
                f"[Offset] Track {t['number']:02d}: cannot read layout, "
                f"confirmation failed"
            )
            return None
        pcm = aligned_track_pcm(ext, layout, t["sectors"])
        # Pad a short final-track window to nominal length: the checksum's
        # skip boundary derives from the PCM length, and the padding lies
        # inside the never-hashed 2940-frame skip.
        pcm = pad_tail_shortfall(pcm, layout, t["sectors"])
        sums = compute_track_checksums(pcm, t["number"], track_count)
        status = verify_track(sums, entries, idx)
        log_cb(
            f"[Offset] Track {t['number']:02d}: v1={sums.crc1:08x} "
            f"v2={sums.crc2:08x} -> {status.value}"
        )
        if status is not VerificationStatus.VERIFIED:
            return None
    return offset_frames
