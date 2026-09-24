"""
track_processor.py  –  Read verification and CD track extraction logic.

Implements multi-read verification with majority-vote resolution,
C2 error-pointer diagnostics, and the main extract_track_scsi()
function that reads raw CDDA sectors and writes a WAV file.
"""

import ctypes
import os
import struct
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np

from audio_suite_shared.exceptions import AudioConfigurationError
from cd_ripper.core.accuraterip import (
    EDGE_SKIP_FRAMES,
    FRAMES_PER_SECTOR,
    LookupFound,
    LookupNotFound,
    LookupOffline,
    LookupResult,
    VerificationStatus,
    compute_track_checksums,
    verify_track,
    with_gap_window,
)
from cd_ripper.core.drive_handler import (
    BITS_PER_SAMPLE,
    CHANNELS,
    SAMPLE_RATE,
    SECTOR_SIZE,
    _bytes_per_sector,
    _open_device,
    _read_cd_scsi,
    _require_windows,
)
from cd_ripper.core.read_offset import (
    TrackReadLayout,
    aligned_track_pcm,
    compute_track_read_layout,
    pad_tail_shortfall,
)

# ── Exceptions and configuration ──────────────────────────────────────────


class UnresolvedSectorError(RuntimeError):
    """
    Raised when repeated reads of a chunk never reach majority agreement on
    every byte. Callers (RipTask.run already catches RuntimeError) must let
    this abort the track rather than writing an unverified file.
    """


@dataclass(frozen=True)
class RipVerificationConfig:
    """
    Controls read verification behaviour for extract_track_scsi.

    Attributes:
        max_read_attempts: Total reads permitted per chunk when the first
            two disagree, before resolving by majority vote. Must be >= 2.
        use_c2_hint: If True, request C2 error flags on the first read of
            each chunk and skip the second read when every C2 byte is
            zero. This is a speed optimisation only and must not be
            enabled unless diagnose_c2_reliability() has shown this
            specific drive actually populates the C2 field -- a drive
            that silently zero-fills C2 will look identical to a clean
            read, silently defeating verification. Defaults to False.
        read_offset_frames: Drive read offset in whole CDDA frames (1/75 s),
            the number of frames by which the drive's stream leads the LBA
            it was asked for. A non-zero value re-aligns the extracted
            window and the rip-twice/AccurateRip checksums so a
            mis-aligned drive does not produce spurious MISMATCHes.
            Measured per drive via ``cd-rip --detect-read-offset`` and
            persisted in the shared suite config. Must be within
            [0, FRAMES_PER_SECTOR]. Defaults to 0.
    """

    max_read_attempts: int = 3
    use_c2_hint: bool = False
    read_offset_frames: int = 0

    def __post_init__(self) -> None:
        if self.max_read_attempts < 2:
            raise AudioConfigurationError(
                "max_read_attempts must be >= 2 to allow read comparison, "
                f"got {self.max_read_attempts}"
            )
        if self.read_offset_frames < 0 or self.read_offset_frames > FRAMES_PER_SECTOR:
            raise AudioConfigurationError(
                "read_offset_frames must be within "
                f"[0, {FRAMES_PER_SECTOR}], got {self.read_offset_frames}"
            )


@dataclass(frozen=True)
class C2DiagnosticResult:
    """Result of diagnose_c2_reliability() for one drive/LBA range."""

    lba_tested: int
    sectors_tested: int
    audio_data_matched: bool
    c2_flags_all_zero: bool
    c2_nonzero_byte_count: int
    c2_appears_honest: bool
    detail: str


# ── C2 reliability diagnostic ─────────────────────────────────────────────


def diagnose_c2_reliability(
    drive_letter: str,
    start_lba: int,
    log_cb: Callable[[str], None],
    sectors: int = 8,
) -> C2DiagnosticResult:
    """
    Empirically test whether this drive's C2 error-pointer reporting can be
    trusted, rather than assuming a spec sheet or forum report about the
    drive model applies to this specific unit.

    Reads the same ``sectors`` sectors twice with C2 flags requested and
    checks:
      1. Whether the audio-data portion is byte-identical between the two
         reads (a mismatch here means this LBA range is not a fair test
         spot -- re-run against a different, known-good track).
      2. Whether the C2 flag bytes are all-zero. The MMC spec explicitly
         permits a drive with no real C2 support to return zero-filled
         data instead of rejecting the request, so an all-zero result
         does NOT prove errors are absent.

    A result only "appears honest" if the audio data matched between reads
    AND at least one non-zero C2 byte was returned, proving the drive is
    populating the field rather than silently zero-filling it. Treat a
    passing result as weak positive evidence, not certainty -- there is no
    way to force a genuine C2 event on demand for this test.
    """
    _require_windows()
    handle = _open_device(drive_letter)
    try:
        bytes_per_sector = _bytes_per_sector(request_c2=True)
        buf_a = ctypes.create_string_buffer(sectors * bytes_per_sector)
        buf_b = ctypes.create_string_buffer(sectors * bytes_per_sector)
        _read_cd_scsi(handle, start_lba, sectors, buf_a, log_cb, request_c2=True)
        _read_cd_scsi(handle, start_lba, sectors, buf_b, log_cb, request_c2=True)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)

    raw_a, raw_b = buf_a.raw, buf_b.raw
    audio_a = bytearray()
    audio_b = bytearray()
    c2_a = bytearray()
    for i in range(sectors):
        base = i * bytes_per_sector
        audio_a += raw_a[base : base + SECTOR_SIZE]
        audio_b += raw_b[base : base + SECTOR_SIZE]
        c2_a += raw_a[base + SECTOR_SIZE : base + bytes_per_sector]

    audio_matched = bytes(audio_a) == bytes(audio_b)
    nonzero_c2 = int(np.frombuffer(bytes(c2_a), dtype=np.uint8).astype(bool).sum())
    c2_all_zero = nonzero_c2 == 0
    appears_honest = audio_matched and not c2_all_zero

    if not audio_matched:
        detail = (
            "Audio data differed between two reads of the same LBA range -- "
            "this location isn't a valid test spot (or the drive has a real "
            "read problem here). Re-run against a different, known-good "
            "track before drawing any conclusion about C2."
        )
    elif c2_all_zero:
        detail = (
            "C2 field was entirely zero across both reads. This is "
            "consistent with either a truly clean read, or the drive "
            "silently zero-filling an unsupported C2 field -- the MMC spec "
            "permits this and it cannot be distinguished from a clean read "
            "using this test alone. Do not treat this as proof the drive "
            "honours C2; assume it does not unless a known-bad sector "
            "produces a non-zero response."
        )
    else:
        detail = (
            f"{nonzero_c2} non-zero C2 byte(s) observed, audio data matched "
            "between reads -- weak positive evidence the drive is "
            "populating this field rather than zero-filling it."
        )

    log_cb(f"[C2 Diagnostic] {detail}")

    return C2DiagnosticResult(
        lba_tested=start_lba,
        sectors_tested=sectors,
        audio_data_matched=audio_matched,
        c2_flags_all_zero=c2_all_zero,
        c2_nonzero_byte_count=nonzero_c2,
        c2_appears_honest=appears_honest,
        detail=detail,
    )


# ── Read verification (multi-read compare + optional C2 hint) ─────────────


def _resolve_by_majority(reads: list[bytes]) -> tuple[bytes, int]:
    """
    Vectorised per-byte majority vote across N re-reads of the same chunk.

    The loop below iterates over read *attempts* (at most a handful), never
    over audio samples -- each iteration is a single vectorised NumPy
    comparison across the whole buffer, per the suite's no-raw-sample-loop
    rule.

    Returns:
        (resolved_bytes, unresolved_byte_count). A byte position is
        "unresolved" if no value appears in more than half of the reads;
        callers must treat a non-zero count as a failed verification.
    """
    arr = np.frombuffer(b"".join(reads), dtype=np.uint8).reshape(len(reads), -1)
    n_reads = arr.shape[0]
    majority_needed = n_reads // 2 + 1

    counts = np.zeros_like(arr, dtype=np.int16)
    for i in range(n_reads):
        counts[i] = (arr == arr[i]).sum(axis=0)

    best_idx = np.argmax(counts, axis=0)
    col_idx = np.arange(arr.shape[1])
    resolved = arr[best_idx, col_idx]
    best_count = counts[best_idx, col_idx]

    unresolved_mask = best_count < majority_needed
    return resolved.astype(np.uint8).tobytes(), int(unresolved_mask.sum())


def _read_verified_chunk(
    handle: int,
    lba: int,
    chunk_sectors: int,
    buf: ctypes.Array[ctypes.c_char],
    log_cb: Callable[[str], None],
    track_num: int,
    config: RipVerificationConfig,
) -> bytes:
    """
    Read ``chunk_sectors`` sectors starting at ``lba``, verified per ``config``.

    If ``config.use_c2_hint`` is True, a single read is taken with C2 error
    flags requested; if every C2 byte in the chunk is zero, that read is
    accepted immediately as a fast path. Otherwise (or if C2 flags a
    possible error), falls back to multi-read comparison: read again, and
    if the two disagree, keep re-reading up to ``config.max_read_attempts``
    total times, then resolve byte-for-byte by majority vote. Raises
    UnresolvedSectorError if any byte position never reaches majority
    agreement.
    """
    reads: list[bytes] = []

    if config.use_c2_hint:
        bytes_per_sector = _bytes_per_sector(request_c2=True)
        _read_cd_scsi(handle, lba, chunk_sectors, buf, log_cb, request_c2=True)
        raw = buf.raw[: chunk_sectors * bytes_per_sector]
        audio = bytearray()
        c2_all_zero = True
        for i in range(chunk_sectors):
            base = i * bytes_per_sector
            audio += raw[base : base + SECTOR_SIZE]
            if any(raw[base + SECTOR_SIZE : base + bytes_per_sector]):
                c2_all_zero = False
        if c2_all_zero:
            return bytes(audio)
        reads.append(bytes(audio))
        log_cb(
            f"[Verify] Track {track_num:02d}: LBA {lba} C2 flagged a "
            f"possible error -- falling back to multi-read verification"
        )

    while len(reads) < 2:
        _read_cd_scsi(handle, lba, chunk_sectors, buf, log_cb)
        reads.append(buf.raw[: chunk_sectors * SECTOR_SIZE])

    while reads[0] != reads[-1] and len(reads) < config.max_read_attempts:
        _read_cd_scsi(handle, lba, chunk_sectors, buf, log_cb)
        reads.append(buf.raw[: chunk_sectors * SECTOR_SIZE])

    if all(r == reads[0] for r in reads):
        return reads[0]

    resolved, unresolved_count = _resolve_by_majority(reads)
    if unresolved_count:
        raise UnresolvedSectorError(
            f"Track {track_num:02d}: {unresolved_count} byte position(s) at "
            f"LBA {lba} disagreed across all {len(reads)} read attempts "
            f"with no majority -- aborting track rather than writing "
            f"unverified audio."
        )

    log_cb(
        f"[Verify] Track {track_num:02d}: LBA {lba} required {len(reads)} "
        f"reads, resolved by majority vote"
    )
    return resolved


# ── Track extraction ──────────────────────────────────────────────────────


def extract_track_scsi(
    drive_letter: str,
    start_lba: int,
    sectors: int,
    out_wav: str,
    progress_cb: Callable[[int, int, str], None],
    track_num: int,
    cancelled_fn: Callable[[], bool],
    log_cb: Callable[[str], None],
    verification_config: RipVerificationConfig | None = None,
    is_last_track: bool = False,
) -> None:
    config = verification_config or RipVerificationConfig()
    layout: TrackReadLayout = compute_track_read_layout(
        start_lba, sectors, config.read_offset_frames, is_last_track
    )
    if config.read_offset_frames:
        log_cb(
            f"[Offset] Track {track_num:02d}: applying drive read offset "
            f"{config.read_offset_frames:+d} frame(s) "
            f"(read LBA {layout.read_start_lba}, {layout.read_sectors} sectors)"
        )

    handle = _open_device(drive_letter)
    CHUNK = 20

    byte_rate = SAMPLE_RATE * CHANNELS * (BITS_PER_SAMPLE // 8)
    block_align = CHANNELS * (BITS_PER_SAMPLE // 8)
    data_size = sectors * SECTOR_SIZE

    def wav_header(sz: int) -> bytes:
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + sz,
            b"WAVE",
            b"fmt ",
            16,
            1,
            CHANNELS,
            SAMPLE_RATE,
            byte_rate,
            block_align,
            BITS_PER_SAMPLE,
            b"data",
            sz,
        )

    try:
        with open(out_wav, "wb") as fout:
            fout.write(wav_header(data_size))
            written = 0
            in_byte = 0
            total_in = layout.read_sectors * SECTOR_SIZE
            buf = ctypes.create_string_buffer(
                CHUNK * _bytes_per_sector(request_c2=config.use_c2_hint)
            )

            while in_byte < total_in and written < data_size:
                if cancelled_fn():
                    break
                chunk = min(CHUNK, layout.read_sectors - in_byte // SECTOR_SIZE)
                lba = layout.read_start_lba + in_byte // SECTOR_SIZE
                audio_bytes = _read_verified_chunk(
                    handle, lba, chunk, buf, log_cb, track_num, config
                )
                # Clip the chunk to the aligned window (drops the leading
                # offset frames and any tail shortfall beyond the nominal end).
                seg_start = max(0, layout.skip_bytes - in_byte)
                seg_end = min(
                    chunk * SECTOR_SIZE, layout.skip_bytes + data_size - in_byte
                )
                if seg_start < seg_end:
                    fout.write(audio_bytes[seg_start:seg_end])
                    written += seg_end - seg_start
                in_byte += chunk * SECTOR_SIZE
                pct = min(int(written / data_size * 90), 90)
                progress_cb(track_num, pct, f"Extracting\u2026 {pct}%")

            # Rewrite header with actual size
            fout.seek(0)
            fout.write(wav_header(written))

        log_cb(
            f"[SCSI] Track {track_num:02d}: "
            f"{written // SECTOR_SIZE}/{sectors} sectors \u2192 "
            f"{os.path.basename(out_wav)}"
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


# ── Track verification (rip-twice + AccurateRip cross-check) ──────────────


class RipVerificationMode(str, Enum):
    """Per-disc verification strategy (7a of the governing plan)."""

    OFF = "off"
    TWICE = "twice"
    ACCURATERIP = "accuraterip"


@dataclass(frozen=True)
class VerificationPlan:
    """One verification strategy, resolved once per disc before any rip.

    Attributes:
        mode: The strategy to apply to each extracted track.
        lookup: AccurateRip result from the session-level disc lookup, or
            ``None`` for local-only modes.
        toc: The full disc TOC, so track numbering and gap-edge neighbours
            stay consistent across every track's verification.
    """

    mode: RipVerificationMode = RipVerificationMode.OFF
    lookup: LookupResult | None = None
    toc: tuple[dict[str, int], ...] = ()


def read_wav_pcm(path: str) -> bytes:
    """Return the raw PCM payload of a PCM16 RIFF/WAVE file.

    Walks the chunk list to locate the ``data`` chunk so exotic headers
    (extra ``fmt`` padding, ``LIST`` chunks) do not break extraction.

    Raises:
        ValueError: If the file is not a RIFF/WAVE container or lacks a
            ``data`` chunk.
    """
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) < 44 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError(f"{path}: not a RIFF/WAVE file")
    pos = 12
    while pos + 8 <= len(blob):
        chunk_id = blob[pos : pos + 4]
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        if chunk_id == b"data":
            if pos + 8 + size > len(blob):
                raise ValueError(f"{path}: data chunk truncated")
            return blob[pos + 8 : pos + 8 + size]
        pos += 8 + size + (size & 1)
    raise ValueError(f"{path}: no data chunk found")


def read_track_pcm(
    drive_letter: str,
    start_lba: int,
    sectors: int,
    track_num: int,
    cancelled_fn: Callable[[], bool],
    log_cb: Callable[[str], None],
    verification_config: RipVerificationConfig | None = None,
    is_last_track: bool = False,
) -> bytes:
    """Re-read raw CDDA audio and return the aligned PCM bytes.

    The rip-twice pass: an independent second read of the same extents using
    the same verified multi-read machinery as extraction. Returns fewer bytes
    than requested if ``cancelled_fn`` becomes true; callers must re-check
    their cancellation state afterwards.

    When the read config carries a drive read offset, the same
    ``compute_track_read_layout`` used for extraction is applied so pass B
    (and the AccurateRip checksum) uses the *exact* window extraction wrote —
    a mis-aligned drive must not be able to make a good rip mismatch.

    Raises:
        UnresolvedSectorError, AudioIOError, OSError: propagated from the
            verified-read path; callers must treat any of these as a failed
            verification and never write the track.
    """
    config = verification_config or RipVerificationConfig()
    layout: TrackReadLayout = compute_track_read_layout(
        start_lba, sectors, config.read_offset_frames, is_last_track
    )
    handle = _open_device(drive_letter)
    CHUNK = 20
    try:
        out = bytearray()
        written = 0
        buf = ctypes.create_string_buffer(
            CHUNK * _bytes_per_sector(request_c2=config.use_c2_hint)
        )
        while written < layout.read_sectors:
            if cancelled_fn():
                break
            chunk = min(CHUNK, layout.read_sectors - written)
            lba = layout.read_start_lba + written
            audio_bytes = _read_verified_chunk(
                handle, lba, chunk, buf, log_cb, track_num, config
            )
            out += audio_bytes
            written += chunk
        return aligned_track_pcm(bytes(out), layout, sectors)
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _toc_index(toc: Sequence[dict[str, int]], toc_entry: dict[str, int]) -> int:
    """Resolve a track's position in the disc TOC (identity, then number)."""
    for index, entry in enumerate(toc):
        if entry is toc_entry or entry.get("number") == toc_entry.get("number"):
            return index
    return -1


def verify_extracted_track(
    drive_letter: str,
    toc_entry: dict[str, int],
    toc: Sequence[dict[str, int]],
    first_pcm: bytes,
    plan: VerificationPlan,
    verification_config: RipVerificationConfig | None,
    track_num: int,
    cancelled_fn: Callable[[], bool],
    log_cb: Callable[[str], None],
) -> tuple[VerificationStatus | None, str]:
    """Verify one freshly extracted track using the plan's strategy.

    Pass A is the extracted PCM, pass B is a fresh device read. If both agree
    and the mode needs the database, the track-level checksums are matched
    first; with-gap candidates are checked only when the track window misses,
    re-reading the previous track's tail and next track's head separately.

    Returns a ``VerificationStatus`` plus a human-readable detail for the
    ``MISMATCH`` / ``NO_ENTRY`` / ``OFFLINE`` cases, or ``(None, "cancelled")``
    when the pass-B re-reads were cut short. The caller decides how to block
    on the result; ``MISMATCH`` must never be written.

    Raises:
        ValueError: If the re-read produced an unexpected number of sectors
            or the TOC does not contain ``toc_entry``.
    """
    if plan.mode is RipVerificationMode.OFF:
        raise ValueError("verify_extracted_track requires a non-OFF plan")
    index = _toc_index(toc, toc_entry)
    if index < 0:
        raise ValueError("verification TOC does not contain this track's TOC entry")
    track_number = index + 1
    track_count = len(toc)
    is_last_track = index == track_count - 1

    # The extraction window comes up short of the nominal length only for the
    # final track of a read-offset drive: recovering the shifted tail needs a
    # past-lead-out read, which the drive refuses. That shortfall lives
    # entirely inside the AccurateRip last-track skip window, so the
    # checksums stay comparable; account for it in the length gate rather
    # than mis-flagging a correctly aligned rip.
    offset_frames = (verification_config or RipVerificationConfig()).read_offset_frames
    layout: TrackReadLayout = compute_track_read_layout(
        toc_entry["start_lba"], toc_entry["sectors"], offset_frames, is_last_track
    )
    expected = toc_entry["sectors"] * SECTOR_SIZE - layout.tail_shortfall_bytes
    if len(first_pcm) != expected:
        return VerificationStatus.MISMATCH, (
            f"extraction produced {len(first_pcm)} data bytes, expected {expected}"
        )

    log_cb(f"[Verify] Track {track_num:02d}: re-reading for rip-twice comparison")
    second_pcm = read_track_pcm(
        drive_letter,
        toc_entry["start_lba"],
        toc_entry["sectors"],
        track_num,
        cancelled_fn,
        log_cb,
        verification_config,
        is_last_track=is_last_track,
    )
    if cancelled_fn():
        return None, "cancelled"

    # A short final-track window must be padded to nominal length before
    # any checksum: the skip boundary is derived from the PCM length, and
    # the padding (inside the never-hashed 2940-frame skip) keeps both
    # passes byte-identical to the full window.
    if layout.tail_shortfall_bytes:
        first_pcm = pad_tail_shortfall(first_pcm, layout, toc_entry["sectors"])
        second_pcm = pad_tail_shortfall(second_pcm, layout, toc_entry["sectors"])

    try:
        first_sums = compute_track_checksums(first_pcm, track_number, track_count)
        second_sums = compute_track_checksums(second_pcm, track_number, track_count)
    except ValueError as exc:
        return VerificationStatus.MISMATCH, f"invalid PCM for checksum: {exc}"

    if first_sums != second_sums:
        return VerificationStatus.MISMATCH, (
            f"rip-twice: second read differs from first "
            f"(v1 {first_sums.crc1:08x} vs {second_sums.crc1:08x})"
        )

    if plan.mode is RipVerificationMode.TWICE:
        return VerificationStatus.VERIFIED, "rip-twice check passed"

    lookup = plan.lookup
    if not isinstance(lookup, LookupFound):
        if isinstance(lookup, LookupNotFound):
            return VerificationStatus.NO_ENTRY, lookup.reason
        if isinstance(lookup, LookupOffline):
            return VerificationStatus.OFFLINE, lookup.reason
        return VerificationStatus.OFFLINE, "no AccurateRip lookup performed"

    if verify_track(second_sums, lookup.entries, index) is VerificationStatus.VERIFIED:
        return VerificationStatus.VERIFIED, "matched AccurateRip (track window)"
    if cancelled_fn():
        return None, "cancelled"

    prev_entry = toc[index - 1] if index > 0 else None
    next_entry = toc[index + 1] if index + 1 < len(toc) else None
    edge_sectors = EDGE_SKIP_FRAMES // FRAMES_PER_SECTOR
    prev_tail: bytes | None = None
    next_head: bytes | None = None
    if prev_entry is not None:
        # The previous track can never be the final track (this track has a
        # next), so its edge read uses the standard forward-extended layout.
        tail_sectors = min(prev_entry["sectors"], edge_sectors)
        tail_start = prev_entry["start_lba"] + prev_entry["sectors"] - tail_sectors
        prev_tail = read_track_pcm(
            drive_letter,
            tail_start,
            tail_sectors,
            track_num,
            cancelled_fn,
            log_cb,
            verification_config,
            is_last_track=False,
        )
        if cancelled_fn():
            return None, "cancelled"
    if next_entry is not None:
        head_sectors = min(next_entry["sectors"], edge_sectors)
        next_head = read_track_pcm(
            drive_letter,
            next_entry["start_lba"],
            head_sectors,
            track_num,
            cancelled_fn,
            log_cb,
            verification_config,
            is_last_track=index + 1 == track_count - 1,
        )
        if cancelled_fn():
            return None, "cancelled"

    gap_pcm = with_gap_window(second_pcm, prev_tail, next_head)
    gap_sums = compute_track_checksums(gap_pcm, track_number, track_count)
    if verify_track(gap_sums, lookup.entries, index) is VerificationStatus.VERIFIED:
        return VerificationStatus.VERIFIED, "matched AccurateRip (with-gap window)"
    return VerificationStatus.MISMATCH, (
        f"AccurateRip cross-check failed: CRC not found for track "
        f"{track_number}/{track_count} (v1 {second_sums.crc1:08x}, "
        f"v2 {second_sums.crc2:08x})"
    )
