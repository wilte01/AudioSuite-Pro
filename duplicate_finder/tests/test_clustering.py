"""Tests for duplicate clustering, including the measured fixture set.

The measurement half is the point of the item: ``DEFAULT_THRESHOLD`` is only a
justified default if the distances a real encode pair produces sit well below it
and the nearest pair that must *not* cluster sits well above.  Both are asserted
here against the declared fixture set in :mod:`duplicate_finder.tests.conftest`,
and the numbers are printed into the failure message so a future encoder change
shows what moved instead of only that something did.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from duplicate_finder.core.clustering import (
    _MAX_ANCHOR_FANOUT,
    _UnionFind,
    candidate_pairs,
    choose_keeper,
    cluster_records,
)
from duplicate_finder.core.fingerprint_distance import bit_error_rate
from duplicate_finder.core.models import (
    DEFAULT_THRESHOLD,
    DuplicateGroup,
    FingerprintRecord,
    ScanSettings,
)

#: The largest distance measured between two encodings of one recording
#: (FLAC against MP3 96 kbit/s: 0.000204; the lossless-versus-high-bitrate pairs
#: measure 0.0000).
MEASURED_SAME_RECORDING_MAX = 0.0005

#: The smallest distance measured between two *different* recordings (two
#: arrangements sharing a 10 s intro: 0.1580).
MEASURED_DISTINCT_RECORDING_MIN = 0.1570


def record(
    path: str,
    words: tuple[int, ...],
    *,
    duration: float = 20.0,
    size: int = 1000,
    mtime: float = 1.0,
    sample_rate: int = 44100,
    channels: int = 2,
    bitrate_kbps: float = 128.0,
    lossless: bool = False,
) -> FingerprintRecord:
    """Return a record with *words* and only the fields a test varies.

    Args:
        path: The record's path; also the keeper tie-break.
        words: The fingerprint words.
        duration: Decoded duration in seconds.
        size: File size, half of the cache's freshness stamp.
        mtime: Modification time, the stamp's other half.
        sample_rate: Sample rate in Hz.
        channels: Channel count.
        bitrate_kbps: Audio bitrate.
        lossless: Whether the container is lossless.

    Returns:
        The record.
    """
    return FingerprintRecord(
        path=path,
        words=words,
        duration=duration,
        size=size,
        mtime=mtime,
        sample_rate=sample_rate,
        channels=channels,
        bitrate_kbps=bitrate_kbps,
        lossless=lossless,
    )


class TestCandidatePairs:
    """Anchor search: the cheap first stage before any distance is measured."""

    def test_a_shared_word_makes_a_pair(self) -> None:
        # Only every fourth word is indexed, so the shared value sits at a
        # sampled position (index 4) rather than at index 3.
        left = record("a.flac", (1, 2, 3, 4, 5, 6, 7, 8))
        right = record("b.mp3", (9, 9, 9, 9, 5, 9, 9, 9))

        assert candidate_pairs([left, right]) == [(0, 1)]

    def test_an_unrelated_pair_is_not_a_candidate(self) -> None:
        left = record("a.flac", (1, 2, 3, 4))
        right = record("b.mp3", (5, 6, 7, 8))

        assert candidate_pairs([left, right]) == []

    def test_a_word_shared_by_too_many_files_is_not_an_anchor(self) -> None:
        # A common word in a big library would make the index quadratic on its
        # own, so a word past the fan-out cap is treated as noise.  Identical
        # fingerprints isolate the cap: without it, every pair would be found.
        crowded = [
            record(f"c{index}.mp3", (42, 42, 42, 42))
            for index in range(_MAX_ANCHOR_FANOUT + 1)
        ]
        small = [record(f"s{index}.mp3", (42, 42, 42, 42)) for index in range(3)]

        assert candidate_pairs(crowded) == []
        assert len(candidate_pairs(small)) == 3

    def test_pairs_are_unique_and_ordered(self) -> None:
        shared = (7, 7, 7, 7)
        records = [record(f"{index}.mp3", shared) for index in range(3)]

        pairs = candidate_pairs(records)

        assert pairs == [(0, 1), (0, 2), (1, 2)]


class TestUnionFind:
    """The grouping primitive; a bug here silently merges or splits groups."""

    def test_two_unions_of_three_elements_share_one_root(self) -> None:
        union = _UnionFind(3)
        union.union(0, 1)
        union.union(1, 2)

        assert union.find(0) == union.find(2)

    def test_disjoint_elements_keep_separate_roots(self) -> None:
        union = _UnionFind(3)
        union.union(0, 1)

        assert union.find(0) != union.find(2)


class TestClusterRecords:
    """Grouping: threshold, duration guard, keeper choice, stability."""

    def test_empty_and_single_input_give_no_groups(self) -> None:
        settings = ScanSettings()

        assert cluster_records([], settings) == []
        assert cluster_records([record("a.flac", (1, 2, 3, 4))], settings) == []

    def test_three_encodings_of_one_recording_are_one_group(self) -> None:
        words = (10, 20, 30, 40, 50, 60, 70, 80)
        records = [
            record("c.mp3", words, bitrate_kbps=320.0),
            record("a.flac", words, lossless=True),
            record("b.mp3", words, bitrate_kbps=96.0),
        ]

        groups = cluster_records(records, ScanSettings())

        assert len(groups) == 1
        assert groups[0].keeper.path == "a.flac"
        assert [member.record.path for member in groups[0].duplicates] == [
            "b.mp3",
            "c.mp3",
        ]

    def test_an_unrelated_recording_is_its_own_file(self) -> None:
        records = [
            record("a.flac", (10, 20, 30, 40)),
            record("b.flac", (10, 20, 30, 40)),
            record("c.mp3", (90, 91, 92, 93)),
        ]

        groups = cluster_records(records, ScanSettings())

        assert [group.keeper.path for group in groups] == ["a.flac"]
        assert [member.record.path for member in groups[0].duplicates] == ["b.flac"]

    def test_two_files_of_very_different_length_are_not_compared(self) -> None:
        words = (10, 20, 30, 40, 50, 60, 70, 80)
        records = [
            record("full.flac", words, duration=210.0),
            record("clip.mp3", words, duration=12.0),
        ]

        assert cluster_records(records, ScanSettings()) == []

    def test_the_threshold_is_the_only_thing_separating_them(self) -> None:
        """A pair just over one threshold and just under another."""
        left = tuple(0b1111 for _ in range(16))
        right = tuple(0b1111 if index % 8 else 0b1110 for index in range(16))
        records = [record("a.flac", left), record("b.mp3", right)]
        distance = bit_error_rate(left, right)

        assert 0.0 < distance < 1.0
        assert cluster_records(records, ScanSettings(threshold=distance)) != []
        assert cluster_records(records, ScanSettings(threshold=distance * 0.5)) == []

    def test_groups_are_ordered_largest_first_then_by_keeper(self) -> None:
        big = (1, 1, 1, 1)
        small = (9, 9, 9, 9)
        records = [
            record("z.flac", small),
            record("y.mp3", small),
            record("m.flac", big),
            record("n.mp3", big),
            record("o.mp3", big),
        ]

        groups = cluster_records(records, ScanSettings())

        assert [len(group.duplicates) for group in groups] == [2, 1]
        assert [group.keeper.path for group in groups] == ["m.flac", "y.mp3"]

    def test_every_duplicate_carries_its_distance_to_the_keeper(self) -> None:
        words = (5, 5, 5, 5)
        records = [record("a.flac", words), record("b.mp3", words)]

        (group,) = cluster_records(records, ScanSettings())

        assert group.worst_distance == 0.0
        assert group.files[0] is group.keeper

    def test_a_group_survives_a_later_skip_than_the_duration_guard(self) -> None:
        """A chained relation still ends in one group, not two."""
        words = (3, 3, 3, 3)
        records = [
            record("a.flac", words, duration=20.0),
            record("b.mp3", words, duration=21.0),
            record("c.mp3", words, duration=22.0),
        ]

        groups = cluster_records(records, ScanSettings(duration_tolerance_s=1.5))

        # a-b and b-c are comparable; a-c is not, and union-find still joins all
        # three through b, which is the behaviour a best-match rule would miss.
        assert len(groups) == 1
        assert len(groups[0].duplicates) == 2


class TestChooseKeeper:
    """The keeper rule, which decides which file a live run leaves alone."""

    def test_lossless_beats_a_higher_bitrate(self) -> None:
        records = [
            record("a.mp3", (1,), bitrate_kbps=320.0),
            record("b.flac", (1,), lossless=True),
        ]

        assert choose_keeper(records).path == "b.flac"

    def test_higher_bitrate_beats_a_lower_one(self) -> None:
        records = [
            record("a.mp3", (1,), bitrate_kbps=96.0),
            record("b.mp3", (1,), bitrate_kbps=320.0),
        ]

        assert choose_keeper(records).path == "b.mp3"

    def test_sample_rate_breaks_a_bitrate_tie(self) -> None:
        records = [
            record("a.mp3", (1,), sample_rate=44100),
            record("b.mp3", (1,), sample_rate=48000),
        ]

        assert choose_keeper(records).path == "b.mp3"

    def test_the_longer_copy_wins_a_full_tie(self) -> None:
        records = [
            record("a.flac", (1,), duration=180.0),
            record("b.flac", (1,), duration=201.0),
        ]

        assert choose_keeper(records).path == "b.flac"

    def test_a_full_tie_goes_to_the_first_path(self) -> None:
        records = [record("b.flac", (1,)), record("a.flac", (1,))]

        assert choose_keeper(records).path == "a.flac"
        assert choose_keeper(list(reversed(records))).path == "a.flac"

    def test_no_records_is_an_error_not_an_empty_answer(self) -> None:
        with pytest.raises(ValueError, match="at least one record"):
            choose_keeper([])


@pytest.mark.integration
class TestTheMeasuredFixtureSet:
    """The declared distances, measured through the real fingerprint path."""

    @staticmethod
    def _records(library: Path) -> dict[str, FingerprintRecord]:
        """Fingerprint every fixture file through ``build_record``.

        Args:
            library: Directory holding the declared fixture set.

        Returns:
            ``{filename: record}``.
        """
        from duplicate_finder.core.fingerprinting import build_record

        return {
            path.name: build_record(
                str(path), path.stat().st_mtime, path.stat().st_size
            )
            for path in sorted(library.iterdir())
            if path.is_file()
        }

    def test_take2_has_the_same_length_as_the_recording_it_is_not(
        self, library: Path
    ) -> None:
        """The duration guard cannot separate them: only the fingerprint can."""
        records = self._records(library)
        song = records["song.flac"].duration

        assert records["take2.mp3"].duration == pytest.approx(song, abs=0.1)
        for name in ("song_96.mp3", "song_128.mp3", "song_320.mp3"):
            assert records[name].duration == pytest.approx(song, abs=0.1)

    def test_every_encoding_of_the_recording_is_within_the_measured_band(
        self, library: Path
    ) -> None:
        records = self._records(library)
        names = ["song.flac", "song_96.mp3", "song_128.mp3", "song_320.mp3"]

        distances = {
            (left, right): bit_error_rate(records[left].words, records[right].words)
            for index, left in enumerate(names)
            for right in names[index + 1 :]
        }

        assert distances, "no pair measured; the fixture set is not what it declares"
        worst = max(distances.values())
        assert worst <= MEASURED_SAME_RECORDING_MAX, distances
        assert worst < DEFAULT_THRESHOLD / 100, distances

    def test_the_nearest_different_recording_is_well_above_the_threshold(
        self, library: Path
    ) -> None:
        records = self._records(library)
        song = records["song.flac"].words

        distances = {
            name: bit_error_rate(song, records[name].words)
            for name in records
            if name not in {"song.flac", "song_96.mp3", "song_128.mp3", "song_320.mp3"}
        }

        nearest = min(distances.values())
        assert nearest >= MEASURED_DISTINCT_RECORDING_MIN, distances
        assert nearest > DEFAULT_THRESHOLD * 1.5, distances

    def test_the_declared_set_clusters_exactly_as_declared(self, library: Path) -> None:
        records = self._records(library)

        groups = cluster_records(list(records.values()), ScanSettings())

        assert len(groups) == 1, [group.keeper.path for group in groups]
        (group,) = groups
        assert Path(group.keeper.path).name == "song.flac"
        # Duplicates are listed by path, so the bitrate order is not the order
        # the report prints: "song_128" < "song_320" < "song_96".
        assert sorted(Path(member.record.path).name for member in group.duplicates) == [
            "song_128.mp3",
            "song_320.mp3",
            "song_96.mp3",
        ]
        assert isinstance(group, DuplicateGroup)

    def test_the_two_recordings_sharing_an_intro_stay_apart(
        self, library: Path
    ) -> None:
        records = self._records(library)

        distance = bit_error_rate(
            records["shared_a.mp3"].words, records["shared_b.mp3"].words
        )

        assert distance > DEFAULT_THRESHOLD * 2, distance
        assert candidate_pairs(list(records.values()))
