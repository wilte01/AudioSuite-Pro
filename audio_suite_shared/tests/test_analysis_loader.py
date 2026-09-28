"""
test_analysis_loader.py
Pytest suite for audio_suite_shared.analysis_loader.

Covers:
  - load_analysis_audio   (nominal decode, duration cap, stereo downmix, dtype,
                          real generated audio, failure paths)
  - check_min_duration    (the too-short and non-positive-sample-rate guards)
  - rms_energy_db         (digital silence, empty signal, measured level)
  - is_effectively_silent (threshold behaviour on real signals)

``load_analysis_audio`` is a shared seam: key detection, BPM, tempo and mood
analysis all decode through it, so an untested branch here is an untested
branch in four tools at once.  The failure cases therefore assert the
*specific* exception type each caller already catches, and the success cases
assert measured properties (sample count, sample rate, channel downmix, peak
amplitude) rather than merely that a call happened.

Decoder-dependent behaviour is pinned by feeding the loader the exact array the
real decoder was observed to return, rather than by hoping a particular audio
backend fails in a particular way on a particular host.
"""

from __future__ import annotations

import wave

import numpy as np
import pytest

from audio_suite_shared import analysis_loader
from audio_suite_shared.analysis_loader import (
    MIN_ANALYSIS_SECONDS,
    SILENCE_RMS_THRESHOLD,
    check_min_duration,
    is_effectively_silent,
    load_analysis_audio,
    rms_energy_db,
)
from audio_suite_shared.exceptions import AudioAnalysisError, AudioCodecError

_SR = 22050


def _tone(seconds: float = 1.0, sr: int = _SR, freq: float = 220.0) -> np.ndarray:
    """A unit-amplitude sine; callers scale it as needed."""
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    return np.sin(2.0 * np.pi * freq * t)


def _write_mono_wav(path: str, y: np.ndarray, sr: int = _SR) -> str:
    """Write a real 16-bit mono WAV and return its path."""
    pcm = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm)
    return path


def _write_stereo_wav(
    path: str, left: np.ndarray, right: np.ndarray, sr: int = _SR
) -> str:
    """Write a real 16-bit stereo WAV by interleaving *left* and *right*."""
    interleaved = np.empty(2 * len(left), dtype=np.float64)
    interleaved[0::2] = left
    interleaved[1::2] = right
    pcm = (np.clip(interleaved, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(path, "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm)
    return path


def _fake_librosa_load(monkeypatch: pytest.MonkeyPatch, y: np.ndarray, sr: int) -> None:
    """Pin ``librosa.load`` to the exact array/sample-rate pair under test.

    The degenerate decode branch is backend-dependent, not hypothetical:
    librosa ≤ 0.11's audioread fallback returns an empty signal with
    ``sr == 0`` on a corrupt container, while librosa ≥ 1.0 removed the
    fallback and raises soundfile's format error instead — the uv.lock pins
    both versions by Python version (0.11.0 on py<3.12, 1.0.0 on py≥3.12).
    Substituting the loader here (and pinning the raise branch via
    ``librosa.load`` itself elsewhere in this file) lets both branches be
    asserted identically everywhere instead of depending on the host's audio
    backend; batch-level callers assert only the reported-error outcome.
    """
    import librosa

    def _load(*args: object, **kwargs: object):
        return y.astype(np.float32), sr

    monkeypatch.setattr(librosa, "load", _load)


# ═════════════════════════════════════════════════════════════════════════════
# load_analysis_audio — nominal decode
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadAnalysisAudioNominal:
    def test_decodes_a_real_file_and_reports_measured_properties(
        self, tmp_path
    ) -> None:
        path = _write_mono_wav(str(tmp_path / "tone.wav"), 0.5 * _tone(1.0))
        y, sr = load_analysis_audio(path)
        assert sr == _SR
        assert y.dtype == np.float64
        assert y.ndim == 1
        # Exact count, not "about" — a truncated window is the failure this
        # shared seam exists to prevent.
        assert len(y) == _SR
        assert np.max(np.abs(y)) == pytest.approx(0.5, abs=1.0e-4)
        assert not is_effectively_silent(y)

    def test_duration_cap_truncates_the_decoded_window(self, tmp_path) -> None:
        path = _write_mono_wav(str(tmp_path / "long.wav"), 0.5 * _tone(4.0))
        capped, _ = load_analysis_audio(path, max_duration=1)
        assert len(capped) == _SR
        full, _ = load_analysis_audio(path, max_duration=0)
        assert len(full) == 4 * _SR

    def test_stereo_input_is_downmixed_to_mono(self, tmp_path) -> None:
        """Two channels in, one channel out, at mono length.

        The two channels carry different frequencies, so an accidental
        "concatenate instead of downmix" would double the sample count; an
        accidental "pass channel 1 through" would show up in the spectrum.
        """
        path = _write_stereo_wav(
            str(tmp_path / "stereo.wav"),
            0.4 * _tone(1.0, freq=220.0),
            0.4 * _tone(1.0, freq=880.0),
        )
        y, sr = load_analysis_audio(path)
        assert sr == _SR
        assert y.ndim == 1
        assert len(y) == _SR
        assert np.max(np.abs(y)) > 0.25

    def test_native_sample_rate_is_preserved_not_resampled(self, tmp_path) -> None:
        path = _write_mono_wav(
            str(tmp_path / "rate.wav"), 0.5 * _tone(1.0, sr=16000), sr=16000
        )
        y, sr = load_analysis_audio(path)
        assert sr == 16000
        assert len(y) == 16000

    def test_dsp_ready_dtype_is_float64(self, tmp_path) -> None:
        """Feature extraction accumulates in float64; a float32 return would
        reintroduce quantisation noise the loader exists to remove."""
        path = _write_mono_wav(str(tmp_path / "tone.wav"), 0.5 * _tone(1.0))
        y, _ = load_analysis_audio(path)
        assert y.dtype == np.dtype(np.float64)

    def test_min_seconds_override_accepts_a_shorter_signal(self, tmp_path) -> None:
        path = _write_mono_wav(str(tmp_path / "short.wav"), 0.5 * _tone(0.25))
        with pytest.raises(AudioAnalysisError):
            load_analysis_audio(path)
        y, sr = load_analysis_audio(path, min_seconds=0.2)
        assert len(y) == int(0.25 * _SR)
        assert sr == _SR

    def test_min_seconds_override_rejects_a_longer_signal(self, tmp_path) -> None:
        path = _write_mono_wav(str(tmp_path / "long.wav"), 0.5 * _tone(1.0))
        with pytest.raises(AudioAnalysisError):
            load_analysis_audio(path, min_seconds=5.0)


# ═════════════════════════════════════════════════════════════════════════════
# load_analysis_audio — failure paths (the types callers already catch)
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadAnalysisAudioFailures:
    def test_missing_file_raises_audio_codec_error(self, tmp_path) -> None:
        with pytest.raises(AudioCodecError):
            load_analysis_audio(str(tmp_path / "does_not_exist.wav"))

    def test_empty_file_raises_audio_codec_error(self, tmp_path) -> None:
        path = str(tmp_path / "empty.wav")
        open(path, "wb").close()
        with pytest.raises(AudioCodecError):
            load_analysis_audio(path)

    def test_decoder_exception_raises_audio_codec_error(
        self, tmp_path, monkeypatch
    ) -> None:
        """Whatever the backend raises, callers see the one declared type."""
        import librosa

        def _boom(*args: object, **kwargs: object):
            raise RuntimeError("backend exploded")

        monkeypatch.setattr(librosa, "load", _boom)
        with pytest.raises(AudioCodecError):
            load_analysis_audio(str(tmp_path / "any.flac"))

    def test_zero_rate_decode_raises_audio_analysis_error(
        self, tmp_path, monkeypatch
    ) -> None:
        """Regression: a corrupt container decodes to an empty signal at
        ``sr == 0``.  The too-short guard detected that correctly, then divided
        by zero formatting its own message, so every analysis tool received a
        ``ZeroDivisionError`` instead of the documented ``AudioAnalysisError``.
        """
        _fake_librosa_load(monkeypatch, np.zeros(0, dtype=np.float32), 0)
        with pytest.raises(AudioAnalysisError):
            load_analysis_audio(str(tmp_path / "broken.flac"))

    def test_negative_rate_decode_raises_audio_analysis_error(
        self, tmp_path, monkeypatch
    ) -> None:
        _fake_librosa_load(monkeypatch, np.zeros(0, dtype=np.float32), -1)
        with pytest.raises(AudioAnalysisError):
            load_analysis_audio(str(tmp_path / "broken.flac"))

    def test_short_decode_raises_audio_analysis_error(
        self, tmp_path, monkeypatch
    ) -> None:
        _fake_librosa_load(
            monkeypatch, np.zeros(int(MIN_ANALYSIS_SECONDS * _SR / 2), np.float32), _SR
        )
        with pytest.raises(AudioAnalysisError):
            load_analysis_audio(str(tmp_path / "stub.flac"))

    def test_codec_error_chains_the_original_exception(self, tmp_path) -> None:
        """Callers log the causal chain, so ``__cause__`` must be preserved."""
        with pytest.raises(AudioCodecError) as excinfo:
            load_analysis_audio(str(tmp_path / "nope.wav"))
        assert excinfo.value.__cause__ is not None
        assert excinfo.value.context["file"] == str(tmp_path / "nope.wav")

    def test_decoder_failure_is_logged(self, tmp_path, caplog) -> None:
        with caplog.at_level("ERROR", logger=analysis_loader.logger.name):
            with pytest.raises(AudioCodecError):
                load_analysis_audio(str(tmp_path / "nope.wav"))
        assert any(
            "failed to decode" in record.message
            for record in caplog.records
            if record.name == analysis_loader.logger.name
        )

    def test_both_declared_failure_types_are_skippable_by_the_batch_tools(
        self,
    ) -> None:
        """The two types the loader raises are the two the batch engines treat
        as a skip rather than an error, so a bad file never aborts a run."""
        from mood_analysis_batch_tagger.core.batch_analysis_engine import (
            _SKIPPABLE_ANALYSIS_ERRORS,
        )

        assert AudioCodecError in _SKIPPABLE_ANALYSIS_ERRORS
        assert AudioAnalysisError in _SKIPPABLE_ANALYSIS_ERRORS


# ═════════════════════════════════════════════════════════════════════════════
# check_min_duration
# ═════════════════════════════════════════════════════════════════════════════


class TestCheckMinDuration:
    def test_accepts_a_signal_at_exactly_the_minimum(self) -> None:
        sr = 100
        y = np.ones(int(MIN_ANALYSIS_SECONDS * sr), dtype=np.float64)
        check_min_duration(y, sr)

    def test_rejects_a_signal_one_sample_below_the_minimum(self) -> None:
        sr = 100
        y = np.ones(int(MIN_ANALYSIS_SECONDS * sr) - 1, dtype=np.float64)
        with pytest.raises(AudioAnalysisError):
            check_min_duration(y, sr)

    def test_zero_sample_rate_raises_audio_analysis_error_not_a_crash(self) -> None:
        """The regression itself, isolated from the decoder."""
        with pytest.raises(AudioAnalysisError) as excinfo:
            check_min_duration(np.zeros(0, dtype=np.float64), 0)
        assert "too short" in str(excinfo.value)
        assert "0.00s" in str(excinfo.value)

    def test_negative_sample_rate_raises_audio_analysis_error(self) -> None:
        with pytest.raises(AudioAnalysisError):
            check_min_duration(np.zeros(10, dtype=np.float64), -1)

    def test_message_reports_the_measured_duration(self) -> None:
        sr = 100
        y = np.ones(10, dtype=np.float64)
        with pytest.raises(AudioAnalysisError) as excinfo:
            check_min_duration(y, sr)
        assert "0.10s" in str(excinfo.value)
        assert excinfo.value.context["min_seconds"] == MIN_ANALYSIS_SECONDS

    def test_custom_min_seconds_is_carried_in_the_context(self) -> None:
        with pytest.raises(AudioAnalysisError) as excinfo:
            check_min_duration(np.ones(10, dtype=np.float64), 100, min_seconds=3.5)
        assert excinfo.value.context["min_seconds"] == 3.5

    def test_returns_none_for_an_acceptable_signal(self) -> None:
        y = np.ones(int(MIN_ANALYSIS_SECONDS * _SR), dtype=np.float64)
        assert check_min_duration(y, _SR) is None


# ═════════════════════════════════════════════════════════════════════════════
# rms_energy_db / is_effectively_silent
# ═════════════════════════════════════════════════════════════════════════════


class TestRmsEnergyDb:
    def test_half_amplitude_sine_measures_the_analytic_level(self) -> None:
        # RMS of a 0.5-amplitude sine is 0.5/sqrt(2) -> -9.03 dBFS.
        y = 0.5 * _tone(1.0)
        assert rms_energy_db(y) == pytest.approx(-9.03, abs=0.01)

    def test_measured_rms_matches_the_definition(self) -> None:
        y = np.full(1000, 0.25, dtype=np.float64)
        assert rms_energy_db(y) == pytest.approx(20.0 * np.log10(0.25))

    def test_empty_signal_returns_the_epsilon_floor(self) -> None:
        assert rms_energy_db(np.zeros(0, dtype=np.float64)) == -240.0

    def test_digital_silence_returns_the_epsilon_floor(self) -> None:
        assert rms_energy_db(np.zeros(1000, dtype=np.float64)) == -240.0

    def test_halving_the_amplitude_costs_six_db(self) -> None:
        loud = _tone(1.0)
        quiet = loud * 0.5
        assert rms_energy_db(loud) - rms_energy_db(quiet) == pytest.approx(
            6.02, abs=0.01
        )


class TestIsEffectivelySilent:
    def test_threshold_constant_is_the_documented_minus_sixty_dbfs(self) -> None:
        assert 20.0 * np.log10(SILENCE_RMS_THRESHOLD) == pytest.approx(-60.0)

    def test_digital_silence_is_silent(self) -> None:
        assert is_effectively_silent(np.zeros(1000, dtype=np.float64)) is True

    def test_a_usable_tone_is_not_silent(self) -> None:
        assert is_effectively_silent(0.5 * _tone(1.0)) is False

    def test_a_quiet_but_audible_signal_is_not_silent(self) -> None:
        """The check is global RMS, not per-window, so sparse loud material
        survives — far below typical music, but above the threshold."""
        assert is_effectively_silent(0.05 * _tone(1.0)) is False

    def test_a_signal_just_under_the_threshold_is_silent(self) -> None:
        # A sine of amplitude A has RMS A/sqrt(2), so scale by sqrt(2) to land
        # at a chosen RMS rather than assuming amplitude == RMS.
        under = (SILENCE_RMS_THRESHOLD * 0.9 * np.sqrt(2.0)) * _tone(1.0)
        assert rms_energy_db(under) < 20.0 * np.log10(SILENCE_RMS_THRESHOLD)
        assert is_effectively_silent(under) is True

    def test_a_signal_just_over_the_threshold_is_not_silent(self) -> None:
        over = (SILENCE_RMS_THRESHOLD * 1.1 * np.sqrt(2.0)) * _tone(1.0)
        assert rms_energy_db(over) > 20.0 * np.log10(SILENCE_RMS_THRESHOLD)
        assert is_effectively_silent(over) is False

    def test_a_real_loaded_file_is_not_silent(self, tmp_path) -> None:
        y, _ = load_analysis_audio(
            _write_mono_wav(str(tmp_path / "t.wav"), 0.5 * _tone(1.0))
        )
        assert is_effectively_silent(y) is False


# ═════════════════════════════════════════════════════════════════════════════
# Golden-vector measurement (plan iteration 5, item F1 / audit #19)
# ═════════════════════════════════════════════════════════════════════════════
# The pre-existing classes above already assert measured properties on real
# files, so the loader's nominal/failure/threshold contract needs no
# duplication.  The one vector item F1 names explicitly -- "white noise with a
# known RMS feeding the energy features" -- was missing: every existing RMS
# test works on an in-memory sine or a tone file, so nothing pinned that a
# *known-level broadband* signal keeps its level through the real
# encode/decode round trip, which is the seam that would silently rescale or
# clip every downstream analysis.
#
# Tolerance provenance (recorded in the Completion Log): the band is derived
# from the 16-bit grid, not fitted to output.  Writing with `.astype("<i2")`
# truncates toward zero rather than rounding, so every generated file carries
# a systematic half-LSB magnitude shrink of `step / 2` on top of the ordinary
# `step / sqrt(12)` quantisation noise; the decoder then rescales by
# 32767/32768.  The bound below is the sum of those terms, rounded up, and it
# is ~0.65 LSB -- tight enough that any real rescale (2% is 0.17 dB, three
# orders of magnitude above the band) cannot hide inside it.
_NOISE_RMS_VECTORS: tuple[float, ...] = (0.2, 0.05, 0.01)
_QUANT_STEP = 1.0 / 32767.0
_LEVEL_ABS_TOLERANCE = 0.5 * _QUANT_STEP + _QUANT_STEP / np.sqrt(12.0) + _QUANT_STEP


def _db_tolerance(constructed_rms: float) -> float:
    """The level band above, expressed in dB for a given signal level."""
    return 20.0 * np.log10(1.0 + _LEVEL_ABS_TOLERANCE / constructed_rms)


def _seeded_noise_at_rms(rms: float, seed: int = 12345) -> np.ndarray:
    """Seeded white noise rescaled to an exact RMS, well below full scale.

    The scale matters: a Gaussian's peaks exceed its RMS by several sigma, so
    a noise fixture built near RMS 0.5 would clip on encode and the measured
    level would no longer be the constructed one.
    """
    generator = np.random.default_rng(seed)
    noise = generator.standard_normal(int(_SR * 2.0))
    noise = noise / np.sqrt(np.mean(np.square(noise)))
    return (noise * rms).astype(np.float64)


class TestGoldenVectorMeasuredLevelFidelity:
    """A known-RMS broadband signal keeps its level through a real file."""

    @pytest.mark.parametrize("constructed_rms", _NOISE_RMS_VECTORS)
    def test_noise_rms_survives_the_encode_decode_round_trip(
        self, tmp_path, constructed_rms: float
    ) -> None:
        source = _seeded_noise_at_rms(constructed_rms)
        path = _write_mono_wav(str(tmp_path / "noise.wav"), source)
        decoded, _ = load_analysis_audio(path)
        measured_rms = float(np.sqrt(np.mean(np.square(decoded))))
        assert measured_rms == pytest.approx(
            constructed_rms, abs=_LEVEL_ABS_TOLERANCE
        ), (
            f"level shifted by {measured_rms - constructed_rms:+.2e} across a "
            f"16-bit round trip (band {_LEVEL_ABS_TOLERANCE:.2e})"
        )

    @pytest.mark.parametrize("constructed_rms", _NOISE_RMS_VECTORS)
    def test_energy_db_matches_the_analytic_value(
        self, tmp_path, constructed_rms: float
    ) -> None:
        """A level that survives intact must also report the documented dB,
        against 20*log10(RMS) widened by the derived level band."""
        path = _write_mono_wav(
            str(tmp_path / "noise.wav"), _seeded_noise_at_rms(constructed_rms)
        )
        decoded, _ = load_analysis_audio(path)
        measured_db = rms_energy_db(decoded)
        analytic_db = 20.0 * np.log10(constructed_rms)
        assert measured_db == pytest.approx(
            analytic_db, abs=_db_tolerance(constructed_rms)
        ), (
            f"RMS {constructed_rms}: reported {measured_db:.5f} dB vs analytic "
            f"{analytic_db:.5f} dB (band {_db_tolerance(constructed_rms):.5f} dB)"
        )

    def test_relative_level_survives_to_within_two_thousandths(self, tmp_path) -> None:
        """A scale-invariant statement of the same property: halving the
        constructed RMS must halve the measured RMS."""
        ratios = []
        for constructed_rms in (0.2, 0.1):
            path = _write_mono_wav(
                str(tmp_path / f"r{constructed_rms}.wav"),
                _seeded_noise_at_rms(constructed_rms),
            )
            decoded, _ = load_analysis_audio(path)
            ratios.append(float(np.sqrt(np.mean(np.square(decoded)))) / constructed_rms)
        assert ratios[0] == pytest.approx(ratios[1], rel=2.0e-3)

    def test_silence_classification_agrees_across_the_vector_ladder(
        self, tmp_path
    ) -> None:
        """Every level in the ladder is above the -60 dBFS guard, so the
        loader must not classify any of them as silent -- the guard is
        about unusable audio, not quiet audio."""
        for constructed_rms in _NOISE_RMS_VECTORS:
            path = _write_mono_wav(
                str(tmp_path / f"n{constructed_rms}.wav"),
                _seeded_noise_at_rms(constructed_rms),
            )
            decoded, _ = load_analysis_audio(path)
            assert is_effectively_silent(decoded) is False, (
                f"RMS {constructed_rms} ({rms_energy_db(decoded):.1f} dB) was "
                f"misclassified as silent"
            )

    def test_the_round_trip_is_bit_reproducible(self, tmp_path) -> None:
        """Same seed, same file bytes: the decoded array must be identical,
        which is what makes every downstream vector reproducible."""
        first = _write_mono_wav(str(tmp_path / "a.wav"), _seeded_noise_at_rms(0.05))
        second = _write_mono_wav(str(tmp_path / "b.wav"), _seeded_noise_at_rms(0.05))
        decoded_a, sr_a = load_analysis_audio(first)
        decoded_b, sr_b = load_analysis_audio(second)
        assert sr_a == sr_b
        assert np.array_equal(decoded_a, decoded_b)
