"""Tests for ``ml_denoiser.core.rnnoise_engine``.

``pyrnnoise`` is part of the optional ``ml`` extra, so the default suite installs
a fake model in ``sys.modules`` and asserts what the adapter does with it.  The
fake reproduces the two measured quirks the adapter exists for: frames are cut
at 480 samples, and the model's answer may be one sample longer or shorter than
the input (D116).

:class:`TestRealModel` is marked ``real_ml`` and deselected from the default run.
It is the only place the real library is called, and it asserts the file's audio
outcome — the length, the rate and the measured attenuation — not the adapter's
own bookkeeping.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from audio_suite_shared.exceptions import AudioMissingDependencyError
from ml_denoiser.core import rnnoise_engine
from ml_denoiser.core.models import FRAME_SIZE, MIN_CHANGE_DB
from ml_denoiser.core.rnnoise_engine import (
    denoise_samples,
    denoise_segment,
    missing_dependency_reason,
    require_rnnoise,
    rms_dbfs,
)

SR = 44100


def _tone(path: Path, *, seconds: float = 0.5) -> Path:
    """Write a mono 440 Hz tone at -6 dBFS and return its path."""
    tone = Sine(440).to_audio_segment(duration=int(seconds * 1000), volume=-6)
    tone.set_channels(1).export(str(path), format="wav")
    return path


def _install_fake_rnnoise(
    monkeypatch: pytest.MonkeyPatch,
    *,
    gain: float = 0.5,
    extra_samples: int = 0,
    seen: list[tuple[int, int, int]] | None = None,
) -> None:
    """Register a fake ``pyrnnoise`` that scales the signal by *gain*.

    Args:
        monkeypatch: The active monkeypatch fixture.
        gain: Per-sample multiplier the fake model applies.
        extra_samples: Samples appended to (or trimmed from, when negative) the
            model's answer, reproducing the resampler's off-by-a-sample length.
        seen: When given, records ``(sample_rate, channels, samples)`` per call.
    """
    module = types.ModuleType("pyrnnoise")

    class _FakeRNNoise:
        def __init__(self, sample_rate: int) -> None:
            self.sample_rate = sample_rate

        def denoise_chunk(self, chunk: Any, partial: bool = False) -> Any:
            array = np.atleast_2d(np.asarray(chunk, dtype=np.int16))
            if seen is not None:
                seen.append((self.sample_rate, array.shape[0], array.shape[1]))
            processed = np.rint(array.astype(np.float64) * gain).astype(np.int16)
            if extra_samples:
                pad = np.zeros((array.shape[0], abs(extra_samples)), dtype=np.int16)
                if extra_samples > 0:
                    processed = np.concatenate([processed, pad], axis=1)
                else:
                    processed = processed[:, :extra_samples]
            for start in range(0, processed.shape[1], FRAME_SIZE):
                frame = processed[:, start : start + FRAME_SIZE]
                yield np.zeros((array.shape[0], 1), dtype=np.float32), frame

    module.RNNoise = _FakeRNNoise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyrnnoise", module)


class TestAvailability:
    """A missing extra is a named dependency error, not an ImportError."""

    def test_missing_rnnoise_reason_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)

        reason = missing_dependency_reason()

        assert reason is not None
        assert "RNNoise is not installed" in reason
        assert "ml" in reason

    def test_require_rnnoise_raises_the_dependency_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)

        with pytest.raises(AudioMissingDependencyError) as caught:
            require_rnnoise()
        assert "pyrnnoise" in str(caught.value).lower() or "RNNoise" in str(
            caught.value
        )

    def test_installed_rnnoise_reports_no_reason(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)

        assert missing_dependency_reason() is None
        require_rnnoise()


class TestRms:
    """The level measurement the report quotes."""

    def test_full_scale_square_wave_is_zero_dbfs(self) -> None:
        chunk = np.full((1, 100), 32767, dtype=np.int16)

        assert rms_dbfs(chunk) == pytest.approx(0.0, abs=0.01)

    def test_half_scale_is_about_minus_six_db(self) -> None:
        chunk = np.full((1, 100), 16384, dtype=np.int16)

        assert rms_dbfs(chunk) == pytest.approx(-6.02, abs=0.05)

    def test_silence_is_floored_not_infinite(self) -> None:
        assert rms_dbfs(np.zeros((2, 10), dtype=np.int16)) == -120.0

    def test_an_empty_chunk_is_floored(self) -> None:
        assert rms_dbfs(np.zeros((2, 0), dtype=np.int16)) == -120.0


class TestDenoiseSamples:
    """Shape, length and blend are what the written file depends on."""

    def test_the_model_is_called_at_the_source_rate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[tuple[int, int, int]] = []
        _install_fake_rnnoise(monkeypatch, seen=seen)
        chunk = np.full((2, 1000), 1000, dtype=np.int16)

        denoise_samples(chunk, SR)

        assert seen == [(SR, 2, 1000)]

    def test_an_overshooting_model_is_trimmed_to_the_input_length(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, extra_samples=37)
        chunk = np.full((1, 1000), 1000, dtype=np.int16)

        out = denoise_samples(chunk, SR)

        assert out.shape == chunk.shape

    def test_a_short_model_answer_is_padded_from_the_source_tail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A dropped frame must not silence the end of the file."""
        _install_fake_rnnoise(monkeypatch, extra_samples=-480)
        chunk = np.full((1, 2000), 1000, dtype=np.int16)

        out = denoise_samples(chunk, SR)

        assert out.shape == chunk.shape
        # The model's own output was halved; the restored tail keeps the source.
        assert out[0, 0] == 500
        assert out[0, -1] == 1000

    def test_a_blend_keeps_part_of_the_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.0)
        chunk = np.full((1, 960), 1000, dtype=np.int16)

        half = denoise_samples(chunk, SR, amount=0.5)

        assert np.allclose(half, 500, atol=1)
        assert np.allclose(denoise_samples(chunk, SR, amount=1.0), 0)

    def test_a_zero_amount_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_rnnoise(monkeypatch)

        with pytest.raises(ValueError):
            denoise_samples(np.zeros((1, 10), dtype=np.int16), SR, amount=0.0)

    def test_a_one_dimensional_chunk_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)

        with pytest.raises(ValueError):
            denoise_samples(np.zeros(10, dtype=np.int16), SR)

    def test_an_empty_chunk_round_trips_unchanged(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch)
        chunk = np.zeros((2, 0), dtype=np.int16)

        assert denoise_samples(chunk, SR).shape == (2, 0)


class TestDenoiseSegment:
    """The decoded segment keeps its rate, channels and length."""

    def test_the_written_segment_decodes_to_the_attenuated_level(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        source = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav")))

        result = denoise_segment(source, 1.0)

        target = tmp_path / "out.wav"
        result.audio.export(str(target), format="wav")
        decoded = AudioSegment.from_wav(str(target))

        assert decoded.frame_rate == source.frame_rate
        assert decoded.channels == source.channels
        assert len(decoded) == len(source)
        assert result.was_modified is True
        # Halving the signal is -6 dB; measure the file, not the result object.
        assert decoded.rms == pytest.approx(source.rms / 2, rel=0.02)
        assert result.attenuation_db() == pytest.approx(6.02, abs=0.1)

    def test_a_stereo_source_stays_stereo(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        mono = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav")))
        stereo = AudioSegment.from_mono_audiosegments(mono, mono)

        result = denoise_segment(stereo, 1.0)

        assert result.audio.channels == 2
        assert len(result.audio) == len(stereo)

    def test_a_silent_file_is_not_modified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty room stays clean: no level moved, so nothing is rewritten."""
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        silence = AudioSegment.silent(duration=300, frame_rate=SR).set_channels(1)

        result = denoise_segment(silence, 1.0)

        assert result.was_modified is False
        assert result.rms_before_db == result.rms_after_db == -120.0

    def test_an_unchanged_level_is_below_the_change_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _install_fake_rnnoise(monkeypatch, gain=1.0)
        source = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav")))

        result = denoise_segment(source, 1.0)

        assert result.attenuation_db() < MIN_CHANGE_DB
        assert result.was_modified is False

    def test_missing_dependency_is_named_before_decoding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)
        source = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav")))

        with pytest.raises(AudioMissingDependencyError):
            denoise_segment(source)


@pytest.mark.real_ml
class TestRealModel:
    """The real RNNoise path: ``pytest -m real_ml`` with the ``ml`` extra.

    Deselected from the default run because it needs the extra.  The assertions
    are audio outcomes: the length the model returns (within a frame, which the
    adapter must fix) and the attenuation it actually applies to a tone.
    """

    def test_a_real_denoise_keeps_the_length_and_lowers_the_level(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip(
            "pyrnnoise", reason="the 'ml' extra is not installed (uv sync --extra ml)"
        )
        source = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav", seconds=1.0)))

        result = denoise_segment(source, 1.0)

        assert len(result.audio) == len(source)
        assert result.audio.frame_rate == source.frame_rate
        assert result.was_modified is True
        assert result.attenuation_db() > 6.0

        target = tmp_path / "denoised.wav"
        result.audio.export(str(target), format="wav")
        decoded = AudioSegment.from_wav(str(target))
        assert len(decoded) == len(source)
        assert decoded.rms < source.rms / 2

    def test_a_real_blend_is_between_the_two_levels(self, tmp_path: Path) -> None:
        pytest.importorskip(
            "pyrnnoise", reason="the 'ml' extra is not installed (uv sync --extra ml)"
        )
        source = AudioSegment.from_wav(str(_tone(tmp_path / "tone.wav", seconds=1.0)))

        full = denoise_segment(source, 1.0)
        half = denoise_segment(source, 0.5)

        assert half.rms_after_db > full.rms_after_db
        assert half.rms_after_db < rnnoise_engine.rms_dbfs(
            np.asarray(source.get_array_of_samples(), dtype=np.int16).reshape(1, -1)
        )
