"""
tests/test_peak_normalise.py

F-E2 of ``PLAN_2026-11-03_2.6.0_feature_wave_2.md``: a peak/true-peak target
mode beside the LUFS target.

Every level assertion here is measured by decoding the file that was written —
``audio_suite_shared.audio_probe.measure_levels`` (ffmpeg's ``astats`` sample
peak and ``ebur128`` true peak) and, for the full-scale check, a pydub decode
of the samples themselves.  Reading back the plan the code just computed would
prove nothing about the audio.

The files are real: a synthetic 440 Hz tone written to WAV/MP3/FLAC/M4A, so the
stage runs its real FFmpeg encode, its real tag rewrite and its real depth
preservation.

Changed in 2.6.0: new file (F-E2 of the 2.6.0 feature wave).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from audio_refinery.core.models import FileStatus, NormaliseParams, StageConfig
from audio_suite_shared.audio_probe import (
    LevelMetrics,
    measure_levels,
    probe_stream,
)
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.tag_helper import read_tags_raw

FS = 44100
#: The target the plan fixes as the mode's default.
TARGET_DBTP = -1.0
#: The plan's acceptance window: the delivered peak must land this close.
TOLERANCE_DB = 0.2


def _tone(*, peak_dbfs: float = -12.0, duration_ms: int = 400) -> AudioSegment:
    """Return a mono 440 Hz tone whose sample peak is *peak_dbfs*."""
    frames = int(FS * duration_ms / 1000)
    times = np.linspace(0, duration_ms / 1000, frames, endpoint=False)
    amplitude = 10 ** (peak_dbfs / 20.0)
    samples = (amplitude * np.sin(2 * np.pi * 440 * times) * 32767).astype(np.int16)
    return AudioSegment(samples.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _write(
    path: Path, *, peak_dbfs: float = -12.0, fmt: str | None = None, **kwargs: object
) -> Path:
    """Write a tone to *path* and return it."""
    _tone(peak_dbfs=peak_dbfs).export(
        str(path), format=fmt or path.suffix.lstrip("."), **kwargs
    )
    return path


def _config(**overrides: object) -> StageConfig:
    """A normalise-only config targeting :data:`TARGET_DBTP`."""
    config = StageConfig(declick=False, trim=False, enhance=False, normalise=True)
    config.normalise_params = NormaliseParams(
        target_mode="peak",
        target_peak_dbtp=TARGET_DBTP,
        tolerance=TOLERANCE_DB,
        **overrides,
    )
    return config


def _levels(path: Path) -> LevelMetrics:
    """Measure *path* through the suite's one measurement path."""
    return measure_levels(str(path), ffmpeg=FFMPEG_PATH)


def _digest(path: Path) -> str:
    """Return *path*'s SHA-256, so a rewrite cannot pass as a no-op."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _noop_emit(_stage: str, _message: str) -> None:
    """Discard progress messages."""


def _tag_pairs(path: Path) -> list[tuple[str, str]]:
    """Return a file's raw tags as sorted (key, value) text pairs.

    FLAC's Vorbis comment keeps no meaningful field order and mutagen cannot
    ``repr`` a comment dict holding a non-string value, so the comparison here
    is order-insensitive and text-normalised - and still exact per field, so a
    dropped or rewritten tag fails it.
    """

    raw = read_tags_raw(str(path))
    if raw is None:
        return []
    # The containers disagree on shape: ID3/MP4 hand back a mapping of frame
    # objects, the Vorbis handler a list of (field, value) pairs.
    items = raw.items() if hasattr(raw, "items") else raw
    return sorted((str(key), str(value)) for key, value in items)


def _tag(path: Path, title: str) -> None:
    """Write a title and artist through mutagen's easy interface.

    Container-agnostic on purpose: the assertion is that the stage preserves
    whatever the file carries, not that one format's frame ids round-trip.
    """
    from mutagen import File as MutagenFile

    tagged = MutagenFile(str(path), easy=True)
    tagged["title"] = [title]
    tagged["artist"] = ["Peak Artist"]
    tagged.save()


class TestPeakTarget:
    """The stage delivers the true-peak target it was asked for."""

    def test_a_quiet_file_is_raised_to_the_true_peak_target(
        self, tmp_path: Path
    ) -> None:
        """Measure the written file: both peaks at or below the target."""
        from audio_refinery.core.pipeline import process_file

        source = _write(tmp_path / "quiet.wav", peak_dbfs=-12.0)
        before = _levels(source)
        assert before.true_peak_dbtp < -9.0

        result = process_file(source, source, _config())

        assert result.status is FileStatus.DONE
        after = _levels(source)
        assert abs(after.true_peak_dbtp - TARGET_DBTP) <= TOLERANCE_DB, (
            f"true peak {after.true_peak_dbtp:.2f} dBTP is not the "
            f"{TARGET_DBTP} dBTP target"
        )
        assert after.sample_peak_dbfs < 0.0
        message = " ".join(stage.message for stage in result.stages)
        assert f"{TARGET_DBTP} dBTP" in message
        assert "limited" not in message

    def test_no_written_sample_sits_at_full_scale(self, tmp_path: Path) -> None:
        """The ceiling is held in the samples, not merely in ffmpeg's summary."""
        from audio_refinery.core.pipeline import process_file

        source = _write(tmp_path / "ceiling.wav", peak_dbfs=-12.0)
        process_file(source, source, _config())

        decoded = AudioSegment.from_file(str(source))
        samples = np.array(decoded.get_array_of_samples())
        assert int(np.max(np.abs(samples))) < 32767, "a sample reached full scale"
        assert decoded.max_dBFS < 0.0

    def test_a_static_gain_does_not_engage_the_limiter(self, tmp_path: Path) -> None:
        """A file that needs only a gain moves by that gain, flat."""
        from audio_refinery.core.pipeline import process_file

        source = _write(tmp_path / "static.wav", peak_dbfs=-12.0)
        before_rms = AudioSegment.from_file(str(source)).dBFS
        before_peak = _levels(source).true_peak_dbtp

        result = process_file(source, source, _config())

        after_rms = AudioSegment.from_file(str(source)).dBFS
        measured_gain = after_rms - before_rms
        planned_gain = TARGET_DBTP - before_peak
        assert measured_gain == pytest.approx(planned_gain, abs=TOLERANCE_DB)
        message = " ".join(stage.message for stage in result.stages)
        assert "limited" not in message

    def test_a_second_run_leaves_the_file_byte_identical(self, tmp_path: Path) -> None:
        """A file already on target is a no-op, not a re-encode."""
        from audio_refinery.core.pipeline import process_file

        source = _write(tmp_path / "idempotent.wav", peak_dbfs=-11.0)
        process_file(source, source, _config())
        digest = _digest(source)

        second = process_file(source, source, _config())

        assert second.status is FileStatus.SKIPPED
        assert second.was_modified is False
        assert _digest(source) == digest


class TestPeakPlanDecision:
    """The decision is the measured peak, and the limiter is the guard."""

    def test_the_plan_applies_the_difference_to_the_true_peak(
        self, tmp_path: Path
    ) -> None:
        """gain = target - true peak, measured, never assumed."""
        from audio_refinery.core.pipeline import plan_peak_gain

        source = _write(tmp_path / "plan.wav", peak_dbfs=-12.0)
        levels = _levels(source)

        plan = plan_peak_gain(source, _config())

        assert plan.true_peak_dbtp == pytest.approx(levels.true_peak_dbtp)
        assert plan.gain_db == pytest.approx(TARGET_DBTP - levels.true_peak_dbtp)
        assert plan.limited is False

    def test_a_gain_that_would_pass_full_scale_is_limited(self, tmp_path: Path) -> None:
        """An under-reported true peak cannot become a clipped file.

        The branch is defensive: with a consistent measurement the applied gain
        lands the true peak on the target, so a predicted sample peak above
        0 dBFS means the two readings disagree.  It is driven here by the
        measurement that produces exactly that disagreement.
        """
        from audio_refinery.core.pipeline import plan_peak_gain

        source = _write(tmp_path / "guard.wav", peak_dbfs=-6.0)
        disagreement = LevelMetrics(
            sample_peak_dbfs=-0.05, true_peak_dbtp=-6.0, crest_factor_db=6.0
        )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                "audio_suite_shared.audio_probe.measure_levels",
                lambda *_args, **_kwargs: disagreement,
            )
            plan = plan_peak_gain(source, _config())

        assert plan.gain_db == pytest.approx(5.0)
        assert plan.limited is True
        assert plan.ceiling_dbfs == 0.0


class TestPeakLimiterApplication:
    """A limited gain is held by ``alimiter``, never by a clamp."""

    def test_the_limiter_holds_the_ceiling_instead_of_clipping(
        self, tmp_path: Path
    ) -> None:
        """Decode the result: no sample at full scale, and the peaks came down."""
        from audio_refinery.core.pipeline import PeakGainPlan, _apply_peak_plan

        source = _write(tmp_path / "limited.wav", peak_dbfs=-0.2)
        plan = PeakGainPlan(
            sample_peak_dbfs=-0.2,
            true_peak_dbtp=-0.2,
            target_dbtp=TARGET_DBTP,
            gain_db=8.0,
            limited=True,
            ceiling_dbfs=0.0,
        )

        message, applied = _apply_peak_plan(
            source, plan, _config(), _noop_emit, record_snapshot=False
        )

        assert applied is True
        decoded = AudioSegment.from_file(str(source))
        samples = np.abs(np.array(decoded.get_array_of_samples()).astype(np.int32))
        assert decoded.max_dBFS <= 0.05, "the ceiling was not held"
        assert "limited" in message
        # A clamp would hold every peak at full scale; a limiter brings the
        # whole signal's peaks down, so the level gain is not fully delivered.
        # Measured on this 0.4 s tone at +8 dB: the limiter leaves 0.9% of
        # samples at full scale and a 3.06 dB crest, the clamp 73% and 0.84 dB.
        full_scale = float((samples >= 32767).sum()) / float(len(samples))
        assert full_scale < 0.05, f"{full_scale:.1%} of samples sit at full scale"
        assert decoded.max_dBFS - decoded.dBFS > 2.0, "the waveform was flattened"
        assert decoded.dBFS < -0.2 + 7.0


class TestPeakTagsAndDepth:
    """The stage reuses the normaliser's tag and depth preservation."""

    @pytest.mark.parametrize(
        ("suffix", "fmt"),
        [("mp3", "mp3"), ("flac", "flac"), ("m4a", "mp4")],
    )
    def test_tags_survive_the_re_encode(
        self, tmp_path: Path, suffix: str, fmt: str
    ) -> None:
        """Every field on disk before the run is on disk after it."""
        from audio_refinery.core.pipeline import _run_peak_normalise

        source = _write(tmp_path / f"tagged.{suffix}", peak_dbfs=-18.0, fmt=fmt)
        _tag(source, "Peak Title")
        before = _tag_pairs(source)
        assert before, "the fixture carried no tags to preserve"

        _message, applied = _run_peak_normalise(
            source, _config(), _noop_emit, record_snapshot=False
        )

        assert applied is True
        assert _tag_pairs(source) == before

    def test_a_24_bit_wav_keeps_its_depth(self, tmp_path: Path) -> None:
        """The rewrite must not narrow a lossless source to 16-bit."""
        from audio_refinery.core.pipeline import process_file

        source = _write(
            tmp_path / "deep.wav",
            peak_dbfs=-12.0,
            parameters=["-acodec", "pcm_s24le"],
        )
        assert probe_stream(str(source)).bit_depth == 24

        process_file(source, source, _config())

        assert probe_stream(str(source)).bit_depth == 24


class TestPeakDryRun:
    """The preview writes nothing and names what it would do."""

    def test_a_dry_run_reports_the_projected_gain_and_ceiling(
        self, tmp_path: Path
    ) -> None:
        """The projected gain and the ceiling, with the file untouched."""
        from audio_refinery.core.pipeline import process_file

        source = _write(tmp_path / "dry.wav", peak_dbfs=-12.0)
        digest = _digest(source)
        config = _config()
        config.dry_run = True

        result = process_file(source, source, config)

        assert result.was_modified is False
        assert _digest(source) == digest
        message = next(
            stage.message for stage in result.stages if stage.stage == "Normalise"
        )
        assert "Would apply" in message
        assert "ceiling" in message
