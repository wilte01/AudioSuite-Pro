"""Album-mode loudness: one gain for the whole folder, applied per track.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E1).

Every assertion decodes the file the tool wrote with FFmpeg and measures it.
Reading back the gain the plan holds would prove only that the plan can repeat
itself; the promises here are that each track moved by the album's gain (within
0.1 dB), that the album lands on its target (within 0.5 LU), and that the
true-peak ceiling holds on every track.

The fixtures are FLAC because album mode writes through the same encoder map as
the per-file normalise stage, which covers MP3, FLAC, OGG, M4A, Opus, WavPack
and Speex; a WAV album is refused with that stage's own message and is recorded
as follow-on work in the governing plan rather than silently re-encoded here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from audio_normalizer.core.album import (
    AlbumPlan,
    apply_album_gain,
    build_album_plan,
    plan_key,
)
from audio_suite_shared import audio_probe
from audio_suite_shared.exceptions import AudioFormatError

FS = 44100
TARGET = -16.0
CEILING = -1.0


# ── Fixture builders ─────────────────────────────────────────────────────────


def _write(path: Path, pcm: np.ndarray, *, fmt: str = "flac") -> Path:
    """Write one mono segment as *fmt*, without altering the sample values."""
    raw = pcm.astype(np.int16).tobytes()
    AudioSegment(raw, frame_rate=FS, sample_width=2, channels=1).export(
        str(path), format=fmt
    )
    return path


def _tone(
    path: Path, amplitude: float, *, freq: float = 440.0, duration_ms: int = 1200
) -> Path:
    """A steady tone: loudness tracks its amplitude, so it never hits a ceiling."""
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    return _write(path, amplitude * np.sin(2 * np.pi * freq * t) * 32767)


def _peaky(path: Path, *, duration_ms: int = 1200, spike: float = 0.9) -> Path:
    """Mostly silent with full-scale spikes: low loudness, high true peak."""
    n = int(FS * duration_ms / 1000)
    pcm = np.zeros(n)
    pcm[:: FS // 8] = spike
    return _write(path, pcm * 32767)


def _lufs(path: Path) -> float:
    """Decoded integrated loudness of one file."""
    return audio_probe.measure_loudness(str(path)).integrated_lufs


def _true_peak(path: Path) -> float:
    """Decoded true peak of one file, in dBTP."""
    peak = audio_probe.measure_loudness(str(path)).true_peak_dbtp
    assert peak is not None, f"{path.name} reported no true peak"
    return peak


def _fingerprint(path: Path) -> tuple[str, int, int]:
    """SHA-256, mtime_ns and size — what an untouched file must keep."""
    stat = path.stat()
    return (
        hashlib.sha256(path.read_bytes()).hexdigest(),
        stat.st_mtime_ns,
        stat.st_size,
    )


@pytest.fixture
def uneven_album(tmp_path: Path) -> list[Path]:
    """Three tones at deliberately uneven levels, in album order."""
    return [
        _tone(tmp_path / "01 quiet.flac", 0.02),
        _tone(tmp_path / "02 medium.flac", 0.08),
        _tone(tmp_path / "03 loud.flac", 0.30),
    ]


def _plan(paths: list[Path], **overrides: float) -> AlbumPlan:
    options: dict[str, float] = {
        "target_lufs": TARGET,
        "true_peak_ceiling": CEILING,
        "tolerance": 0.5,
    }
    options.update(overrides)
    return build_album_plan([str(path) for path in paths], **options)


# ── The plan ─────────────────────────────────────────────────────────────────


class TestBuildAlbumPlan:
    """The plan's figures, checked against an independently measured reference."""

    def test_one_gain_for_the_whole_album(self, uneven_album: list[Path]) -> None:
        plan = _plan(uneven_album)

        assert set(plan.gains) == {plan_key(path) for path in uneven_album}
        assert len(set(plan.gains.values())) == 1
        assert not any(plan.limited.values())
        assert plan.gains[plan_key(uneven_album[0])] == pytest.approx(
            TARGET - plan.album_lufs, abs=1e-6
        )
        assert plan.album_true_peak is not None

    def test_the_plan_agrees_with_an_independent_single_file_reference(
        self, uneven_album: list[Path], tmp_path: Path
    ) -> None:
        """The album figure must match a concatenated reference measured as one file.

        ``measure_album_loudness`` is a concat-demuxer pass; folding the same
        tracks into one file and measuring *that* is a different decode, so the
        comparison can actually fail.
        """
        combined = AudioSegment.empty()
        for path in uneven_album:
            combined += AudioSegment.from_file(str(path))
        reference = tmp_path / "reference.flac"
        combined.export(str(reference), format="flac")

        plan = _plan(uneven_album)

        assert plan.album_lufs == pytest.approx(_lufs(reference), abs=0.1)

    def test_a_peaky_quiet_track_is_limited_and_the_rest_keep_the_album_gain(
        self, tmp_path: Path
    ) -> None:
        peaky = _peaky(tmp_path / "01 peaky.flac")
        tone = _tone(tmp_path / "02 tone.flac", 0.02)

        plan = _plan([peaky, tone])

        album_gain = TARGET - plan.album_lufs
        assert plan.limited[plan_key(peaky)] is True
        assert plan.limited[plan_key(tone)] is False
        assert plan.gains[plan_key(peaky)] == pytest.approx(
            CEILING - _true_peak(peaky), abs=0.1
        )
        assert plan.gains[plan_key(tone)] == pytest.approx(album_gain, abs=1e-6)
        assert plan.gains[plan_key(peaky)] < album_gain
        assert any("limited" in note for note in plan.notes)

    def test_an_album_already_at_target_plans_zero_gains_and_says_so(
        self, tmp_path: Path
    ) -> None:
        track = _tone(tmp_path / "track.flac", 0.1)

        plan = _plan([track], target_lufs=_lufs(track))

        assert plan.gains[plan_key(track)] == 0.0
        assert plan.limited[plan_key(track)] is False
        assert any("within" in note for note in plan.notes)

    def test_an_empty_folder_is_refused(self) -> None:
        with pytest.raises(AudioFormatError):
            build_album_plan([], target_lufs=TARGET)


# ── Applying the plan ────────────────────────────────────────────────────────


class TestApplyAlbumGain:
    """The written files, decoded and measured — never the requested gain."""

    def test_each_track_moves_by_the_album_gain(self, uneven_album: list[Path]) -> None:
        plan = _plan(uneven_album)
        before = {path: _lufs(path) for path in uneven_album}

        applied = [
            apply_album_gain(str(path), plan.gains[plan_key(path)])
            for path in uneven_album
        ]

        assert applied == [True, True, True]
        for path in uneven_album:
            assert _lufs(path) - before[path] == pytest.approx(
                plan.gains[plan_key(path)], abs=0.1
            )

    def test_the_album_lands_on_its_target(self, uneven_album: list[Path]) -> None:
        plan = _plan(uneven_album)
        for path in uneven_album:
            apply_album_gain(str(path), plan.gains[plan_key(path)])

        measured = audio_probe.measure_album_loudness(
            [str(path) for path in uneven_album]
        ).integrated_lufs

        assert measured == pytest.approx(TARGET, abs=0.5)

    def test_the_true_peak_ceiling_holds_on_every_track(
        self, uneven_album: list[Path]
    ) -> None:
        plan = _plan(uneven_album)
        for path in uneven_album:
            key = plan_key(path)
            apply_album_gain(
                str(path),
                plan.gains[key],
                limit=plan.limited[key],
                true_peak_ceiling=CEILING,
            )

        for path in uneven_album:
            assert _true_peak(path) <= CEILING + 0.2

    def test_a_limited_track_is_held_by_the_limiter(self, tmp_path: Path) -> None:
        peaky = _peaky(tmp_path / "peaky.flac")
        tone = _tone(tmp_path / "tone.flac", 0.02)
        plan = _plan([peaky, tone])

        assert (
            apply_album_gain(
                str(peaky),
                plan.gains[plan_key(peaky)],
                limit=True,
                true_peak_ceiling=CEILING,
            )
            is True
        )

        assert _true_peak(peaky) <= CEILING + 0.2

    def test_zero_gain_writes_nothing(self, uneven_album: list[Path]) -> None:
        track = uneven_album[0]
        before = _fingerprint(track)

        assert apply_album_gain(str(track), 0.0) is False

        assert _fingerprint(track) == before

    def test_a_dry_run_writes_nothing(self, uneven_album: list[Path]) -> None:
        track = uneven_album[0]
        before = _fingerprint(track)

        assert apply_album_gain(str(track), 3.0, dry_run=True) is False

        assert _fingerprint(track) == before

    def test_tags_survive_the_gain(self, tmp_path: Path) -> None:
        from audio_suite_shared.tag_helper import read_tags_raw, write_tags_raw

        track = _tone(tmp_path / "tagged.flac", 0.05, duration_ms=600)
        write_tags_raw(str(track), {"TIT2": "Album Track"}, record_snapshot=False)

        assert apply_album_gain(str(track), -2.0) is True

        tags = read_tags_raw(str(track))
        assert any("Album Track" in str(value) for value in tags.values())

    def test_a_copy_out_gain_leaves_the_source_alone(self, tmp_path: Path) -> None:
        source = _tone(tmp_path / "source.flac", 0.05)
        destination = tmp_path / "out" / "source.flac"
        destination.parent.mkdir()
        before = _fingerprint(source)
        source_lufs = _lufs(source)

        assert apply_album_gain(str(source), -6.0, output=str(destination)) is True

        assert _fingerprint(source) == before
        assert _lufs(destination) == pytest.approx(source_lufs - 6.0, abs=0.2)
