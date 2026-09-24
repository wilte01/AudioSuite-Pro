"""
accuraterip.py  –  Clean-room AccurateRip verification client.

Computes the AccurateRip Disc ID and the per-track AccurateRip v1/v2
checksums from raw CDDA PCM, queries the public AccurateRip database
("ARL") endpoint, and produces a typed, first-class verification result
for each track.

Protocol summary (learned from the public reference implementations —
Leo Bogert's ``accuraterip-checksum.c`` v1.4, whipper's
``common/accurip.py`` and audiotools' ``accuraterip`` module; this is a
clean-room client, no reference code is copied):

* Disc ID: ``discId1`` is the sum of all track index-1 offsets (program-
  area relative, lead-in excluded, exactly the ``start_lba`` values this
  ripper reads from TOC) plus the lead-out LBA. ``discId2`` additionally
  weights each track by its 1-based track number (a zero first-track
  offset counts as 1) and adds ``leadout * (track_count + 1)``. All
  arithmetic wraps mod 2^32. The CDDB/freedb disc id is derived from the
  ``+150``-shifted offsets. The URL path embeds the three least
  significant hex digits of ``discId1`` (least significant first).
* Checksum: NOT zlib CRC-32. Each 16-bit stereo CDDA frame is packed as
  ``(unsigned16(R) << 16) | unsigned16(L)`` (the natural little-endian
  DWORD read of the byte stream). Positions restart at 1 for every track.
  The first 2939 frames of track 1 are ignored (AccurateRip tolerates a
  leading capture offset) and the last 2940 frames of the last track are
  ignored. v1 accumulates ``position * frame`` mod 2^32; v2 accumulates
  ``high32(product) + low32(product)`` mod 2^32.
* Database payload: one record per disc — 1 byte track count, three
  little-endian lens (discId1, discId2, cddb id), then 9 bytes per track
  (1 confidence byte, 4-byte LE CRC1, 4-byte LE CRC2). Multiple disc
  records are concatenated in a single .bin response.

Network failures and "no entry" conditions are deliberately first-class
result types (never an opaque exception), so the ripper can degrade to a
local-only "rip twice" verification when the database cannot answer.
"""

from __future__ import annotations

import logging as _logging
import struct
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

import numpy as np
import numpy.typing as npt
import requests

ACCURATERIP_URL = "http://www.accuraterip.com/accuraterip/"
DEFAULT_TIMEOUT_SECS = 10.0
DEFAULT_USER_AGENT = "AudioSuite-Pro-CDRipper/1.0"

FRAMES_PER_SECTOR = 588
EDGE_SKIP_FRAMES = 5 * FRAMES_PER_SECTOR  # 2940
FIRST_TRACK_SKIP_FRAMES = EDGE_SKIP_FRAMES - 1  # 2939
_MASK32 = 0xFFFFFFFF
_CHUNK_FRAMES = 1 << 20

logger = _logging.getLogger(__name__)


# ── Disc ID ────────────────────────────────────────────────────────────────


def _digit_sum(value: int) -> int:
    total = 0
    while value:
        total += value % 10
        value //= 10
    return total


@dataclass(frozen=True)
class DiscIds:
    """AccurateRip disc identifiers for one CD.

    Attributes:
        disc_id1: AccurateRip internal disc id 1 (``sum(offsets) + leadout``).
        disc_id2: AccurateRip internal disc id 2 (track-weighted variant).
        cddb_id: The freedb/CDDB disc id used in the database key.
        track_count: Number of non-hidden tracks (HTOA is never counted).
    """

    disc_id1: int
    disc_id2: int
    cddb_id: int
    track_count: int

    @property
    def accuraterip_path(self) -> str:
        """Database-relative path (``dBAR-...bin`` under three id1 dirs).

        The path directories are the three least significant hex digits of
        disc_id1, most significant of the three first (matches both whipper's
        ``accuraterip_path`` and audiotools' URL construction).
        """
        id1_hex = f"{self.disc_id1:08x}"
        dbar = (
            f"dBAR-{self.track_count:03d}-{self.disc_id1:08x}-"
            f"{self.disc_id2:08x}-{self.cddb_id:08x}.bin"
        )
        return "/".join((id1_hex[-1], id1_hex[-2], id1_hex[-3], dbar))


def compute_disc_ids(track_start_lbas: Sequence[int], leadout_lba: int) -> DiscIds:
    """Compute the AccurateRip/CDDB identifiers for a disc from its TOC.

    Args:
        track_start_lbas: Per-track start LBAs as read by ``read_toc`` —
            program-area relative (lead-in already subtracted, MSF - 150),
            matching the index-1 offsets used by all reference rippers.
        leadout_lba: Lead-out LBA in the same program-relative frame as the
            track offsets (last track ``start_lba + sectors``).

    Returns:
        The three disc identifiers plus the track count.
    """
    starts = [max(offset, 0) for offset in track_start_lbas]
    track_count = len(starts)
    if track_count == 0:
        raise ValueError("disc with no tracks cannot produce an AccurateRip id")

    disc_id1 = (sum(starts) + leadout_lba) & _MASK32
    disc_id2 = sum((offset or 1) * index for index, offset in enumerate(starts, 1))
    disc_id2 = (disc_id2 + leadout_lba * (track_count + 1)) & _MASK32

    offsetsum = sum(_digit_sum((offset + 150) // 75) for offset in starts)
    track_seconds = (leadout_lba // 75) - (starts[0] // 75)
    cddb_id = (
        ((offsetsum % 255) << 24)
        | ((track_seconds & 0xFFFF) << 8)
        | (track_count & 0xFF)
    ) & _MASK32

    return DiscIds(disc_id1, disc_id2, cddb_id, track_count)


# ── Per-track checksums ────────────────────────────────────────────────────


@dataclass(frozen=True)
class TrackChecksums:
    """The two AccurateRip checksums for one track window.

    Attributes:
        crc1: AccurateRip v1 checksum (position-weighted sum, mod 2^32).
        crc2: AccurateRip v2 checksum (sum of high+low halves of the
            position-weighted products, mod 2^32).
    """

    crc1: int
    crc2: int


def _checksum_window(
    frames_total: int, track_number: int, track_count: int
) -> tuple[int, int]:
    """Return the inclusive-start / exclusive-end frame indices to hash.

    Mirrors the reference skip semantics: the first 2939 frames of track 1
    and the last 2940 frames of the last track are ignored (positions, as
    counted from 1 for the track's own window, are the actual gate -- see
    ``compute_track_checksums``).
    """
    start_idx = FIRST_TRACK_SKIP_FRAMES if track_number == 1 else 0
    end_idx = frames_total - (EDGE_SKIP_FRAMES if track_number == track_count else 0)
    return start_idx, max(end_idx, 0)


def compute_track_checksums(
    pcm_data: bytes, track_number: int, track_count: int
) -> TrackChecksums:
    """Compute AccurateRip v1/v2 checksums for one track window.

    ``pcm_data`` is the raw CDDA byte stream for the track as defined by the
    TOC (from the track's index-1 start LBA to the next track's index-1 or
    the lead-out), 2352 bytes per sector, little-endian 16-bit L/R pairs.

    Args:
        pcm_data: Raw 44.1 kHz stereo 16-bit PCM, 4 bytes per frame.
        track_number: 1-based track number on the disc (TOC track number).
        track_count: Total number of non-hidden tracks on the disc.

    Returns:
        The (v1, v2) checksum pair; both zero for windows fully covered by
        the edge-skips.

    Raises:
        ValueError: If ``pcm_data`` length is not a whole number of frames.
    """
    if len(pcm_data) % 4:
        raise ValueError(
            f"pcm_data length {len(pcm_data)} is not a multiple of 4 bytes"
        )
    frames: npt.NDArray[np.uint32] = np.frombuffer(pcm_data, dtype="<u4")
    start_idx, end_idx = _checksum_window(int(frames.size), track_number, track_count)
    v1 = 0
    v2 = 0
    for lo in range(start_idx, end_idx, _CHUNK_FRAMES):
        hi = min(lo + _CHUNK_FRAMES, end_idx)
        values = frames[lo:hi]
        positions: npt.NDArray[np.uint64] = np.arange(lo + 1, hi + 1, dtype=np.uint64)
        products: npt.NDArray[np.uint64] = positions * values.astype(np.uint64)
        low: npt.NDArray[np.uint64] = products & np.uint64(_MASK32)
        high: npt.NDArray[np.uint64] = products >> np.uint64(32)
        v1 = (v1 + int(np.sum(low))) & _MASK32
        v2 = (v2 + int(np.sum(low + high))) & _MASK32
    return TrackChecksums(v1, v2)


def with_gap_window(
    track_pcm: bytes,
    prev_tail_pcm: bytes | None,
    next_head_pcm: bytes | None,
) -> bytes:
    """Merge the surrounding gap frames into an offset-tolerant context.

    AccurateRip matches can be reconciled across drive read offsets by
    submitting a context window of the previous track's final frames, the
    track itself, and the next track's opening frames (audiotools builds the
    same ``2940 + 1 + 2940`` frame range). Earlier/later tracks pass ``None``
    for the absent neighbour; silence is implied by the gap in the physical
    disc layout and is not padded here.

    Args:
        track_pcm: The track's own window.
        prev_tail_pcm: End of the previous track (its last
            ``EDGE_SKIP_FRAMES`` frames are used), or None for track 1.
        next_head_pcm: Start of the next track (its first
            ``EDGE_SKIP_FRAMES`` frames are used), or None for the last.

    Returns:
        ``prev_tail[-2940 frames] + track + next_head[:2940 frames]``.
    """
    tail = prev_tail_pcm[-(EDGE_SKIP_FRAMES * 4) :] if prev_tail_pcm else b""
    head = next_head_pcm[: EDGE_SKIP_FRAMES * 4] if next_head_pcm else b""
    return b"".join((tail, track_pcm, head))


# ── Database payload parsing ───────────────────────────────────────────────


@dataclass(frozen=True)
class DBTrackEntry:
    """One track record inside an AccurateRip database response.

    Attributes:
        confidence: Number of rips that agreed on these checksums.
        crc1: AccurateRip v1 checksum stored for this track.
        crc2: AccurateRip v2 checksum stored for this track.
    """

    confidence: int
    crc1: int
    crc2: int


@dataclass(frozen=True)
class DBEntry:
    """One parsed disc record from an AccurateRip database response.

    Attributes:
        disc_id1: discId1 as unpacked from the record header.
        disc_id2: discId2 as unpacked from the record header.
        cddb_id: freedb disc id as unpacked from the record header.
        tracks: Per-track records indexed by relative position
            (track 1 -> index 0); HTOA is excluded, matching the database.
    """

    disc_id1: int
    disc_id2: int
    cddb_id: int
    tracks: tuple[DBTrackEntry, ...]


def parse_db_entry(data: bytes) -> DBEntry:
    """Parse exactly one disc record from ``data`` (first entry only).

    Raises:
        ValueError: If the record is truncated or its declared track count
            exceeds the available bytes.
    """
    if len(data) < 13:
        raise ValueError(f"AccurateRip record too short: {len(data)} bytes (< 13)")
    track_count = data[0]
    required = 13 + track_count * 9
    if len(data) < required:
        raise ValueError(
            f"AccurateRip record truncated: {len(data)} bytes, need {required}"
        )
    disc_id1 = struct.unpack_from("<I", data, 1)[0]
    disc_id2 = struct.unpack_from("<I", data, 5)[0]
    cddb_id = struct.unpack_from("<I", data, 9)[0]
    tracks: list[DBTrackEntry] = []
    pos = 13
    for _ in range(track_count):
        confidence = data[pos]
        crc1 = struct.unpack_from("<I", data, pos + 1)[0]
        crc2 = struct.unpack_from("<I", data, pos + 5)[0]
        tracks.append(DBTrackEntry(confidence, crc1, crc2))
        pos += 9
    return DBEntry(disc_id1, disc_id2, cddb_id, tuple(tracks))


def parse_db_payload(data: bytes) -> tuple[DBEntry, ...]:
    """Parse all concatenated disc records from an ARL ``.bin`` payload.

    Returns:
        One :class:`DBEntry` per disc record in the response. An empty body
        yields no entries; a trailing byte fragment that cannot form a whole
        record is dropped with a warning.

    Raises:
        ValueError: If the first record is malformed -- the caller treats
            this as an unusable (offline-class) response.
    """
    if not data:
        return ()
    entries: list[DBEntry] = []
    pos = 0
    while pos < len(data):
        track_count = data[pos]
        record_size = 13 + track_count * 9
        if pos + record_size > len(data):
            if pos == 0:
                raise ValueError(
                    "AccurateRip record truncated: "
                    f"{len(data) - pos} trailing byte(s) cannot form a record"
                )
            logger.warning(
                "Trailing %d byte(s) cannot form an AccurateRip record; dropping them",
                len(data) - pos,
            )
            break
        entries.append(parse_db_entry(data[pos : pos + record_size]))
        pos += record_size
    return tuple(entries)


# ── HTTP client ────────────────────────────────────────────────────────────


class LookupResult:
    """Base marker for the three distinct AccurateRip lookup outcomes."""


@dataclass(frozen=True)
class LookupFound(LookupResult):
    """The database answered with at least one disc record."""

    entries: tuple[DBEntry, ...]
    url: str


@dataclass(frozen=True)
class LookupNotFound(LookupResult):
    """The database has no entry for this disc (an empty record body is
    treated the same way)."""

    reason: str


@dataclass(frozen=True)
class LookupOffline(LookupResult):
    """The database could not be queried (network failure, HTTP error, or
    an unparseable response)."""

    reason: str


class AccurateRipClient:
    """Small ``requests``-based client for the AccurateRip database.

    Every network/parsing failure is reported as a typed result, never an
    exception, so callers can deliberately degrade to local verification.
    """

    def __init__(
        self,
        request_timeout: float = DEFAULT_TIMEOUT_SECS,
        base_url: str = ACCURATERIP_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        session: requests.Session | None = None,
    ) -> None:
        self._request_timeout = request_timeout
        self._base_url = base_url
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent})

    def resolve(self, db_path: str) -> LookupResult:
        """Fetch and parse the database entry at ``db_path``.

        Args:
            db_path: The result of ``DiscIds.accuraterip_path``.

        Returns:
            ``LookupFound`` with all disc records, ``LookupNotFound`` when the
            disc is not present, or ``LookupOffline`` when the query failed.
        """
        url = self._base_url + db_path
        try:
            response = self._session.get(url, timeout=self._request_timeout)
        except requests.RequestException as exc:
            logger.warning("AccurateRip lookup failed for %s: %s", url, exc)
            return LookupOffline(reason=f"Network error querying {url}: {exc}")

        if response.status_code == 404:
            logger.debug("AccurateRip: no entry for %s (%s)", url, db_path)
            return LookupNotFound(reason="Disc has no AccurateRip database entry")

        if response.status_code != 200:
            logger.warning(
                "AccurateRip returned HTTP %s for %s",
                response.status_code,
                url,
            )
            return LookupOffline(
                reason=f"AccurateRip returned HTTP {response.status_code}"
            )

        if not response.content:
            logger.debug("AccurateRip: empty payload for %s", url)
            return LookupNotFound(reason="AccurateRip returned an empty payload")

        try:
            entries = parse_db_payload(response.content)
        except Exception as exc:
            logger.warning("AccurateRip payload unparseable for %s: %s", url, exc)
            return LookupOffline(reason=f"Malformed AccurateRip payload: {exc}")
        if not entries:
            return LookupNotFound(reason="AccurateRip returned no usable records")
        return LookupFound(entries=entries, url=url)


# ── Matching ───────────────────────────────────────────────────────────────


class VerificationStatus(str, Enum):
    """Per-track outcome surfaced to the CLI and results tab."""

    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    NO_ENTRY = "NO_ENTRY"
    OFFLINE = "OFFLINE"


def verify_track(
    local: TrackChecksums,
    db_entries: Sequence[DBEntry],
    track_index: int,
) -> VerificationStatus:
    """Match one track's checksums against the database records.

    Args:
        local: Checksums computed from the rip.
        db_entries: All disc records returned for this disc.
        track_index: 0-based relative track position (track number - 1; the
            database excludes HTOA, so the TOC track number maps directly).

    Returns:
        ``VERIFIED`` when any record holds a matching v1 or v2 checksum for
        this track (with any confidence >= 1), else ``MISMATCH``.
    """
    for entry in db_entries:
        if track_index >= len(entry.tracks):
            continue
        db_track = entry.tracks[track_index]
        if local.crc1 == db_track.crc1 or local.crc2 == db_track.crc2:
            return VerificationStatus.VERIFIED
    return VerificationStatus.MISMATCH
