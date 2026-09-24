"""read_offset.py — per-drive read-offset configuration and read alignment.

A CD drive can deliver its raw audio stream a fixed number of frames early
or late relative to the LBA it was asked for ("drive read offset").
EAC-style rippers measure it once per drive and compensate so ripped frames
line up with the reference sector grid; without it every AccurateRip window
is shifted off the database vectors and every track reports an incorrect
MISMATCH.

This was diagnosed live on drive E: of this suite. For that drive,
``read(LBA L)`` returns content whose first frame is physical frame
``L * 588 - 6``, i.e. the stream leads the requested LBA by 6 frames. The
empirically verified construction is: for any read starting at
``read_start_lba``, raw frame index ``k`` holds physical frame
``read_start_lba + k - offset_frames``.

This module stores the per-drive offset (whole CDDA frames, 1/75 s) in the
shared suite config and computes the *read layout* that converts a
possibly-mis-aligned raw read into the track window: the sector to start
reading at, how many sectors to read, how many leading bytes to discard,
and — for the final track, whose shifted tail would need a past-lead-out
read the drive refuses — how short the aligned tail will be.

Only non-negative offsets are supported: the drive that prompted this module
leads the grid (+6), and a stored offset outside ``[0, FRAMES_PER_SECTOR]``
is treated as unset.
"""

from __future__ import annotations

from dataclasses import dataclass

from audio_suite_shared.exceptions import AudioConfigurationError
from audio_suite_shared.suite_config import (
    load_value as load_value,
)
from audio_suite_shared.suite_config import (
    save_value as save_value,
)
from cd_ripper.core.accuraterip import FRAMES_PER_SECTOR
from cd_ripper.core.drive_handler import SECTOR_SIZE

READ_OFFSET_CONFIG_KEY = "cd_ripper.read_offset_frames"

_BYTES_PER_FRAME = 4


@dataclass(frozen=True)
class TrackReadLayout:
    """Where to read and how to trim so a raw read yields the track window.

    Attributes:
        read_start_lba: LBA the raw read must start at (may differ from the
            track's nominal start for the aligned window).
        read_sectors: Number of sectors to read from ``read_start_lba``
            (>= the track's own sector count when an offset is applied).
        skip_bytes: Leading bytes of the raw read to discard before the
            aligned window begins.
        tail_shortfall_bytes: How many trailing bytes the aligned window
            is short of ``sectors * SECTOR_SIZE``. Non-zero for the final
            track whenever an offset is applied: recovering the shifted
            tail would require reading past the lead-out, which drives
            refuse. AccurateRip's last-track skip window (final 2940
            frames) tolerates the shortfall.
    """

    read_start_lba: int
    read_sectors: int
    skip_bytes: int
    tail_shortfall_bytes: int = 0


# ── Per-drive config ──────────────────────────────────────────────────────


def _normalize_drive(drive_letter: str) -> str:
    """Canonicalise a drive specifier ('E:', 'E', 'E:\\') to a bare letter."""
    return drive_letter.rstrip(":/\\").upper()


def get_read_offset_frames(drive_letter: str) -> int:
    """Return the stored read offset for ``drive_letter`` (frames), 0 if unset.

    Values are whole frames, validated against ``[0, FRAMES_PER_SECTOR]``;
    a corrupted or out-of-range stored value is treated as 0.
    """
    drive = _normalize_drive(drive_letter)
    per_drive = load_value(READ_OFFSET_CONFIG_KEY, {})
    if not isinstance(per_drive, dict):
        return 0
    raw: object = per_drive.get(drive, 0)
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    if raw < 0 or raw > FRAMES_PER_SECTOR:
        return 0
    return raw


def set_read_offset_frames(drive_letter: str, offset_frames: int) -> None:
    """Persist ``offset_frames`` for ``drive_letter``, preserving other drives.

    Raises:
        AudioConfigurationError: If ``offset_frames`` falls outside
            ``[0, FRAMES_PER_SECTOR]``.
    """
    if offset_frames < 0 or offset_frames > FRAMES_PER_SECTOR:
        raise AudioConfigurationError(
            "read offset must be within 0..FRAMES_PER_SECTOR frames "
            f"({FRAMES_PER_SECTOR}), got {offset_frames}"
        )
    drive = _normalize_drive(drive_letter)
    per_drive = load_value(READ_OFFSET_CONFIG_KEY, {})
    if not isinstance(per_drive, dict):
        per_drive = {}
    per_drive = dict(per_drive)
    if offset_frames:
        per_drive[drive] = offset_frames
    else:
        per_drive.pop(drive, None)
    save_value(READ_OFFSET_CONFIG_KEY, per_drive)


# ── Read layout ───────────────────────────────────────────────────────────


def compute_track_read_layout(
    start_lba: int,
    sectors: int,
    offset_frames: int,
    is_last_track: bool,
) -> TrackReadLayout:
    """Compute the read parameters that yield the exact track window.

    The drive model (empirically verified on all three track positions —
    first, middle, and last): raw frame ``k`` of a read that starts at
    ``read_start_lba`` holds physical frame
    ``read_start_lba * 588 + k - offset_frames``.

    * No offset: read the nominal extent and trim nothing.
    * Non-last track with offset: reading from ``start_lba``, the nominal
      window ``phys[start, start + sectors)`` begins at raw frame
      ``offset_frames``; one extra tail sector is read (it lies inside the
      next track) so the shifted end is covered. Track 1 at LBA 0 is
      included: the drive delivers lead-in content for the pre-window
      frames (verified empirically).
    * Last track with offset: the extra tail sector would cross into the
      lead-out, which drives refuse (SCSI status 2). The window is read
      from the nominal start and the aligned tail falls short by
      ``offset_frames`` frames — entirely inside the AccurateRip
      last-track skip window (final 2940 frames), so verification stays
      exact; the extracted audio is short by the same ``offset_frames``
      frames, the same compromise EAC makes for non-overreading drives.

    Args:
        start_lba: Track's nominal index-1 LBA.
        sectors: Track length in sectors.
        offset_frames: Drive read offset in frames (0 = no correction).
        is_last_track: Whether this track is the final track on the disc.

    Returns:
        The ``TrackReadLayout`` for the raw read plus trimming.
    """
    if offset_frames <= 0:
        return TrackReadLayout(start_lba, sectors, 0, 0)
    if is_last_track:
        skip = offset_frames * _BYTES_PER_FRAME
        return TrackReadLayout(start_lba, sectors, skip, skip)
    return TrackReadLayout(start_lba, sectors + 1, offset_frames * _BYTES_PER_FRAME, 0)


def aligned_track_pcm(raw_pcm: bytes, layout: TrackReadLayout, sectors: int) -> bytes:
    """Extract the aligned track window from ``raw_pcm``.

    Slices ``raw_pcm`` from ``layout.skip_bytes`` for ``sectors * SECTOR_SIZE``
    bytes. If ``raw_pcm`` is shorter than the requested window end (the
    final track of an offset drive, whose shifted tail needs a
    past-lead-out read the drive refuses), returns exactly what is
    available; ``layout.tail_shortfall_bytes`` quantifies the difference
    from the nominal length.
    """
    end = layout.skip_bytes + sectors * SECTOR_SIZE
    return raw_pcm[layout.skip_bytes : end]


def pad_tail_shortfall(pcm: bytes, layout: TrackReadLayout, sectors: int) -> bytes:
    """Zero-pad a short aligned window back to the nominal track length.

    ``compute_track_checksums`` derives its edge-skip boundary from the
    length of the PCM it is handed, so a short final-track window would
    hash fewer frames than the database vector. Padding restores the
    nominal length; because the shortfall can never exceed one sector
    (588 frames) while AccurateRip skips the final 2940 frames of the last
    track, the padded bytes are never hashed and the checksums stay
    byte-identical to the full window's.

    Args:
        pcm: The (possibly short) aligned track window.
        layout: The layout the window was produced with.
        sectors: The track's nominal sector count.

    Returns:
        ``pcm`` when it is already nominal-length, else the zero-padded
        window of exactly ``sectors * SECTOR_SIZE`` bytes.
    """
    nominal = sectors * SECTOR_SIZE
    if len(pcm) >= nominal:
        return pcm
    return pcm + b"\x00" * (nominal - len(pcm))
