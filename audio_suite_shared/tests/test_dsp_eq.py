"""test_dsp_eq.py — Locks for the parametric EQ engine (F-S1).

Every check here measures the *rendered* signal, not a value the module wrote:
the response test renders a tone at each 1/3-octave point and compares the
measured gain with ``response_curve``, and the bypass test decodes the written
WAV rather than trusting the returned array alone. A test that read the band
list back would pass while the filter did nothing.

Changed in 2.7.0: new module — the EQ engine's acceptability locks (F-S1).
"""

from __future__ import annotations

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.dsp_eq import (
    EQ_DEFAULT_Q,
    EQ_MAX_GAIN_DB,
    EQ_MAX_Q,
    MAX_EQ_BANDS,
    EqBand,
    EqSettings,
    apply_eq,
    build_eq_plugins,
    parse_band,
    response_curve,
)
from audio_suite_shared.exceptions import AudioConfigValueError

_RATE = 44_100


def _tone(freq_hz: float, seconds: float = 1.0, rate: int = _RATE) -> np.ndarray:
    """Return a stereo sine at *freq_hz* at half scale, float32."""
    t = np.arange(int(seconds * rate), dtype=np.float64) / rate
    mono = 0.5 * np.sin(2.0 * np.pi * freq_hz * t)
    return np.stack([mono, mono]).astype(np.float32)


def _rms_db(audio: np.ndarray) -> float:
    """Return the RMS of *audio* in dBFS."""
    rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
    return 20.0 * np.log10(max(rms, 1e-12))


def _measured_gain_db(band: EqBand, freq_hz: float, rate: int = _RATE) -> float:
    """Render a tone through one band and return its measured gain in dB.

    The first 200 ms are skipped so the measurement sees the filter's steady
    state rather than its start-up transient.
    """
    tone = _tone(freq_hz, seconds=1.0, rate=rate)
    rendered = apply_eq(tone, EqSettings(bands=(band,)), rate)
    skip = int(0.2 * rate)
    return _rms_db(rendered[:, skip:]) - _rms_db(tone[:, skip:])


def _write_wav(path, audio: np.ndarray, rate: int = _RATE) -> None:
    """Write a 16-bit stereo WAV through pydub, the suite's normal path."""
    pcm = (np.clip(audio.T, -1.0, 1.0) * 32767.0).astype(np.int16)
    segment = AudioSegment(
        pcm.tobytes(), frame_rate=rate, sample_width=2, channels=audio.shape[0]
    )
    segment.export(str(path), format="wav")


def _read_wav(path) -> np.ndarray:
    """Return a written WAV's samples as an ``(channels, frames)`` int16 array."""
    segment = AudioSegment.from_file(str(path))
    samples = np.array(segment.get_array_of_samples(), dtype=np.int16)
    return samples.reshape(-1, segment.channels).T


class TestTheBandModel:
    """A band the renderer cannot apply is refused, never silently ignored."""

    @pytest.mark.parametrize("kind", ["peaking", "lowshelf", "highshelf", "highpass"])
    def test_known_kinds_are_accepted(self, kind: str) -> None:
        gain = 0.0 if kind == "highpass" else 3.0
        band = EqBand(kind=kind, freq_hz=1000.0, gain_db=gain)  # type: ignore[arg-type]
        assert band.kind == kind

    def test_unknown_kind_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="Unknown EQ band kind"):
            EqBand(kind="notch", freq_hz=1000.0)  # type: ignore[arg-type]

    @pytest.mark.parametrize("freq_hz", [19.0, 20_001.0])
    def test_frequency_outside_the_audio_band_is_refused(self, freq_hz: float) -> None:
        with pytest.raises(AudioConfigValueError, match="is outside"):
            EqBand(kind="peaking", freq_hz=freq_hz)

    @pytest.mark.parametrize("gain_db", [-24.5, 24.5])
    def test_gain_outside_the_declared_range_is_refused(self, gain_db: float) -> None:
        with pytest.raises(AudioConfigValueError, match="dB is outside"):
            EqBand(kind="peaking", freq_hz=1000.0, gain_db=gain_db)
        assert abs(EQ_MAX_GAIN_DB) == 24.0

    @pytest.mark.parametrize("q", [0.05, 19.0])
    def test_q_outside_the_declared_range_is_refused(self, q: float) -> None:
        with pytest.raises(AudioConfigValueError, match="Q .* is outside"):
            EqBand(kind="peaking", freq_hz=1000.0, q=q)
        assert EQ_MAX_Q == 18.0

    def test_first_order_kind_refuses_a_q_it_cannot_apply(self) -> None:
        """pedalboard's high-pass is first-order: a Q would do nothing."""
        with pytest.raises(AudioConfigValueError, match="carries no Q"):
            EqBand(kind="highpass", freq_hz=200.0, q=2.0)

    def test_first_order_kind_refuses_a_gain_it_cannot_apply(self) -> None:
        with pytest.raises(AudioConfigValueError, match="has no gain"):
            EqBand(kind="lowpass", freq_hz=2000.0, gain_db=3.0)

    def test_a_rack_holds_at_most_eight_bands(self) -> None:
        bands = tuple(
            EqBand(kind="peaking", freq_hz=100.0 + 10.0 * i) for i in range(9)
        )
        with pytest.raises(AudioConfigValueError, match="at most 8 bands"):
            EqSettings(bands=bands)
        assert MAX_EQ_BANDS == 8
        assert EqSettings(bands=bands[:8]).active

    def test_describe_and_parse_round_trip(self) -> None:
        band = EqBand(kind="peaking", freq_hz=1000.0, gain_db=3.0, q=1.0)
        assert band.describe() == "peaking,1000,3,1"
        assert parse_band(band.describe()) == band

    @pytest.mark.parametrize(
        ("text", "gain", "q"),
        [
            ("peaking,1000,3", 3.0, EQ_DEFAULT_Q),
            ("peaking,1000,3,2", 3.0, 2.0),
            ("lowpass,8000", 0.0, EQ_DEFAULT_Q),
        ],
    )
    def test_parse_band_defaults_the_optional_fields(
        self, text: str, gain: float, q: float
    ) -> None:
        band = parse_band(text)
        assert (band.gain_db, band.q) == (gain, q)

    @pytest.mark.parametrize(
        "text",
        ["peaking", "peaking,1000,3,1,extra", "peaking,loud,3", "peaking,1000,noise"],
    )
    def test_malformed_band_strings_are_refused(self, text: str) -> None:
        with pytest.raises(AudioConfigValueError):
            parse_band(text)


class TestBypassIsBitTransparent:
    """A bypassed rack changes nothing, in memory and on disk."""

    def test_an_inactive_rack_returns_the_input_array_itself(self) -> None:
        audio = _tone(1000.0, seconds=0.1)
        settings = EqSettings(
            bands=(EqBand(kind="peaking", freq_hz=1000.0, gain_db=12.0),),
            bypass=True,
        )
        assert apply_eq(audio, settings, _RATE) is audio
        assert np.array_equal(apply_eq(audio, EqSettings(), _RATE), audio)

    def test_the_written_file_decodes_to_identical_samples(self, tmp_path) -> None:
        audio = _tone(1000.0, seconds=0.5)
        settings = EqSettings(
            bands=(EqBand(kind="peaking", freq_hz=1000.0, gain_db=12.0),),
            bypass=True,
        )
        processed = apply_eq(audio, settings, _RATE)
        _write_wav(tmp_path / "input.wav", audio)
        _write_wav(tmp_path / "bypassed.wav", processed)
        assert np.array_equal(
            _read_wav(tmp_path / "input.wav"), _read_wav(tmp_path / "bypassed.wav")
        )

    def test_a_bypassed_rack_has_a_flat_curve(self) -> None:
        freqs = np.array([100.0, 1000.0, 10_000.0])
        settings = EqSettings(
            bands=(EqBand(kind="peaking", freq_hz=1000.0, gain_db=12.0),),
            bypass=True,
        )
        assert np.array_equal(response_curve(settings, freqs), np.zeros(3))


class TestZeroGainBandIsTransparent:
    """A 0 dB band is a no-op within one 16-bit LSB, for any Q."""

    @pytest.mark.parametrize("q", [0.5, 1.0, 2.0, 8.0])
    def test_a_zero_gain_peak_changes_nothing_measurable(self, q: float) -> None:
        audio = _tone(440.0, seconds=0.2)
        settings = EqSettings(bands=(EqBand(kind="peaking", freq_hz=440.0, q=q),))
        rendered = apply_eq(audio, settings, _RATE)
        one_lsb = 1.0 / 32768.0
        assert float(np.max(np.abs(rendered - audio))) <= one_lsb


class TestTheCurveIsTheRender:
    """The drawn response and the applied filter are the same transfer function."""

    @pytest.mark.parametrize(
        ("band", "centre_hz"),
        [
            (EqBand(kind="peaking", freq_hz=1000.0, gain_db=6.0, q=1.0), 1000.0),
            (EqBand(kind="lowshelf", freq_hz=200.0, gain_db=6.0), 200.0),
            (EqBand(kind="highshelf", freq_hz=4000.0, gain_db=-6.0), 4000.0),
            (EqBand(kind="highpass", freq_hz=300.0), 300.0),
            (EqBand(kind="lowpass", freq_hz=3000.0), 3000.0),
        ],
    )
    def test_rendered_gain_matches_the_curve_at_third_octave_points(
        self, band: EqBand, centre_hz: float
    ) -> None:
        settings = EqSettings(bands=(band,))
        freqs = np.array([centre_hz * 2.0 ** (step / 3.0) for step in range(-4, 5)])
        curve = response_curve(settings, freqs, sample_rate=_RATE)
        for freq, expected in zip(freqs, curve):
            measured = _measured_gain_db(band, float(freq))
            assert abs(measured - float(expected)) <= 0.5, (
                f"{band.describe()} at {freq:.0f} Hz: measured {measured:.2f} dB, "
                f"curve {float(expected):.2f} dB"
            )

    def test_the_curve_follows_the_band_it_describes(self) -> None:
        boost = EqSettings(bands=(EqBand(kind="peaking", freq_hz=1000.0, gain_db=9.0),))
        cut = EqSettings(bands=(EqBand(kind="peaking", freq_hz=1000.0, gain_db=-9.0),))
        freqs = np.array([1000.0])
        assert float(response_curve(boost, freqs)[0]) == pytest.approx(9.0, abs=0.5)
        assert float(response_curve(cut, freqs)[0]) == pytest.approx(-9.0, abs=0.5)


class TestNyquistRefusal:
    """A band the renderer cannot place is an error, not a clamped band."""

    def test_a_band_above_nyquist_is_refused_before_rendering(self) -> None:
        audio = _tone(1000.0, seconds=0.05, rate=22_050)
        settings = EqSettings(bands=(EqBand(kind="peaking", freq_hz=15_000.0),))
        with pytest.raises(AudioConfigValueError, match="Nyquist"):
            apply_eq(audio, settings, 22_050)
        with pytest.raises(AudioConfigValueError, match="Nyquist"):
            response_curve(settings, np.array([1000.0]), sample_rate=22_050)

    def test_an_inactive_rack_builds_no_plugins(self) -> None:
        assert build_eq_plugins(EqSettings()) == []
        assert (
            build_eq_plugins(
                EqSettings(bands=(EqBand(kind="peaking", freq_hz=100.0),), bypass=True)
            )
            == []
        )
