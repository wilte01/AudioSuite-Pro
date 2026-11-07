"""Tests for the join engine.

The lengths are measured by decoding the written file, never read back from the
plan, and the crossfade is checked on the samples at the seam.

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from mutagen import File as MutagenFile
from pydub import AudioSegment

from audio_joiner.core.join import (
    REPORT_NAMES,
    join_files,
    preferred_order,
    resolve_order,
    split_order,
)
from audio_joiner.core.models import JoinSettings
from audio_suite_shared.exceptions import AudioConfigValueError

SAMPLE_RATE = 44_100


def _tone(
    duration_ms: int, frequency: int, *, rate: int = SAMPLE_RATE, amplitude: float = 0.3
) -> AudioSegment:
    times = np.arange(int(rate * duration_ms / 1000)) / rate
    samples = (amplitude * np.sin(2 * np.pi * frequency * times) * 32767).astype(
        np.int16
    )
    return AudioSegment(
        data=samples.tobytes(), sample_width=2, frame_rate=rate, channels=1
    )


def _write(segment: AudioSegment, path) -> None:
    segment.export(str(path), format="wav")


@pytest.fixture()
def pair(tmp_path):
    """Two 400 ms WAVs with identical stream parameters."""
    _write(_tone(400, 440), tmp_path / "a.wav")
    _write(_tone(400, 880), tmp_path / "b.wav")
    return tmp_path / "a.wav", tmp_path / "b.wav", tmp_path


@pytest.mark.integration
class TestLength:
    def test_a_gap_adds_exactly_its_length_per_boundary(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files(
            [first, second], folder / "joined.wav", JoinSettings(gap_ms=200)
        )

        assert outcome.planned_ms == 1000
        assert outcome.written is not None
        measured = len(AudioSegment.from_file(str(outcome.written)))
        assert measured == pytest.approx(1000, abs=3)

    def test_a_crossfade_removes_exactly_its_length_per_boundary(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files(
            [first, second], folder / "joined.wav", JoinSettings(crossfade_ms=100)
        )

        measured = len(AudioSegment.from_file(str(outcome.written)))
        assert outcome.planned_ms == 700
        assert measured == pytest.approx(700, abs=3)

    def test_a_hard_join_is_the_sum(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files([first, second], folder / "joined.wav", JoinSettings())

        measured = len(AudioSegment.from_file(str(outcome.written)))
        assert measured == pytest.approx(800, abs=3)


@pytest.mark.integration
class TestSeam:
    def test_a_crossfed_boundary_has_no_step(self, tmp_path) -> None:
        _write(_tone(500, 100), tmp_path / "low.wav")
        _write(_tone(500, 300), tmp_path / "high.wav")

        outcome = join_files(
            [tmp_path / "low.wav", tmp_path / "high.wav"],
            tmp_path / "joined.wav",
            JoinSettings(crossfade_ms=50),
        )

        samples = np.array(
            AudioSegment.from_file(str(outcome.written)).get_array_of_samples(),
            dtype=np.float64,
        )
        boundary = int(0.45 * SAMPLE_RATE)
        span = int(0.005 * SAMPLE_RATE)
        near = np.max(np.abs(np.diff(samples[boundary - span : boundary + span])))
        surrounding = np.concatenate(
            [
                np.abs(np.diff(samples[boundary - 10 * span : boundary - span])),
                np.abs(np.diff(samples[boundary + span : boundary + 10 * span])),
            ]
        )
        assert near <= max(float(surrounding.max()) * 2, 400.0)


@pytest.mark.integration
class TestCompatibility:
    def test_identical_streams_are_stream_copied(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files([first, second], folder / "joined.wav", JoinSettings())

        assert outcome.copy_used is True
        assert "stream copy" in " ".join(outcome.notes)

    def test_mixed_sample_rates_are_re_encoded_to_the_first_file(
        self, tmp_path
    ) -> None:
        _write(_tone(400, 440), tmp_path / "a.wav")
        _write(_tone(400, 440, rate=22_050), tmp_path / "b.wav")

        outcome = join_files(
            [tmp_path / "a.wav", tmp_path / "b.wav"],
            tmp_path / "joined.wav",
            JoinSettings(),
        )

        assert outcome.copy_used is False
        assert outcome.sample_rate == SAMPLE_RATE
        assert "re-encoded" in " ".join(outcome.notes)
        assert "b.wav" in " ".join(outcome.notes)
        measured = AudioSegment.from_file(str(outcome.written))
        assert measured.frame_rate == SAMPLE_RATE

    def test_a_different_output_container_forces_a_re_encode(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files([first, second], folder / "joined.flac", JoinSettings())

        assert outcome.copy_used is False
        assert (folder / "joined.flac").is_file()


@pytest.mark.integration
class TestTags:
    def test_the_first_segment_tags_reach_the_output(self, tmp_path) -> None:
        first = tmp_path / "a.mp3"
        second = tmp_path / "b.mp3"
        _tone(400, 440).export(str(first), format="mp3")
        _tone(400, 880).export(str(second), format="mp3")
        tagged = MutagenFile(str(first), easy=True)
        assert tagged is not None
        if tagged.tags is None:
            tagged.add_tags()
        tagged["title"] = "Opening"
        tagged["artist"] = "The Band"
        tagged.save()

        outcome = join_files([first, second], tmp_path / "joined.mp3", JoinSettings())

        assert outcome.tags_copied is True
        written = MutagenFile(str(outcome.written), easy=True)
        assert written is not None
        assert written["title"] == ["Opening"]
        assert written["artist"] == ["The Band"]

    def test_a_wav_output_reports_that_tags_were_not_written(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files([first, second], folder / "joined.wav", JoinSettings())

        assert outcome.tags_copied is False
        assert any("Tags: not written" in note for note in outcome.notes)


class TestRefusals:
    def test_one_segment_is_refused(self, tmp_path) -> None:
        first = tmp_path / "a.wav"
        _write(_tone(400, 440), first)

        with pytest.raises(AudioConfigValueError, match="at least two"):
            join_files([first], tmp_path / "joined.wav", JoinSettings())

    def test_an_output_that_is_a_segment_is_refused(self, pair) -> None:
        first, second, _folder = pair

        with pytest.raises(AudioConfigValueError, match="replace"):
            join_files([first, second], first, JoinSettings())

    def test_a_dry_run_writes_nothing(self, pair) -> None:
        first, second, folder = pair

        outcome = join_files(
            [first, second], folder / "joined.wav", JoinSettings(), dry_run=True
        )

        assert outcome.written is None
        assert not (folder / "joined.wav").exists()


def test_the_two_modes_write_different_reports() -> None:
    assert REPORT_NAMES[True] != REPORT_NAMES[False]


class TestAnOrderWithCommasInNames:
    """A comma is a legal file-name character, not only an order separator.

    Splitting the order on every comma cut ``1-03 Johnny, Don't Do It.mp3`` at
    the comma and refused the run with "names no file" for the fragment, which
    made a file the operating system accepts unusable in the joiner.
    """

    @pytest.fixture()
    def album(self, tmp_path: Path) -> tuple[Path, list[str]]:
        names = [
            "1-03 Johnny, Don't Do It.mp3",
            "1-04 Sand In My Face.mp3",
            "1-05 Speed Kills.mp3",
        ]
        for name in names:
            (tmp_path / name).write_bytes(b"")
        return tmp_path, names

    def test_a_name_with_a_comma_is_one_entry(self, album) -> None:
        folder, names = album

        resolved = resolve_order(folder, ",".join(names))

        assert [path.name for path in resolved] == names

    def test_the_spacing_after_a_comma_does_not_matter(self, album) -> None:
        folder, names = album

        resolved = resolve_order(folder, ", ".join(names))

        assert [path.name for path in resolved] == names

    def test_the_split_reports_the_name_whole(self, album) -> None:
        folder, names = album

        assert split_order(",".join(names), folder) == names

    def test_a_name_that_matches_nothing_is_still_reported(self, album) -> None:
        folder, names = album

        with pytest.raises(AudioConfigValueError, match="names no file"):
            resolve_order(folder, f"{names[0]},missing.mp3")

    def test_the_window_order_keeps_only_the_names_it_finds(self, album) -> None:
        folder, names = album

        preferred = preferred_order(folder, f"{names[2]},{names[1]},gone.mp3")

        assert [path.name for path in preferred] == [names[2], names[1]]
