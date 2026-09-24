"""
Tests for cd_ripper.core.offset_detect

Coverage strategy
-----------------
- A synthetic mis-aligned drive (raw frame k = phys[read_start*588 + k - o],
  the empirically verified model) serves both the sweep and the production
  confirm phase via a patched ``_read_raw_range``; DB entries are built with
  the REAL ``compute_track_checksums`` over the nominal windows, so a
  positive result proves the whole chain end-to-end.
- The O(1) prefix-sum v1 must equal the production checksum's crc1 on
  identical windows, including both edge-skip variants (first/last track).
- Failure modes: unreadable margin reads, ambiguous (non-unanimous)
  candidates, and empty DB crc sets.
- Geometry safety: no read request may extend past the lead-out.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from cd_ripper.core.accuraterip import (
    EDGE_SKIP_FRAMES,
    FIRST_TRACK_SKIP_FRAMES,
    FRAMES_PER_SECTOR,
    DBEntry,
    DBTrackEntry,
    compute_track_checksums,
)
from cd_ripper.core.offset_detect import (
    ReadOffsetDetectionError,
    _prefix_arrays,
    _read_raw_range,
    _v1_fast,
    _window_bounds,
    detect_read_offset_frames,
    run_read_offset_detection,
)

FRAMES = FRAMES_PER_SECTOR
LEADIN_SECTORS = 16  # readable pre-LBA-0 content the drive model delivers
SLACK_SECTORS = 16

# Three-track disc mirroring a real TOC: track 1 starts at LBA 0.
_TOC = (
    {"number": 1, "start_lba": 0, "end_lba": 99, "sectors": 100},
    {"number": 2, "start_lba": 100, "end_lba": 219, "sectors": 120},
    {"number": 3, "start_lba": 220, "end_lba": 382, "sectors": 163},
)
_LEADOUT_LBA = 383


def _phys_bytes() -> bytes:
    """Deterministic pseudo-random PCM for lead-in + program + slack."""
    total_frames = (LEADIN_SECTORS + _LEADOUT_LBA + SLACK_SECTORS) * FRAMES
    values = np.arange(total_frames, dtype=np.uint64)
    mixed = (values * 2_654_435_761 + 972_613_119) & 0xFFFFFFFF
    return mixed.astype("<u4").tobytes()


def _frame_index(lba: int, frame: int) -> int:
    """Byte-independent frame index into the synthetic physical stream."""
    return (LEADIN_SECTORS + lba) * FRAMES + frame


def _drive_read(phys: bytes, lba: int, count: int, offset: int) -> bytes | None:
    """The empirically verified offset-drive model as a fake raw read.

    Raw frame ``k`` of ``read(lba, count)`` holds physical frame
    ``lba * FRAMES + k - offset``; requests whose stream would exceed the
    available content return ``None`` (the drive refusing past the lead-out).
    """
    start = _frame_index(lba, -offset)
    end = start + count * FRAMES
    if start < 0 or end > len(phys) // 4:
        return None
    return phys[start * 4 : end * 4]


def _nominal_window(phys: bytes, track: dict[str, int]) -> bytes:
    lo = _frame_index(track["start_lba"], 0)
    hi = lo + track["sectors"] * FRAMES
    return phys[lo * 4 : hi * 4]


def _db_entries(phys: bytes) -> tuple[DBEntry, ...]:
    """Entries whose crcs come from the REAL production checksum."""
    tracks = tuple(
        DBTrackEntry(
            confidence=1,
            crc1=compute_track_checksums(
                _nominal_window(phys, t), t["number"], len(_TOC)
            ).crc1,
            crc2=compute_track_checksums(
                _nominal_window(phys, t), t["number"], len(_TOC)
            ).crc2,
        )
        for t in _TOC
    )
    return (DBEntry(disc_id1=0, disc_id2=0, cddb_id=0, tracks=tracks),)


def _run_detection(
    phys: bytes,
    entries: tuple[DBEntry, ...],
    offset: int,
    fail_filter: Callable[[int, int], bool] | None = None,
    requests: list[tuple[int, int]] | None = None,
) -> tuple[int | None, list[str]]:
    """Patch the raw read with the synthetic drive and run detection."""
    logs: list[str] = []

    def fake_read(drive: str, lba: int, count: int) -> bytes | None:
        if requests is not None:
            requests.append((lba, count))
        if fail_filter is not None and fail_filter(lba, count):
            return None
        return _drive_read(phys, lba, count, offset)

    with patch("cd_ripper.core.offset_detect._read_raw_range", side_effect=fake_read):
        result = detect_read_offset_frames("E", _TOC, entries, logs.append)
    return result, logs


# ===========================================================================
# end-to-end detection on the synthetic offset drive
# ===========================================================================


class TestDetectReadOffsetFrames:
    def test_finds_positive_offset(self) -> None:
        phys = _phys_bytes()
        result, logs = _run_detection(phys, _db_entries(phys), offset=6)
        assert result == 6
        assert any("candidate +6" in line for line in logs)

    def test_zero_offset_drive_detects_zero(self) -> None:
        phys = _phys_bytes()
        result, _ = _run_detection(phys, _db_entries(phys), offset=0)
        assert result == 0

    def test_full_band_extremes_are_found(self) -> None:
        phys = _phys_bytes()
        result, _ = _run_detection(phys, _db_entries(phys), offset=587)
        assert result == 587

    def test_unreadable_margin_read_degrades_to_other_tracks(self) -> None:
        phys = _phys_bytes()
        # Track 1's margin read is (0, 116): fail exactly that signature.
        result, logs = _run_detection(
            phys,
            _db_entries(phys),
            offset=6,
            fail_filter=lambda lba, count: (lba, count) == (0, 116),
        )
        assert result == 6
        assert any("skipped for grading" in line for line in logs)

    def test_all_reads_fail_returns_none(self) -> None:
        phys = _phys_bytes()
        result, _ = _run_detection(
            phys, _db_entries(phys), offset=6, fail_filter=lambda _l, _c: True
        )
        assert result is None

    def test_ambiguous_candidates_return_none(self) -> None:
        phys = _phys_bytes()

        def _crc_at_shift(track_idx: int, shift: int) -> int:
            t = _TOC[track_idx]
            lo = _frame_index(t["start_lba"], shift)
            window = phys[lo * 4 : (lo + t["sectors"] * FRAMES) * 4]
            return compute_track_checksums(window, t["number"], len(_TOC)).crc1

        # Track 0 and 2 vote for +6, track 1 for -6: no unanimous candidate.
        tracks = (
            DBTrackEntry(confidence=1, crc1=_crc_at_shift(0, 6), crc2=0),
            DBTrackEntry(confidence=1, crc1=_crc_at_shift(1, -6), crc2=0),
            DBTrackEntry(confidence=1, crc1=_crc_at_shift(2, 6), crc2=0),
        )
        entries = (DBEntry(0, 0, 0, tracks),)
        result, logs = _run_detection(phys, entries, offset=6)
        assert result is None
        assert any("no unanimous candidate" in line for line in logs)

    def test_no_read_request_extends_past_leadout(self) -> None:
        phys = _phys_bytes()
        requests: list[tuple[int, int]] = []
        result, _ = _run_detection(phys, _db_entries(phys), offset=6, requests=requests)
        assert result == 6
        for lba, count in requests:
            assert lba >= 0
            assert lba + count <= _LEADOUT_LBA

    def test_empty_toc_returns_none(self) -> None:
        phys = _phys_bytes()
        logs: list[str] = []
        with patch(
            "cd_ripper.core.offset_detect._read_raw_range",
            side_effect=lambda _d, _l, _c: None,
        ):
            result = detect_read_offset_frames("E", (), _db_entries(phys), logs.append)
        assert result is None

    def test_entries_without_crcs_return_none(self) -> None:
        phys = _phys_bytes()
        empty = (
            DBEntry(
                0,
                0,
                0,
                tuple(DBTrackEntry(confidence=1, crc1=0, crc2=0) for _ in _TOC),
            ),
        )
        result, _ = _run_detection(phys, empty, offset=6)
        assert result is None


# ===========================================================================
# run_read_offset_detection — shared CLI/GUI pipeline
# ===========================================================================


class TestRunReadOffsetDetection:
    """The full pipeline: TOC -> disc ids -> DB lookup -> sweep -> persist.

    Every dependency is a module-level import of ``offset_detect``, so the
    patches target that module's own bindings (the AGENTS.md mock rule).
    """

    def _patches(self, lookup, detected):
        from cd_ripper.core import accuraterip, offset_detect

        ids = accuraterip.DiscIds(
            disc_id1=0x11111111,
            disc_id2=0x22222222,
            cddb_id=0x33333333,
            track_count=3,
        )
        return (
            patch.object(offset_detect, "read_toc", return_value=list(_TOC)),
            patch.object(offset_detect, "compute_disc_ids", return_value=ids),
            patch.object(
                offset_detect,
                "AccurateRipClient",
                return_value=MagicMock(resolve=MagicMock(return_value=lookup)),
            ),
            patch.object(
                offset_detect, "detect_read_offset_frames", return_value=detected
            ),
            patch.object(offset_detect, "set_read_offset_frames"),
        )

    def test_success_returns_and_persists_offset(self) -> None:
        from cd_ripper.core import accuraterip

        found = accuraterip.LookupFound(entries=(), url="http://ar/x.bin")
        p = self._patches(found, 6)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            p[4] as set_off,
        ):
            offset = run_read_offset_detection("E:", lambda _m: None)
        assert offset == 6
        set_off.assert_called_once_with("E", 6)

    def test_drive_letter_is_normalised_for_the_device_layer(self) -> None:
        """Regression: 'E:' passed to _open_device builds the invalid raw
        path '\\\\.\\E::' (Win32 error 2); the pipeline must normalise."""
        from cd_ripper.core import accuraterip

        found = accuraterip.LookupFound(entries=(), url="http://ar/x.bin")
        p = self._patches(found, 6)
        with (
            p[0] as read_toc,
            p[1],
            p[2],
            p[3] as detect,
            p[4],
        ):
            run_read_offset_detection("E:", lambda _m: None)
        read_toc.assert_called_once()
        assert read_toc.call_args.args[0] == "E"
        detect.assert_called_once()
        assert detect.call_args.args[0] == "E"

    def test_lookup_failure_raises_and_persists_nothing(self) -> None:
        from cd_ripper.core import accuraterip

        p = self._patches(accuraterip.LookupNotFound(reason="no entry"), None)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            p[4] as set_off,
        ):
            with pytest.raises(ReadOffsetDetectionError):
                run_read_offset_detection("E", lambda _m: None)
        set_off.assert_not_called()

    def test_inconclusive_sweep_raises_and_persists_nothing(self) -> None:
        from cd_ripper.core import accuraterip

        found = accuraterip.LookupFound(entries=(), url="http://ar/x.bin")
        p = self._patches(found, None)
        with (
            p[0],
            p[1],
            p[2],
            p[3],
            p[4] as set_off,
        ):
            with pytest.raises(ReadOffsetDetectionError, match="unanimous"):
                run_read_offset_detection("E", lambda _m: None)
        set_off.assert_not_called()


# ===========================================================================
# O(1) v1 fast formula parity with the production checksum
# ===========================================================================


class TestV1FastParity:
    def _parity(self, track_number: int, track_count: int) -> None:
        rng = np.random.default_rng(20260924)
        raw = (
            rng.integers(0, 2**32, size=70_000 * 1, dtype=np.uint32)
            .astype("<u4")
            .tobytes()
        )
        s = 9414  # arbitrary non-zero base, mirrors the 16-sector lookback
        frames_total = 60_000
        window = raw[s * 4 : (s + frames_total) * 4]
        production = compute_track_checksums(window, track_number, track_count)

        pj, pw, _ = _prefix_arrays(raw)
        start_idx, end_idx = _window_bounds(frames_total, track_number, track_count)
        assert (start_idx, end_idx) == (
            FIRST_TRACK_SKIP_FRAMES if track_number == 1 else 0,
            frames_total - (EDGE_SKIP_FRAMES if track_number == track_count else 0),
        )
        fast = _v1_fast(pj, pw, s, start_idx, end_idx)
        assert fast == production.crc1

    def test_first_track_skip_window_matches_production(self) -> None:
        self._parity(track_number=1, track_count=2)

    def test_last_track_skip_window_matches_production(self) -> None:
        self._parity(track_number=2, track_count=2)

    def test_plain_track_window_matches_production(self) -> None:
        self._parity(track_number=1, track_count=3)


# ===========================================================================
# module plumbing
# ===========================================================================


def test_read_raw_range_is_exported_for_patching() -> None:
    # The detection tests patch this exact binding; keep it module-level.
    assert callable(_read_raw_range)
