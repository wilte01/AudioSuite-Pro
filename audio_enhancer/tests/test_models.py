"""Locks for ``audio_enhancer.core.models`` after 2.4.1 WP-0.

After WP-0 the module only re-exports the shared DSP model, so these tests
assert three things: the identity that makes a second definition impossible,
that every preset still matches the shared table field by field, and — the only
check that proves the *applied* preset is the *displayed* preset — the output
gain measured from a decoded file rather than read back off the object the
chain was handed.

PLAN_2026-11-03_2.4.1_stop_the_drift.md §2.3.

Changed in 2.4.1: added with WP-0 as the enhancer model's lock - shared
identity, the field-by-field preset table, and the declared gain measured
from a decoded file rather than read back off the object the chain was
handed.
"""

from __future__ import annotations

from dataclasses import fields, replace
from pathlib import Path

import numpy as np
import pytest

from audio_enhancer.core import models
from audio_suite_shared import dsp_models
from audio_suite_shared.dsp_chain import apply_enhancement_chain, compute_rms_db

#: Sample rate of the measurement fixture; 44.1 kHz is what the tools write.
SR = 44_100


class TestSharedIdentity:
    """The enhancer holds no second copy of the model."""

    def test_presets_is_the_shared_table(self) -> None:
        assert models.PRESETS is dsp_models.PRESETS

    def test_enhancement_params_is_the_shared_class(self) -> None:
        assert models.EnhancementParams is dsp_models.EnhancementParams

    def test_preset_name_is_the_shared_enum(self) -> None:
        assert models.PresetName is dsp_models.PresetName

    def test_every_preset_matches_the_shared_table_field_by_field(self) -> None:
        """A reintroduced local PRESETS dict fails here, not only on identity."""
        assert len(dsp_models.PRESETS) >= 3, "an empty table would pass vacuously"
        assert set(models.PRESETS) == set(dsp_models.PRESETS)
        for name, shared in dsp_models.PRESETS.items():
            local = models.PRESETS[name]
            for field in fields(dsp_models.EnhancementParams):
                assert getattr(local, field.name) == getattr(shared, field.name), (
                    f"{name.value}.{field.name} diverged from the shared table"
                )


def _tone(
    peak: float = 0.25, seconds: float = 1.0, freq_hz: float = 1000.0
) -> np.ndarray:
    """Return a stereo 1 kHz tone as ``(channels, samples)`` at *peak*."""
    n = int(SR * seconds)
    t = np.arange(n, dtype=np.float64) / SR
    return np.tile(peak * np.sin(2.0 * np.pi * freq_hz * t), (2, 1))


def _write_wav(audio: np.ndarray, path: Path) -> Path:
    """Write ``(channels, samples)`` audio to a real 16-bit WAV and return it."""
    from pydub import AudioSegment

    frames = np.clip(np.asarray(audio, dtype=np.float64).T, -1.0, 1.0)
    segment = AudioSegment(
        data=(frames * 32767.0).astype("<i2").tobytes(),
        sample_width=2,
        frame_rate=SR,
        channels=2,
    )
    segment.export(str(path), format="wav")
    return path


def _decode_rms_db(path: Path) -> list[float]:
    """Decode *path* from disk and return one RMS level in dBFS per channel."""
    from pydub import AudioSegment

    segment = AudioSegment.from_wav(str(path))
    assert segment.frame_rate == SR, "the fixture must not be resampled"
    assert segment.channels == 2, "the measurement is per channel"
    frames = np.frombuffer(segment.raw_data, dtype="<i2").reshape(-1, 2)
    return [compute_rms_db(frames[:, channel] / 32768.0) for channel in range(2)]


class TestDeclaredGainReachesTheWrittenFile:
    """Decode the written file and measure it; never read the object back."""

    def test_the_declared_output_gain_is_what_the_file_carries(
        self, tmp_path: Path
    ) -> None:
        """The preset's declared gain must arrive in the decoded audio.

        Measured 2026-11-03 on this fixture: the Moderate chain at its declared
        ``output_gain_db`` of 4.0 dB lands 4.000 dB above the same preset pinned
        to 0.0 dB, and +2.135 dB above the source. The comparison is that
        differential rather than an absolute band around 4 dB because
        pedalboard's Limiter is level-dependent — it contributes +2.49 dB
        in-chain at this level, so an absolute band would measure the limiter
        instead of the declared gain.
        """
        params = dsp_models.PRESETS[dsp_models.PresetName.MODERATE]
        unboosted = replace(params, output_gain_db=0.0)
        tone = _tone()
        baseline = _write_wav(
            apply_enhancement_chain(tone.copy(), SR, unboosted), tmp_path / "base.wav"
        )
        declared = _write_wav(
            apply_enhancement_chain(tone.copy(), SR, params), tmp_path / "declared.wav"
        )

        before = _decode_rms_db(baseline)
        after = _decode_rms_db(declared)
        assert len(after) == 2
        for channel, (start, end) in enumerate(zip(before, after, strict=True)):
            assert end - start == pytest.approx(params.output_gain_db, abs=0.2), (
                f"channel {channel}: the file carries {end - start:+.3f} dB, "
                f"the model declares {params.output_gain_db:+.3f} dB"
            )

    def test_the_chain_that_wrote_the_file_is_the_shared_chain(
        self, tmp_path: Path
    ) -> None:
        """A recorded absolute gain, so a bypassed or swapped chain fails.

        Measured 2026-11-03 with the fixture below: +2.135 dB, of which the
        declared 4.0 dB gain and the limiter's behaviour account for the rest.
        """
        params = dsp_models.PRESETS[dsp_models.PresetName.MODERATE]
        tone = _tone()
        source = _write_wav(tone, tmp_path / "source.wav")
        written = _write_wav(
            apply_enhancement_chain(tone.copy(), SR, params), tmp_path / "chain.wav"
        )

        for channel, (start, end) in enumerate(
            zip(_decode_rms_db(source), _decode_rms_db(written), strict=True)
        ):
            assert end - start == pytest.approx(2.135, abs=0.3), f"channel {channel}"
