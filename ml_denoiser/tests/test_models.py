"""Tests for ``ml_denoiser.core.models``.

The parameters are the only thing a run reads, so their validation is the one
place a bad value can be refused *before* a batch starts.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from ml_denoiser.core.models import (
    DEFAULT_AMOUNT,
    MIN_CHANGE_DB,
    DenoiseParams,
    DenoiseResult,
)


class TestDenoiseParams:
    """Validation refuses what a run could not honour."""

    def test_defaults_are_a_full_denoise_in_live_mode(self) -> None:
        params = DenoiseParams()

        assert params.amount == DEFAULT_AMOUNT == 1.0
        assert params.dry_run is False
        assert params.validate() == []

    def test_a_zero_amount_is_refused(self) -> None:
        problems = DenoiseParams(amount=0.0).validate()

        assert problems
        assert "above 0%" in problems[0]

    def test_an_over_full_amount_is_refused(self) -> None:
        problems = DenoiseParams(amount=1.5).validate()

        assert problems
        assert "at most 100%" in problems[0]

    def test_a_negative_amount_is_refused(self) -> None:
        assert DenoiseParams(amount=-0.5).validate()

    @pytest.mark.parametrize("amount", [0.01, 0.5, 0.99, 1.0])
    def test_in_range_amounts_are_accepted(self, amount: float) -> None:
        assert DenoiseParams(amount=amount).validate() == []


class TestDenoiseResult:
    """The measured attenuation is derived, never stored twice."""

    def _segment(self) -> AudioSegment:
        return Sine(440).to_audio_segment(duration=100)

    def test_attenuation_is_the_level_drop(self) -> None:
        result = DenoiseResult(
            audio=self._segment(),
            rms_before_db=-18.0,
            rms_after_db=-24.0,
            was_modified=True,
        )

        assert result.attenuation_db() == pytest.approx(6.0)

    def test_attenuation_never_goes_negative(self) -> None:
        """A model that made the file louder is reported as no attenuation."""
        result = DenoiseResult(
            audio=self._segment(),
            rms_before_db=-24.0,
            rms_after_db=-18.0,
            was_modified=False,
        )

        assert result.attenuation_db() == 0.0

    def test_min_change_threshold_is_audible_not_measurable_noise(self) -> None:
        assert 0.0 < MIN_CHANGE_DB < 1.0
