"""Tests for the duplicate finder's data model.

The keeper rule and the settings validation are pure functions, and they decide
which file a live run leaves alone and which comparisons a run is allowed to
make, so they are pinned here rather than only through a scan.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import pytest

from duplicate_finder.core.models import (
    DEFAULT_DURATION_TOLERANCE_S,
    DEFAULT_MAX_SHIFT_WORDS,
    DEFAULT_MIN_OVERLAP_RATIO,
    DEFAULT_THRESHOLD,
    DuplicateGroup,
    DuplicateMember,
    FingerprintRecord,
    ScanOutcome,
    ScanSettings,
)


def record(
    path: str = "song.flac",
    *,
    duration: float = 210.0,
    lossless: bool = False,
    bitrate_kbps: float = 0.0,
    sample_rate: int = 44100,
    channels: int = 2,
    artist: str = "",
    title: str = "",
) -> FingerprintRecord:
    """Return a record with the suite's standard fixture values.

    Args:
        path: The record's path.
        duration: Decoded duration in seconds.
        lossless: Whether the container is lossless.
        bitrate_kbps: Audio bitrate.
        sample_rate: Sample rate in Hz.
        channels: Channel count.
        artist: Artist tag.
        title: Title tag.

    Returns:
        The record.
    """
    return FingerprintRecord(
        path=path,
        duration=duration,
        words=(1, 2, 3),
        size=4096,
        mtime=1700000000.0,
        sample_rate=sample_rate,
        channels=channels,
        bitrate_kbps=bitrate_kbps,
        lossless=lossless,
        artist=artist,
        title=title,
    )


class TestDefaults:
    """The shipped constants, and the measurement the threshold came from."""

    def test_the_threshold_sits_between_the_measured_bands(self) -> None:
        assert DEFAULT_THRESHOLD == 0.10
        assert DEFAULT_THRESHOLD > 0.0005  # inside one recording: 0.0000-0.0002
        assert DEFAULT_THRESHOLD < 0.1570  # nearest distinct pair: 0.1580

    def test_the_comparison_bounds_are_the_suite_defaults(self) -> None:
        settings = ScanSettings()

        assert settings.duration_tolerance_s == DEFAULT_DURATION_TOLERANCE_S == 2.0
        assert settings.min_overlap_ratio == DEFAULT_MIN_OVERLAP_RATIO == 0.6
        assert settings.max_shift_words == DEFAULT_MAX_SHIFT_WORDS == 32
        assert settings.quarantine_dir == ""


class TestScanSettingsValidation:
    """A setting the distance code cannot honour is refused at construction."""

    @pytest.mark.parametrize("threshold", [0.0, -0.1, 1.01, 5.0])
    def test_a_threshold_outside_the_unit_range_is_refused(
        self, threshold: float
    ) -> None:
        with pytest.raises(ValueError, match="threshold must be in"):
            ScanSettings(threshold=threshold)

    def test_a_full_threshold_is_allowed(self) -> None:
        assert ScanSettings(threshold=1.0).threshold == 1.0

    def test_a_negative_duration_tolerance_is_refused(self) -> None:
        with pytest.raises(ValueError, match="duration_tolerance_s"):
            ScanSettings(duration_tolerance_s=-1.0)

    def test_a_zero_overlap_ratio_is_refused(self) -> None:
        with pytest.raises(ValueError, match="min_overlap_ratio"):
            ScanSettings(min_overlap_ratio=0.0)

    def test_a_negative_shift_width_is_refused(self) -> None:
        with pytest.raises(ValueError, match="max_shift_words"):
            ScanSettings(max_shift_words=-1)

    def test_a_zero_shift_width_is_allowed(self) -> None:
        assert ScanSettings(max_shift_words=0).max_shift_words == 0


class TestQualityKey:
    """The ordering a keeper is chosen by, best last."""

    def test_lossless_outranks_a_higher_bitrate(self) -> None:
        lossless = record(lossless=True, bitrate_kbps=1411.0)
        lossy = record(path="b.mp3", bitrate_kbps=320.0)

        assert lossless.quality_key > lossy.quality_key

    def test_bitrate_then_sample_rate_then_duration_order_the_rest(self) -> None:
        low = record(bitrate_kbps=96.0, sample_rate=44100, duration=200.0)
        mid = record(
            path="b.mp3", bitrate_kbps=192.0, sample_rate=44100, duration=200.0
        )
        higher_rate = record(
            path="c.mp3", bitrate_kbps=192.0, sample_rate=48000, duration=200.0
        )
        longer = record(
            path="d.mp3", bitrate_kbps=192.0, sample_rate=48000, duration=230.0
        )

        assert low.quality_key < mid.quality_key < higher_rate.quality_key
        assert higher_rate.quality_key < longer.quality_key


class TestLabel:
    """The one line a report prints for a file."""

    def test_a_fully_tagged_lossless_file_names_its_properties(self) -> None:
        line = record(
            artist="Artist",
            title="Title",
            lossless=True,
            sample_rate=96000,
            channels=2,
        ).label

        assert line == "Artist - Title (lossless, 96000 Hz, 2 ch)"

    def test_a_lossy_file_states_its_bitrate(self) -> None:
        line = record(artist="A", title="T", bitrate_kbps=192.4).label

        assert line == "A - T (192 kbit/s, 44100 Hz, 2 ch)"

    def test_a_file_without_tags_still_reads_as_a_sentence(self) -> None:
        line = record(artist="  ", title="").label

        assert line.startswith("Unknown artist - Unknown title (")


class TestDuplicateGroup:
    """The grouped result's own helpers."""

    def test_files_lists_the_keeper_first(self) -> None:
        keeper = record("keeper.flac")
        other = record("other.mp3")
        group = DuplicateGroup(
            keeper=keeper, duplicates=(DuplicateMember(record=other, distance=0.1),)
        )

        assert group.files == (keeper, other)

    def test_worst_distance_is_the_largest_measured(self) -> None:
        group = DuplicateGroup(
            keeper=record(),
            duplicates=(
                DuplicateMember(record=record("a.mp3"), distance=0.01),
                DuplicateMember(record=record("b.mp3"), distance=0.09),
            ),
        )

        assert group.worst_distance == 0.09

    def test_a_singleton_group_reports_no_distance(self) -> None:
        assert DuplicateGroup(keeper=record(), duplicates=()).worst_distance == 0.0


class TestScanOutcome:
    """The counted result starts empty and counts what happens."""

    def test_a_fresh_outcome_counts_nothing(self) -> None:
        outcome = ScanOutcome()

        assert outcome.groups == []
        assert outcome.duplicates == 0
        assert outcome.quarantined == 0
        assert outcome.missing_fingerprint == 0
        assert outcome.log_entries == []

    def test_two_outcomes_do_not_share_their_lists(self) -> None:
        first, second = ScanOutcome(), ScanOutcome()
        first.log_entries.append("x")

        assert second.log_entries == []
