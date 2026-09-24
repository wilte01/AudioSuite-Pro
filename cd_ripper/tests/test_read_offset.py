"""
Tests for cd_ripper.core.read_offset

Coverage strategy
-----------------
- Config round-trip: per-drive set/get through the shared suite config with
  drive-specifier normalisation, multi-drive preservation, and 0 deleting
  the entry (real suite_config, CONFIG_PATH redirected to tmp_path).
- Validation: set/get reject out-of-range and corrupted stored values.
- Geometry: the layout matrix for every (offset, is_last) combination,
  including the empirically derived skip for the final track.
- Outcome correctness: a synthetic mis-aligned drive read pushed through
  ``compute_track_read_layout`` + ``aligned_track_pcm`` must reproduce the
  exact nominal physical window (or the documented short tail for the
  final track) — the real alignment outcome, not internal state.
"""

from __future__ import annotations

import pytest

import audio_suite_shared.suite_config as sc
from audio_suite_shared.exceptions import AudioConfigurationError
from cd_ripper.core.accuraterip import FRAMES_PER_SECTOR
from cd_ripper.core.drive_handler import SECTOR_SIZE
from cd_ripper.core.read_offset import (
    READ_OFFSET_CONFIG_KEY,
    aligned_track_pcm,
    compute_track_read_layout,
    get_read_offset_frames,
    set_read_offset_frames,
)

FRAMES = FRAMES_PER_SECTOR
BYTES_PER_FRAME = 4


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Redirect suite_config.CONFIG_PATH to a temp file for every test."""
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(sc, "CONFIG_PATH", config_file)
    sc._invalidate_cache()
    yield config_file


# ===========================================================================
# config round-trip
# ===========================================================================


class TestConfigRoundTrip:
    def test_unset_drive_returns_zero(self) -> None:
        assert get_read_offset_frames("E") == 0

    @pytest.mark.parametrize("spec", ["E", "e", "E:", "e:", "E:\\", "e/"])
    def test_drive_specifier_normalised(self, spec: str) -> None:
        set_read_offset_frames("E", 6)
        assert get_read_offset_frames(spec) == 6

    def test_other_drives_preserved(self) -> None:
        set_read_offset_frames("D", 12)
        set_read_offset_frames("E", 6)
        assert get_read_offset_frames("D") == 12
        assert get_read_offset_frames("E") == 6

    def test_zero_offset_deletes_entry(self) -> None:
        set_read_offset_frames("E", 6)
        set_read_offset_frames("E", 0)
        assert get_read_offset_frames("E") == 0
        stored = sc.load_value(READ_OFFSET_CONFIG_KEY, {})
        assert isinstance(stored, dict)
        assert "E" not in stored

    def test_round_trip_full_sector_offset(self) -> None:
        set_read_offset_frames("F", FRAMES)
        assert get_read_offset_frames("f:") == FRAMES


class TestConfigValidation:
    @pytest.mark.parametrize("bad", [-1, FRAMES + 1, 10_000])
    def test_set_out_of_range_raises(self, bad: int) -> None:
        with pytest.raises(AudioConfigurationError):
            set_read_offset_frames("E", bad)

    def test_set_bounds_are_inclusive(self) -> None:
        set_read_offset_frames("E", 0)
        set_read_offset_frames("E", FRAMES)

    @pytest.mark.parametrize(
        "stored",
        [
            6,  # plain int is fine — sanity that the good path works
            -3,  # negative stored value treated as unset
            FRAMES + 1,  # out-of-range stored value treated as unset
            True,  # bool is not an int offset
            "6",  # string value
            6.0,  # float value
        ],
    )
    def test_corrupted_stored_values(self, stored: object) -> None:
        if stored == 6:
            sc.save_value(READ_OFFSET_CONFIG_KEY, {"E": 6})
            assert get_read_offset_frames("E") == 6
            return
        sc.save_value(READ_OFFSET_CONFIG_KEY, {"E": stored})
        assert get_read_offset_frames("E") == 0

    def test_non_dict_stored_value(self) -> None:
        sc.save_value(READ_OFFSET_CONFIG_KEY, [1, 2, 3])
        assert get_read_offset_frames("E") == 0


# ===========================================================================
# geometry matrix
# ===========================================================================


class TestComputeTrackReadLayout:
    def test_zero_offset_is_nominal_for_any_track(self) -> None:
        for is_last in (False, True):
            layout = compute_track_read_layout(100, 50, 0, is_last)
            assert layout.read_start_lba == 100
            assert layout.read_sectors == 50
            assert layout.skip_bytes == 0
            assert layout.tail_shortfall_bytes == 0

    def test_non_last_track_reads_one_extra_sector(self) -> None:
        layout = compute_track_read_layout(100, 50, 6, False)
        assert layout.read_start_lba == 100
        assert layout.read_sectors == 51
        assert layout.skip_bytes == 6 * BYTES_PER_FRAME
        assert layout.tail_shortfall_bytes == 0

    def test_last_track_never_reads_past_leadout(self) -> None:
        layout = compute_track_read_layout(200, 60, 6, True)
        assert layout.read_start_lba == 200
        assert layout.read_sectors == 60
        assert layout.skip_bytes == 6 * BYTES_PER_FRAME
        assert layout.tail_shortfall_bytes == 6 * BYTES_PER_FRAME

    def test_last_track_at_lba_zero_same_geometry(self) -> None:
        layout = compute_track_read_layout(0, 40, 6, True)
        assert layout.read_sectors == 40
        assert layout.skip_bytes == 24
        assert layout.tail_shortfall_bytes == 24

    def test_full_sector_offset_bounds(self) -> None:
        layout = compute_track_read_layout(10, 30, FRAMES, False)
        assert layout.read_sectors == 31
        assert layout.skip_bytes == FRAMES * BYTES_PER_FRAME
        last = compute_track_read_layout(10, 30, FRAMES, True)
        assert last.read_sectors == 30
        assert last.skip_bytes == FRAMES * BYTES_PER_FRAME
        assert last.tail_shortfall_bytes == FRAMES * BYTES_PER_FRAME

    def test_negative_offset_treated_as_no_correction(self) -> None:
        layout = compute_track_read_layout(10, 30, -6, False)
        assert layout.read_start_lba == 10
        assert layout.read_sectors == 30
        assert layout.skip_bytes == 0
        assert layout.tail_shortfall_bytes == 0


# ===========================================================================
# outcome correctness — synthetic mis-aligned drive
# ===========================================================================


def _synthetic_disc_frames(leadin_sectors: int, total_sectors: int) -> bytes:
    """Deterministic pseudo-random PCM for a whole disc plus a lead-in prefix.

    Physical frame ``f`` of LBA ``l`` lives at byte offset
    ``((leadin_sectors + l) * FRAMES + f) * 4`` of the returned bytes; the
    lead-in prefix models a drive that can deliver content before LBA 0.
    """
    import numpy as np

    frames: int = (leadin_sectors + total_sectors) * FRAMES
    values = np.arange(frames, dtype=np.uint64)
    # Non-trivial, byte-distinguishable values: mix bits so each frame is
    # unique but stays inside uint32 when packed.
    mixed = (values * 2_654_435_761 + 1_234_567_890) & 0xFFFFFFFF
    return mixed.astype("<u4").tobytes()


def _drive_read(
    phys: bytes, leadin_sectors: int, lba: int, sectors: int, offset_frames: int
) -> bytes:
    """What an offset drive delivers for ``read(lba, sectors)``.

    Model (empirically verified on real hardware): raw frame ``k`` holds
    physical frame ``lba * FRAMES + k - offset_frames``.
    """
    start_frame = (leadin_sectors + lba) * FRAMES - offset_frames
    end_frame = start_frame + sectors * FRAMES
    assert start_frame >= 0
    return phys[start_frame * 4 : end_frame * 4]


LEADIN = 16  # sectors of readable pre-LBA-0 content the drive can deliver


class TestAlignedOutcome:
    """The aligned window must equal the true physical track window."""

    TOTAL_SECTORS = 300
    OFFSET = 6

    def _phys(self) -> bytes:
        return _synthetic_disc_frames(LEADIN, self.TOTAL_SECTORS)

    def test_non_last_track_aligns_exactly(self) -> None:
        phys = self._phys()
        start_lba, sectors = 100, 50
        layout = compute_track_read_layout(start_lba, sectors, self.OFFSET, False)
        raw = _drive_read(
            phys, LEADIN, layout.read_start_lba, layout.read_sectors, self.OFFSET
        )
        aligned = aligned_track_pcm(raw, layout, sectors)

        lo = ((LEADIN + start_lba) * FRAMES) * 4
        hi = ((LEADIN + start_lba + sectors) * FRAMES) * 4
        assert aligned == phys[lo:hi]
        assert len(aligned) == sectors * SECTOR_SIZE

    def test_track1_at_lba0_aligns_exactly(self) -> None:
        phys = self._phys()
        sectors = 40
        layout = compute_track_read_layout(0, sectors, self.OFFSET, False)
        raw = _drive_read(phys, LEADIN, 0, layout.read_sectors, self.OFFSET)
        aligned = aligned_track_pcm(raw, layout, sectors)

        lo = (LEADIN * FRAMES) * 4
        hi = ((LEADIN + sectors) * FRAMES) * 4
        assert aligned == phys[lo:hi]

    def test_last_track_aligns_with_documented_short_tail(self) -> None:
        phys = self._phys()
        start_lba, sectors = 240, 60
        layout = compute_track_read_layout(start_lba, sectors, self.OFFSET, True)
        raw = _drive_read(
            phys, LEADIN, layout.read_start_lba, layout.read_sectors, self.OFFSET
        )
        aligned = aligned_track_pcm(raw, layout, sectors)

        lo = ((LEADIN + start_lba) * FRAMES) * 4
        nominal_hi = ((LEADIN + start_lba + sectors) * FRAMES) * 4
        expected_hi = nominal_hi - layout.tail_shortfall_bytes
        assert aligned == phys[lo:expected_hi]
        assert len(aligned) == sectors * SECTOR_SIZE - layout.tail_shortfall_bytes

    def test_shortfall_lies_inside_ar_last_track_skip(self) -> None:
        """The missing tail must fit inside the 2940-frame skip window."""
        from cd_ripper.core.accuraterip import EDGE_SKIP_FRAMES

        layout = compute_track_read_layout(240, 60, FRAMES, True)
        assert layout.tail_shortfall_bytes <= EDGE_SKIP_FRAMES * BYTES_PER_FRAME

    def test_zero_offset_layout_is_passthrough(self) -> None:
        phys = self._phys()
        start_lba, sectors = 100, 50
        layout = compute_track_read_layout(start_lba, sectors, 0, False)
        raw = _drive_read(phys, LEADIN, start_lba, sectors, 0)
        assert aligned_track_pcm(raw, layout, sectors) == raw
