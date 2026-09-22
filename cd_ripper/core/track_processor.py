"""
track_processor.py  –  Read verification and CD track extraction logic.

Implements multi-read verification with majority-vote resolution,
C2 error-pointer diagnostics, and the main extract_track_scsi()
function that reads raw CDDA sectors and writes a WAV file.
"""

import ctypes
import os
import struct
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from audio_suite_shared.exceptions import AudioConfigurationError
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
    """

    max_read_attempts: int = 3
    use_c2_hint: bool = False

    def __post_init__(self) -> None:
        if self.max_read_attempts < 2:
            raise AudioConfigurationError(
                "max_read_attempts must be >= 2 to allow read comparison, "
                f"got {self.max_read_attempts}"
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
) -> None:
    config = verification_config or RipVerificationConfig()
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
            buf = ctypes.create_string_buffer(
                CHUNK * _bytes_per_sector(request_c2=config.use_c2_hint)
            )

            while written < sectors:
                if cancelled_fn():
                    break
                chunk = min(CHUNK, sectors - written)
                lba = start_lba + written
                audio_bytes = _read_verified_chunk(
                    handle, lba, chunk, buf, log_cb, track_num, config
                )
                fout.write(audio_bytes)
                written += chunk
                pct = min(int(written / sectors * 90), 90)
                progress_cb(track_num, pct, f"Extracting\u2026 {pct}%")

            # Rewrite header with actual size
            actual = written * SECTOR_SIZE
            fout.seek(0)
            fout.write(wav_header(actual))

        log_cb(
            f"[SCSI] Track {track_num:02d}: {written}/{sectors} sectors \u2192 "
            f"{os.path.basename(out_wav)}"
        )
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)
