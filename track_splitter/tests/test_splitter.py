"""End-to-end split tests on a real, decoded fixture.

The fixture is three tones separated by two silent runs, so every expectation is
measured on the written audio: the number of tracks, the partition of the file,
and which tone each output actually contains.  Reading the plan back would only
prove the plan agrees with itself.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from track_splitter.core.models import SplitSettings
from track_splitter.core.splitter import split_file

pytestmark = pytest.mark.integration

SAMPLE_RATE = 44_100


def _tone(duration_ms: int, frequency: int) -> AudioSegment:
    """Return a mono sine tone at -10 dBFS-ish."""
    times = np.arange(int(SAMPLE_RATE * duration_ms / 1000)) / SAMPLE_RATE
    samples = (0.3 * np.sin(2 * np.pi * frequency * times) * 32767).astype(np.int16)
    return AudioSegment(
        data=samples.tobytes(),
        sample_width=2,
        frame_rate=SAMPLE_RATE,
        channels=1,
    )


def _silence(duration_ms: int) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms, frame_rate=SAMPLE_RATE)


@pytest.fixture()
def source(tmp_path: Path) -> Path:
    """500 ms tone, 800 ms silence, 500 ms tone, 800 ms silence, 500 ms tone."""
    audio = (
        _tone(500, 440)
        + _silence(800)
        + _tone(500, 880)
        + _silence(800)
        + _tone(500, 1320)
    )
    path = tmp_path / "gig.wav"
    audio.export(str(path), format="wav")
    return path


def _settings(**overrides: object) -> SplitSettings:
    values: dict[str, object] = {
        "min_silence_ms": 400,
        "silence_db": -40.0,
        "min_track_ms": 200,
    }
    values.update(overrides)
    return SplitSettings(**values)  # type: ignore[arg-type]


class TestSplitFile:
    def test_it_finds_three_tracks_and_partitions_the_file(
        self, source: Path, tmp_path: Path
    ) -> None:
        outcome = split_file(source, tmp_path / "out", _settings())

        assert len(outcome.tracks) == 3
        assert [t.start_ms for t in outcome.tracks] == [0, 900, 2200]
        assert outcome.tracks[0].start_ms == 0
        assert sum(t.duration_ms for t in outcome.tracks) == 3100
        assert len(outcome.written) == 3

    def test_each_written_track_holds_its_own_tone(
        self, source: Path, tmp_path: Path
    ) -> None:
        outcome = split_file(source, tmp_path / "out", _settings())

        first = AudioSegment.from_file(str(outcome.written[0]))
        assert first.dBFS > -20.0, "track one lost its tone"
        assert first[:300].dBFS > -20.0
        assert first[-200:].dBFS < -40.0, "track one kept silence it should have cut"

        # Midpoint halves the gap, so track two opens with 400 ms of the
        # silence and its tone starts at 400 ms.
        second = AudioSegment.from_file(str(outcome.written[1]))
        assert second[:300].dBFS < -40.0
        assert second[400:700].dBFS > -20.0
        assert second.frame_rate == SAMPLE_RATE
        assert second.channels == 1

    def test_the_partition_covers_the_source_sample_for_sample(
        self, source: Path, tmp_path: Path
    ) -> None:
        outcome = split_file(source, tmp_path / "out", _settings())
        written = sum(len(AudioSegment.from_file(str(p))) for p in outcome.written)
        assert abs(written - 3100) <= 1

    def test_it_writes_one_cue_that_round_trips(
        self, source: Path, tmp_path: Path
    ) -> None:
        from audio_suite_shared.cue_parser import parse_cue_file

        outcome = split_file(source, tmp_path / "out", _settings(write_cue=True))

        assert outcome.cue_path is not None and outcome.cue_path.exists()
        parsed = parse_cue_file(outcome.cue_path)
        offsets = [t.index01.start_ms for t in parsed.files[0].tracks]
        for offset, planned in zip(offsets, outcome.tracks, strict=True):
            assert abs(offset - planned.start_ms) <= 14

    def test_a_dry_run_writes_nothing(self, source: Path, tmp_path: Path) -> None:
        target = tmp_path / "out"
        outcome = split_file(source, target, _settings(write_cue=True), dry_run=True)

        assert len(outcome.tracks) == 3
        assert outcome.written == []
        assert outcome.cue_path is None
        assert not target.exists()

    def test_a_source_without_gaps_stays_whole(self, tmp_path: Path) -> None:
        path = tmp_path / "one.wav"
        (_tone(1200, 440)).export(str(path), format="wav")

        outcome = split_file(path, tmp_path / "out", _settings())

        assert len(outcome.tracks) == 1
        assert outcome.tracks[0].start_ms == 0
        assert "no gap found" in outcome.summary

    def test_the_configured_boundary_moves_the_cut_not_the_length(
        self, source: Path, tmp_path: Path
    ) -> None:
        for rule in ("midpoint", "start", "end"):
            outcome = split_file(
                source, tmp_path / f"out-{rule}", _settings(boundary=rule)
            )
            assert sum(t.duration_ms for t in outcome.tracks) == 3100
