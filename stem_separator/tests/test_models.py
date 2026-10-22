"""Tests for ``stem_separator.core.models``.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import numpy as np
import pytest

from stem_separator.core.models import (
    DEFAULT_MODEL,
    MIX_FILENAME,
    MODEL_SAMPLE_RATE,
    STEM_NAMES,
    SeparatedTrack,
    StemSeparationParams,
    normalise_stems,
)


class TestNormaliseStems:
    """The selection is validated once, in canonical order."""

    def test_none_means_every_stem(self) -> None:
        assert normalise_stems(None) == STEM_NAMES
        assert normalise_stems(()) == STEM_NAMES

    def test_requested_stems_come_back_in_model_order(self) -> None:
        assert normalise_stems(("bass", "vocals")) == ("vocals", "bass")

    def test_duplicates_collapse(self) -> None:
        assert normalise_stems(("drums", "drums")) == ("drums",)

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError) as caught:
            normalise_stems(("piano",))
        assert "piano" in str(caught.value)


class TestStemSeparationParams:
    """A run's parameters describe themselves and reject what cannot work."""

    def test_defaults_are_a_complete_live_run_shape(self) -> None:
        params = StemSeparationParams(output_dir="out")

        assert params.model == DEFAULT_MODEL
        assert params.resolved_stems() == STEM_NAMES
        assert params.validate() == []

    def test_missing_output_directory_is_a_problem(self) -> None:
        problems = StemSeparationParams(output_dir="  ").validate()

        assert problems
        assert "output directory" in problems[0].lower()

    def test_unknown_model_is_a_problem(self) -> None:
        problems = StemSeparationParams(output_dir="out", model="nope").validate()

        assert any("model" in problem for problem in problems)

    def test_no_selected_stem_is_a_problem(self) -> None:
        params = StemSeparationParams(output_dir="out", stems=("piano",))

        assert params.validate()


class TestSeparatedTrack:
    """The result knows how long the stems it carries are."""

    def test_duration_comes_from_the_longest_stem(self) -> None:
        track = SeparatedTrack(
            sample_rate=MODEL_SAMPLE_RATE,
            stems={
                "vocals": np.zeros((2, MODEL_SAMPLE_RATE), dtype=np.float32),
                "drums": np.zeros((2, MODEL_SAMPLE_RATE // 2), dtype=np.float32),
            },
        )

        assert track.duration_seconds() == pytest.approx(1.0)

    def test_empty_result_has_no_duration(self) -> None:
        assert (
            SeparatedTrack(sample_rate=MODEL_SAMPLE_RATE, stems={}).duration_seconds()
            == 0.0
        )

    def test_mix_filename_is_wav(self) -> None:
        assert MIX_FILENAME.endswith(".wav")
