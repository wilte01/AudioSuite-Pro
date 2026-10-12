"""
lossless_gain.py — Lossless MP3 volume adjustment via global_gain modification.

Adjusts the ``global_gain`` fields in MPEG Layer III side information without
re-encoding, preserving bit-perfect audio quality.  Equivalent to the
mp3gain / mp3rgain approach but implemented in pure Python — no external
binary dependency.

Each granule/channel block in the side information carries its own 8-bit
``global_gain``.  In the ISO 11172-3 decoder the output amplitude scales with
``2^(global_gain / 4)``, so each unit corresponds to approximately 1.505 dB
of gain change:

    db_per_unit = 20 * log10(2) / 4   ≈ 1.505

Conversely, a desired dB change maps to a global_gain delta of:

    delta = round(desired_db / db_per_unit)

Every ``global_gain`` field of every frame is adjusted (MPEG-1 stereo frames
carry 4 fields: 2 granules × 2 channels; MPEG-1 mono 2; MPEG-2/2.5 stereo 2;
MPEG-2/2.5 mono 1), so stereo balance is preserved exactly.

Side-information layout
-----------------------
The Layer III side info starts with main_data_begin, private_bits and (for
MPEG-1 only) scfsi, followed by one fixed-width block per (granule, channel):

    block = part2_3_length (12) + big_values (9) + global_gain (8)
          + scalefac_compress (4 MPEG-1 / 9 LSF) + window_switching_flag (1)
          + branch (22: table_select 3×5 + region0_count 4 + region1_count 3,
                    or block_type 2 + mixed_block 1 + table_select 2×5
                    + subblock_gain 3×3 — both 22 bits wide)
          + preflag (1, MPEG-1 only) + scalefac_scale (1)
          + count1table_select (1)

Because both window-switching branches have equal width, the block size is
constant: 59 bits (MPEG-1) / 63 bits (MPEG-2/2.5, no preflag and a 9-bit
scalefac_compress).  The global_gain fields therefore sit at a fixed first
offset with a fixed stride:

    ┌──────────────────────────┬────────┬──────────────┬────────┬────────┐
    │ Frame type               │ side   │ first gg bit │ stride │ fields │
    ├──────────────────────────┼────────┼──────────────┼────────┼────────┤
    │ MPEG-1 stereo/joint/dual │ 32 B   │ 9+3+8+21=41  │ 59     │ 4      │
    │ MPEG-1 mono              │ 17 B   │ 9+5+4+21=39  │ 59     │ 2      │
    │ MPEG-2/2.5 stereo/joint  │ 17 B   │ 8+2+21=31    │ 63     │ 2      │
    │ MPEG-2/2.5 mono          │ 9 B    │ 8+1+21=30    │ 63     │ 1      │
    └──────────────────────────┴────────┴──────────────┴────────┴────────┘

Exact-fill identity (fields consume the side info exactly):
MPEG-1 stereo 9+3+8+4×59 = 256 bits, MPEG-1 mono 9+5+4+2×59 = 136 bits,
LSF stereo 8+2+2×63 = 136 bits, LSF mono 8+1+63 = 72 bits.

This layout was verified empirically: bumping each candidate bit position by
±1 on LAME-encoded stereo/mono/MPEG-1/MPEG-2/MPEG-2.5 files and decoding with
ffmpeg shows a clean ±1.505 dB lift exactly at the offsets above, on every
decoded window (see Sprint 0 of PLAN_iteration2_remediation.md).

Limitations
-----------
- Only valid for MPEG Layer III (MP3) files.  FLAC, OGG, M4A, WAV, etc.
  cannot be adjusted this way — callers should fall back to lossy
  re-encoding (FFmpeg loudnorm) for non-MP3 formats.
- Supports MPEG-1, MPEG-2, and MPEG-2.5 Layer III in stereo, joint
  stereo, dual channel, and mono modes.
- CBR and VBR files are both handled (per-frame gain modification).
- CRC-protected files (protection bit clear: a 16-bit CRC follows each
  frame header, shifting every side-info offset by 16 bits) are
  **rejected** with ``AudioFormatError``.  Offset-adjusting them would
  require a trustworthy CRC fixture to prove the shift; no such fixture
  is obtainable from the encoders used in this suite (ffmpeg/libmp3lame
  and LAME both emit the protection bit set by default), so the walker
  refuses rather than risk mis-modifying ``global_gain``.
- Free-format frames (bitrate index 0, undefined frame size) are
  **rejected** with ``AudioFormatError``: the frame size cannot be
  derived from the header, so the walker cannot advance frame-by-frame.
- Files with no valid MPEG frames raise ``AudioFormatError``.

Changed in 1.0.1: a valid MP3 whose ``global_gain`` fields are already all
at a clamp bound is now reported as "no change" (returns 0) instead of the
misleading ``AudioFormatError`` "No valid MPEG Layer III frames found".
"""

from __future__ import annotations

import logging
import math
import os
import struct
from typing import BinaryIO, Callable

from audio_suite_shared.batch_undo import record_tag_edit_snapshot
from audio_suite_shared.exceptions import AudioFormatError

logger = logging.getLogger(f"audio_suite.{__name__}")

# ── Constants ────────────────────────────────────────────────────────────────

_GAIN_UNITS_PER_DB: float = 4 / (20 * math.log10(2))
"""Global_gain units per dB of gain change (reciprocal of ~1.505 dB/unit)."""

_MIN_GLOBAL_GAIN: int = 0
_MAX_GLOBAL_GAIN: int = 255

# Bitrate tables differ between MPEG-1 and the low-sampling-frequency
# (MPEG-2 / MPEG-2.5) variants (ISO 11172-3 Table B.1 vs ISO 13818-3).
_BITRATE_V1_KBPS: dict[int, int] = {
    0: 0,
    1: 32,
    2: 40,
    3: 48,
    4: 56,
    5: 64,
    6: 80,
    7: 96,
    8: 112,
    9: 128,
    10: 160,
    11: 192,
    12: 224,
    13: 256,
    14: 320,
    15: 0,
}

_BITRATE_LSF_KBPS: dict[int, int] = {
    0: 0,
    1: 8,
    2: 16,
    3: 24,
    4: 32,
    5: 40,
    6: 48,
    7: 56,
    8: 64,
    9: 80,
    10: 96,
    11: 112,
    12: 128,
    13: 144,
    14: 160,
    15: 0,
}

_SAMPLE_RATES_V1: dict[int, int] = {
    0: 44100,
    1: 48000,
    2: 32000,
    3: 0,
}

_SAMPLE_RATES_MPEG2: dict[int, int] = {
    0: 22050,
    1: 24000,
    2: 16000,
    3: 0,
}

_SAMPLE_RATES_MPEG25: dict[int, int] = {
    0: 11025,
    1: 12000,
    2: 8000,
    3: 0,
}

_MP3_EXTENSIONS: frozenset[str] = frozenset({".mp3"})

# Bit 16 of the MPEG frame header is the CRC-protection bit.  A value of 0
# means a 16-bit CRC check word follows the 4-byte header, shifting every
# side-info offset by 16 bits; a value of 1 means no CRC is present.
_HEADER_CRC_PROTECTION_BIT: int = 0x00010000


# ── Bit-level helpers ────────────────────────────────────────────────────────


def _read_bits(data: bytearray, bit_offset: int, num_bits: int) -> int:
    """Read *num_bits* bits from *data* starting at *bit_offset* (0-indexed)."""
    result = 0
    for i in range(num_bits):
        byte_idx = (bit_offset + i) // 8
        bit_idx = 7 - ((bit_offset + i) % 8)
        if byte_idx < len(data) and (data[byte_idx] >> bit_idx) & 1:
            result |= 1 << (num_bits - 1 - i)
    return result


def _write_bits(data: bytearray, bit_offset: int, num_bits: int, value: int) -> None:
    """Write *num_bits* bits of *value* into *data* at *bit_offset*."""
    for i in range(num_bits):
        byte_idx = (bit_offset + i) // 8
        bit_idx = 7 - ((bit_offset + i) % 8)
        if byte_idx >= len(data):
            break
        bit_val = (value >> (num_bits - 1 - i)) & 1
        if bit_val:
            data[byte_idx] |= 1 << bit_idx
        else:
            data[byte_idx] &= ~(1 << bit_idx)


# ── Public API ───────────────────────────────────────────────────────────────


def is_mp3_file(path: str) -> bool:
    """Return True if *path* has an MP3 file extension.

    Args:
        path: Absolute or relative file path.

    Returns:
        True when the extension is ``.mp3`` (case-insensitive).
    """
    return os.path.splitext(path)[1].lower() in _MP3_EXTENSIONS


def calculate_gain_delta(replaygain_track_gain_db: float) -> int:
    """Convert a ReplayGain dB value to a global_gain delta.

    A positive ``replaygain_track_gain_db`` means the file is too quiet
    and needs to be made louder.  The global_gain field *increases* with
    louder output, so the delta is positive for positive dB values.

    Args:
        replaygain_track_gain_db: Gain in dB (e.g. ``+2.34`` means the file
            needs 2.34 dB more gain).

    Returns:
        Integer delta to add to each frame's global_gain (each unit ≈ 1.505 dB).
    """
    return int(round(replaygain_track_gain_db * _GAIN_UNITS_PER_DB))


def read_mp3_global_gains(path: str) -> list[int]:
    """Read every ``global_gain`` field in the MPEG Layer III frames of *path*.

    Walks the file byte-by-byte looking for valid sync words.  Xing/Info
    and VBRI header frames are skipped.

    Args:
        path: Absolute path to an MP3 file.

    Returns:
        List of global_gain values (0–255), **one per global_gain field** —
        a frame contributes ``nch × ngranules`` entries (4 for MPEG-1 stereo,
        2 for MPEG-1 mono and MPEG-2/2.5 stereo, 1 for MPEG-2/2.5 mono).

    Raises:
        AudioFormatError: If the file contains no valid MPEG frames.
        OSError: If the file cannot be read.
    """
    gains: list[int] = []
    with open(path, "rb") as fh:
        data = bytearray(fh.read())

    _walk_frames(
        data,
        lambda _offset, _header, _frame_size, gg_bit_offs: gains.extend(
            _read_bits(data, off, 8) for off in gg_bit_offs
        ),
    )

    if not gains:
        raise AudioFormatError(
            f"No valid MPEG Layer III frames found in: {path}",
            context={"file": path},
        )
    return gains


def get_frame_count(path: str) -> int:
    """Return the number of valid MPEG Layer III audio frames in *path*.

    Xing/Info and VBRI header frames are not counted.

    Args:
        path: Absolute path to an MP3 file.

    Returns:
        Frame count.

    Raises:
        AudioFormatError: If no valid frames are found.
        OSError: If the file cannot be read.
    """
    with open(path, "rb") as fh:
        data = bytearray(fh.read())

    holder = [0]

    def _count(
        _offset: int, _header: int, _frame_size: int, _gg_bit_offs: list[int]
    ) -> None:
        holder[0] += 1

    _walk_frames(data, _count)

    if holder[0] == 0:
        raise AudioFormatError(
            f"No valid MPEG Layer III frames found in: {path}",
            context={"file": path},
        )
    return holder[0]


def apply_track_gain(path: str, gain_delta_db: float) -> int:
    """Apply a uniform gain adjustment to every frame in a single MP3 file.

    Modifies **all** ``global_gain`` fields (every granule and channel) in
    each frame's side information in-place.  The file is read/written in
    binary mode; no audio decoding occurs.

    Args:
        path: Absolute path to an MP3 file.
        gain_delta_db: Gain change in dB.  Positive values increase
            loudness; negative values decrease it.

    Returns:
        Number of frames whose gain fields were modified.

    Raises:
        AudioFormatError: If the file contains no valid MPEG frames.
        OSError: If the file cannot be read or written.
    """
    delta = calculate_gain_delta(gain_delta_db)
    if delta == 0:
        return 0

    with open(path, "r+b") as fh:
        frames_seen, modified = _modify_mp3_gains(fh, delta)

    if frames_seen == 0:
        raise AudioFormatError(
            f"No valid MPEG Layer III frames found in: {path}",
            context={"file": path},
        )
    # Frames were walked but none changed: every field is already at the clamp
    # bound.  This is a valid "no change" outcome, not an unreadable file.
    if modified == 0:
        logger.info(
            "No gain change required for %s (already at the gain limit)",
            path,
        )
        return 0
    # Snapshot only after the walk validated the frames — an invalid or
    # rejected file must never leave an undo row for a file that did not
    # change.
    record_tag_edit_snapshot(path, "lossless_gain_track")
    logger.info(
        "Applied %.2f dB track gain to %s (%d frames)",
        gain_delta_db,
        path,
        modified,
    )
    return modified


def apply_album_gain(file_paths: list[str], album_gain_db: float) -> dict[str, int]:
    """Apply the same gain adjustment to every frame across multiple MP3 files.

    This implements album-gain mode: every file in the album gets the same
    delta so the relative levels between tracks are preserved.

    Args:
        file_paths: List of absolute paths to MP3 files in the album.
        album_gain_db: Gain change in dB applied uniformly to all files.

    Returns:
        Mapping of file path to number of frames modified.

    Raises:
        AudioFormatError: If any file contains no valid MPEG frames.
        OSError: If any file cannot be read or written.
    """
    delta = calculate_gain_delta(album_gain_db)
    if delta == 0:
        return {p: 0 for p in file_paths}

    results: dict[str, int] = {}
    for path in file_paths:
        with open(path, "r+b") as fh:
            frames_seen, count = _modify_mp3_gains(fh, delta)
        if frames_seen == 0:
            raise AudioFormatError(
                f"No valid MPEG Layer III frames found in: {path}",
                context={"file": path},
            )
        # Frames were walked but none changed: the file is already at the
        # gain limit.  Record a zero-change result, not a failure.
        if count == 0:
            logger.info(
                "No gain change required for %s (already at the gain limit)",
                path,
            )
            results[path] = 0
            continue
        # Snapshot only after the walk validated the frames (P3 ordering).
        record_tag_edit_snapshot(path, "lossless_gain_album")
        results[path] = count

    logger.info(
        "Applied %.2f dB album gain to %d files",
        album_gain_db,
        len(file_paths),
    )
    return results


# ── Internal helpers ─────────────────────────────────────────────────────────


def _side_info_size(version: int, channel_mode: int) -> int:
    """Return side information size in bytes for the given frame type.

    Args:
        version: MPEG version bits (0b00=MPEG-2.5, 0b10=MPEG-2, 0b11=MPEG-1).
        channel_mode: Channel mode bits (0b00=stereo, 0b01=joint, 0b10=dual, 0b11=mono).
    """
    if version == 0b11:  # MPEG-1
        return 17 if channel_mode == 0b11 else 32
    # MPEG-2 / MPEG-2.5
    return 9 if channel_mode == 0b11 else 17


def _side_info_layout(version: int, channel_mode: int) -> tuple[int, int, int]:
    """Return (first global_gain bit, stride, field count) for a frame type.

    See the module docstring for the full layout derivation.  The stride is
    constant because both window-switching branches of the per-block side
    info are 22 bits wide, making every (granule, channel) block exactly
    59 bits (MPEG-1) or 63 bits (MPEG-2/2.5).

    Args:
        version: MPEG version bits (0b00=MPEG-2.5, 0b10=MPEG-2, 0b11=MPEG-1).
        channel_mode: Channel mode bits (0b00=stereo, 0b01=joint, 0b10=dual, 0b11=mono).

    Returns:
        Tuple of (bit offset of granule-0/channel-0 global_gain from the
        side info start, stride between consecutive global_gain fields,
        number of global_gain fields per frame).
    """
    if version == 0b11:  # MPEG-1
        if channel_mode == 0b11:  # mono: mdb 9 + private 5 + scfsi 4
            return 9 + 5 + 4 + 21, 59, 2
        # stereo/joint/dual: mdb 9 + private 3 + scfsi 8
        return 9 + 3 + 8 + 21, 59, 4
    # MPEG-2 / MPEG-2.5: mdb 8, no scfsi, private 1 (mono) / 2 (stereo)
    if channel_mode == 0b11:
        return 8 + 1 + 21, 63, 1
    return 8 + 2 + 21, 63, 2


def _gg_bit_offsets(side_start_bit: int, version: int, channel_mode: int) -> list[int]:
    """Return absolute bit offsets of every global_gain field in a frame."""
    first, stride, count = _side_info_layout(version, channel_mode)
    return [side_start_bit + first + i * stride for i in range(count)]


def _is_valid_mpeg_frame(header: int) -> bool:
    """Check whether *header* looks like a valid MPEG Layer III frame header.

    Validates sync word, MPEG version, and Layer bits.
    """
    if (header & 0xFFE00000) != 0xFFE00000:
        return False
    version = (header >> 19) & 0x3
    if version == 0b01:  # reserved
        return False
    layer = (header >> 17) & 0x3
    if layer != 0b01:  # not Layer III
        return False
    return True


def _frame_size(header: int) -> int:
    """Calculate the byte length of the frame starting at *header*.

    Returns 0 if the bitrate or sample rate index is reserved/zero.

    Layer III frames carry 1152 samples (MPEG-1) or 576 samples (MPEG-2/2.5),
    giving the 144 / 72 byte coefficients below.
    """
    version = (header >> 19) & 0x3
    layer = (header >> 17) & 0x3
    bitrate_idx = (header >> 12) & 0xF
    samplerate_idx = (header >> 10) & 0x3
    padding = (header >> 9) & 0x1

    if layer != 0b01:
        return 0

    if version == 0b11:  # MPEG-1
        kbps = _BITRATE_V1_KBPS.get(bitrate_idx, 0)
        sr = _SAMPLE_RATES_V1.get(samplerate_idx, 0)
        coeff = 144
    elif version == 0b10:  # MPEG-2
        kbps = _BITRATE_LSF_KBPS.get(bitrate_idx, 0)
        sr = _SAMPLE_RATES_MPEG2.get(samplerate_idx, 0)
        coeff = 72
    else:  # MPEG-2.5
        kbps = _BITRATE_LSF_KBPS.get(bitrate_idx, 0)
        sr = _SAMPLE_RATES_MPEG25.get(samplerate_idx, 0)
        coeff = 72

    if kbps == 0 or sr == 0:
        return 0

    return int(coeff * kbps * 1000 / sr) + padding


def _is_xing_or_info_header(data: bytearray, sync_offset: int, header: int) -> bool:
    """Detect Xing, Info, or VBRI header frames.

    ``Xing``/``Info`` tags sit directly after the side information;
    the Fraunhofer ``VBRI`` tag sits at a fixed 32-byte offset from the
    frame header regardless of frame type.

    Args:
        data: Full file contents as a mutable byte array.
        sync_offset: Byte offset of the frame's sync word.
        header: The 32-bit frame header value.

    Returns:
        True if this is a Xing/Info/VBRI header frame.
    """
    version = (header >> 19) & 0x3
    channel_mode = (header >> 6) & 0x3
    side_size = _side_info_size(version, channel_mode)

    xing_offset = sync_offset + 4 + side_size
    if xing_offset + 4 <= len(data):
        tag = bytes(data[xing_offset : xing_offset + 4])
        if tag in (b"Xing", b"Info"):
            return True

    vbri_offset = sync_offset + 4 + 32
    if vbri_offset + 4 <= len(data):
        tag = bytes(data[vbri_offset : vbri_offset + 4])
        if tag == b"VBRI":
            return True

    return False


def _walk_frames(
    data: bytearray,
    callback: Callable[[int, int, int, list[int]], None] | None = None,
) -> int:
    """Walk all valid MPEG Layer III frames in *data*.

    For each frame, calls ``callback(frame_offset, header, frame_size,
    gain_bit_offsets)`` if provided, where ``gain_bit_offsets`` lists the
    absolute bit offset of **every** global_gain field (all granules and
    channels).  Skips Xing/Info/VBRI header frames.

    Raises ``AudioFormatError`` for a file whose frames cannot be walked
    safely: CRC-protected frames (a 16-bit CRC after the header shifts the
    side info) and free-format frames (undefined frame size).  The walk
    stops at the first such frame, so callers that apply modifications on a
    buffered copy leave the on-disk file untouched when this raises.

    Args:
        data: Full file contents as a byte array.
        callback: Optional callable receiving frame metadata.

    Returns:
        Number of audio frames walked (Xing/Info/VBRI header frames and
        non-frame bytes are not counted).  Zero means the file carries no
        valid MPEG Layer III audio frames.
    """
    length = len(data)
    pos = 0
    frames_walked = 0

    while pos < length - 4:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue

        header = struct.unpack(">I", bytes(data[pos : pos + 4]))[0]
        if not _is_valid_mpeg_frame(header):
            pos += 1
            continue

        if not header & _HEADER_CRC_PROTECTION_BIT:
            raise AudioFormatError(
                "CRC-protected MPEG frames are not supported: a 16-bit CRC "
                "check word follows each frame header, shifting every "
                "side-info offset by 16 bits. Re-encode without CRC "
                "protection or use a different format."
            )

        if (header >> 12) & 0xF == 0:
            raise AudioFormatError(
                "Free-format MPEG frames are not supported: the frame size "
                "cannot be derived from the header (bitrate index 0). "
                "Re-encode at a fixed bitrate or use a different format."
            )

        size = _frame_size(header)

        if _is_xing_or_info_header(data, pos, header):
            pos += size if size > 0 else 4
            continue

        version = (header >> 19) & 0x3
        channel_mode = (header >> 6) & 0x3
        gg_bit_offs = _gg_bit_offsets((pos + 4) * 8, version, channel_mode)

        if callback is not None:
            callback(pos, header, size if size > 0 else 0, gg_bit_offs)
        frames_walked += 1

        pos += size if size > 0 else 4

    return frames_walked


def _modify_mp3_gains(fh: BinaryIO, delta: int) -> tuple[int, int]:
    """Modify every global_gain field in every frame by *delta*, in-place.

    Each frame carries multiple global_gain fields (2 granules × n channels
    for MPEG-1, 1 granule × n channels for MPEG-2/2.5); all of them are
    adjusted so the per-channel balance is preserved.

    Args:
        fh: Open ``r+b`` file handle.
        delta: Integer gain delta to add to each frame's global_gain fields.

    Returns:
        ``(frames_seen, modified)`` where ``frames_seen`` is the number of
        valid audio frames walked and ``modified`` is the number of frames
        in which at least one field actually changed.  ``frames_seen == 0``
        means the file carries no valid MPEG Layer III audio frames;
        ``frames_seen > 0 and modified == 0`` means the file is already at
        the gain clamp bound (a no-op, not an error).
    """
    fh.seek(0)
    data = bytearray(fh.read())
    modified = 0

    def _modify(
        _offset: int,
        _header: int,
        _frame_size: int,
        gg_bit_offs: list[int],
    ) -> None:
        nonlocal modified, data
        frame_changed = False
        for gain_bit_off in gg_bit_offs:
            old_gain = _read_bits(data, gain_bit_off, 8)
            new_gain = max(_MIN_GLOBAL_GAIN, min(_MAX_GLOBAL_GAIN, old_gain + delta))
            if new_gain != old_gain:
                _write_bits(data, gain_bit_off, 8, new_gain)
                frame_changed = True
        if frame_changed:
            modified += 1

    frames_seen = _walk_frames(data, _modify)

    if modified > 0:
        fh.seek(0)
        fh.write(bytes(data))

    return frames_seen, modified
