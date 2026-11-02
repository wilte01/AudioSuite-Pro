"""
tests/test_silence_trimmer.py
Pytest suite for the Silence Trimmer's trimming core.

Covers trimmer.py: the TrimResult frozen dataclass and trim_and_fade()
correctness, including the all-silent skip and the non-silent control.

Changed in 1.0.1: adds the all-silent skip regression and a non-silent control.

Changed in 1.1.0: exempted read-only formats from the export-mapping check and
added a behavioural skip test.

Changed in 2.6.0 (U-04): the standalone window, its batch processor and its CLI
are gone - REFINE's Trim stage runs this core - so the tests that drove
``process_single_file``, ``run_trimming`` and the CLI parser went with them.

Changed in 2.3.1: drops the orphaned ``_make_slot_deps`` helper that
removal left behind, so the module no longer names names it cannot import.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pydub import AudioSegment

from silence_trimmer.core.trimmer import TrimResult, trim_and_fade  # noqa: E402

# ───────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────


def _make_audio(duration_ms: int = 2000, silence_ms: int = 300) -> "AudioSegment":
    """Return an AudioSegment with silence_ms of leading/trailing silence
    around duration_ms of audible tone.

    The body must be audible: an all-silent fixture would exercise the
    wholly-silent SKIP path (H2) rather than trimming, so "silence at the
    ends" tests built on it would silently assert the wrong outcome.
    """
    from pydub import AudioSegment
    from pydub.generators import Sine

    silence_seg = AudioSegment.silent(duration=silence_ms)
    tone = Sine(440).to_audio_segment(duration=duration_ms)
    return silence_seg + tone + silence_seg


def _make_pure_silent(duration_ms: int = 1000) -> "AudioSegment":
    from pydub import AudioSegment

    return AudioSegment.silent(duration=duration_ms)


# ─────────────────────────────────────────────────────────────────────────────
# TrimResult — frozen dataclass
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimResult:
    def test_frozen_prevents_mutation(self) -> None:
        """TrimResult must be immutable per claude.md frozen dataclass mandate."""
        r = TrimResult(
            start_trim_ms=0,
            end_trim_ms=0,
            total_trim_ms=0,
            has_silence=False,
            trimmed=None,
            status="SKIP",
            action="No silence detected",
        )
        with pytest.raises((FrozenInstanceError, AttributeError)):
            r.status = "MUTATED"  # type: ignore[misc]

    def test_field_types_preserved(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="ok",
        )
        assert r.start_trim_ms == 100
        assert r.end_trim_ms == 200
        assert r.total_trim_ms == 300
        assert r.has_silence is True
        assert r.status == "TRIMMED"

    def test_skip_action_string(self) -> None:
        r = TrimResult(
            start_trim_ms=0,
            end_trim_ms=0,
            total_trim_ms=0,
            has_silence=False,
            trimmed=None,
            status="SKIP",
            action="No silence detected",
        )
        assert r.action == "No silence detected"

    def test_trimmed_action_with_fades(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="-100ms / -200ms + Fades",
        )
        assert "+ Fades" in r.action

    def test_trimmed_action_without_fades(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="TRIMMED",
            action="-100ms / -200ms",
        )
        assert "+ Fades" not in r.action

    def test_dry_run_action_string(self) -> None:
        r = TrimResult(
            start_trim_ms=100,
            end_trim_ms=200,
            total_trim_ms=300,
            has_silence=True,
            trimmed=None,
            status="DRY_RUN",
            action="Would trim 300ms",
        )
        assert "Would trim" in r.action


# ─────────────────────────────────────────────────────────────────────────────
# trim_and_fade — digital silence (no silence to detect)
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimAndFadeNoSilence:
    """Audio that has no detectable silence should be skipped."""

    def test_skip_status_when_no_silence(self) -> None:
        # 500 Hz sine approximation: use a non-silent segment
        # full silence returns full length — so force a "loud" segment
        import array

        from pydub import AudioSegment

        samples = array.array("h", [32000] * 8000)
        loud = AudioSegment(
            samples.tobytes(), frame_rate=8000, sample_width=2, channels=1
        )
        result = trim_and_fade(loud, threshold=-50, is_dry_run=False)
        assert result.status == "SKIP"
        assert result.has_silence is False
        assert result.trimmed is None
        assert result.total_trim_ms == 0

    def test_skip_returns_zero_trim_amounts(self) -> None:
        import array

        samples = array.array("h", [32000] * 8000)
        from pydub import AudioSegment

        loud = AudioSegment(
            samples.tobytes(), frame_rate=8000, sample_width=2, channels=1
        )
        result = trim_and_fade(loud, threshold=-50, is_dry_run=False)
        assert result.start_trim_ms == 0
        assert result.end_trim_ms == 0


# ─────────────────────────────────────────────────────────────────────────────
# trim_and_fade — silence detection
# ─────────────────────────────────────────────────────────────────────────────


class TestTrimAndFadeWithSilence:
    def test_dry_run_does_not_produce_trimmed_audio(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        if result.has_silence:
            assert result.trimmed is None
            assert result.status == "DRY_RUN"
            assert "Would trim" in result.action

    def test_live_run_produces_trimmed_audio(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=False)
        if result.has_silence:
            assert result.trimmed is not None
            assert result.status == "TRIMMED"
            assert len(result.trimmed) < len(audio)

    def test_fade_applied_when_requested(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        if result.has_silence:
            assert result.trimmed is not None
            assert "+ Fades" in result.action

    def test_apply_fade_field_is_true_when_requested(self) -> None:
        """`apply_fade` is the structured counterpart of the "+ Fades"
        action text, so consumers need not substring-match `action`.
        """
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.apply_fade is True

    def test_apply_fade_field_is_false_when_not_requested(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=False, apply_fade=False)
        assert result.apply_fade is False

    def test_apply_fade_defaults_false_for_skipped_results(self) -> None:
        """The skip and dry-run paths leave apply_fade at its False default."""
        import array

        from pydub import AudioSegment

        loud = AudioSegment(
            array.array("h", [32000] * 8000).tobytes(),
            frame_rate=8000,
            sample_width=2,
            channels=1,
        )
        skipped = trim_and_fade(loud, threshold=-60, is_dry_run=False)
        assert skipped.status == "SKIP"
        assert skipped.apply_fade is False

        audio = _make_audio(duration_ms=500, silence_ms=200)
        dry = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        assert dry.status == "DRY_RUN"
        assert dry.apply_fade is False

    def test_fade_not_applied_in_dry_run(self) -> None:
        audio = _make_audio(duration_ms=1000, silence_ms=300)
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=True,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.trimmed is None

    def test_total_trim_equals_start_plus_end(self) -> None:
        audio = _make_audio(duration_ms=500, silence_ms=200)
        result = trim_and_fade(audio, threshold=-60, is_dry_run=True)
        assert result.total_trim_ms == result.start_trim_ms + result.end_trim_ms

    def test_pure_silence_produces_trim_covering_full_length(self) -> None:
        """All-silent audio: trim amounts sum to (at least) full duration."""
        audio = _make_pure_silent(duration_ms=500)
        result = trim_and_fade(audio, threshold=-10, is_dry_run=True)
        assert result.has_silence is True
        assert result.total_trim_ms > 0

    def test_fade_durations_longer_than_trimmed_segment_are_clamped(self) -> None:
        """Regression test: fade_in_ms/fade_out_ms exceeding the trimmed
        segment's length must be clamped to that length, not passed through
        to pydub as-is.

        pydub's AudioSegment.fade() does not clip an over-long fade — it
        computes a negative internal start offset instead, which silently
        lengthens and corrupts the output. Before the fix, applying the
        default 500ms/1000ms fades to an audio file with under ~1.5s of
        real content after trimming (e.g. short samples, podcast clips)
        would expand the exported file well beyond its correct length.
        """
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence_pad = AudioSegment.silent(duration=800)
        tone = Sine(440).to_audio_segment(duration=300)
        audio = silence_pad + tone + silence_pad

        result = trim_and_fade(
            audio,
            threshold=-50,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=500,
            fade_out_ms=1000,
        )

        assert result.status == "TRIMMED"
        assert result.trimmed is not None
        expected_len = len(audio) - result.start_trim_ms - result.end_trim_ms
        # Allow normal pydub ms-rounding slack, but the output must NOT be
        # inflated by hundreds of ms the way the unclamped bug produced.
        assert abs(len(result.trimmed) - expected_len) <= 5

    def test_fade_clamp_does_not_affect_fades_already_within_segment_length(
        self,
    ) -> None:
        """Clamping must be a no-op when the fade duration already fits —
        normal-length tracks must fade exactly as before."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence_pad = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=2000)
        audio = silence_pad + tone + silence_pad

        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        assert result.has_silence is True
        expected_len = len(audio) - result.start_trim_ms - result.end_trim_ms
        assert abs(len(result.trimmed) - expected_len) <= 5

    def test_fully_silent_audio_is_skipped_not_emptied(self) -> None:
        """H2: a wholly silent source must not yield an empty trimmed segment
        that callers would export over the original. It returns trimmed=None
        with a non-destructive SKIP status, even when fades are requested."""
        audio = _make_pure_silent(duration_ms=500)
        result = trim_and_fade(
            audio,
            threshold=-10,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=500,
            fade_out_ms=1000,
        )
        assert result.status == "SKIP"
        assert result.trimmed is None
        assert result.has_silence is True
        assert "silence" in result.action.lower()

    def test_fully_silent_audio_is_skipped_in_dry_run_too(self) -> None:
        """The wholly-silent source is non-destructive in dry-run as well, so
        the reported action stays truthful instead of promising a trim that
        would delete the whole file."""
        audio = _make_pure_silent(duration_ms=500)
        result = trim_and_fade(audio, threshold=-10, is_dry_run=True, apply_fade=True)
        assert result.status == "SKIP"
        assert result.trimmed is None
        assert result.has_silence is True

    def test_no_fade_action_does_not_contain_fades_string(self) -> None:
        """When apply_fade=False, action must not mention fades."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=500)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=False,
        )
        if result.has_silence:
            assert result.status == "TRIMMED"
            assert "+ Fades" not in result.action
            assert result.action.startswith("-")

    def test_trimmed_length_correct_without_fades(self) -> None:
        """Without fades, trimmed segment length must equal original minus
        detected trim amounts (within pydub ms-rounding slack)."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=1000)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=False,
        )
        if result.has_silence:
            expected = len(audio) - result.start_trim_ms - result.end_trim_ms
            assert abs(len(result.trimmed) - expected) <= 5

    def test_trimmed_length_correct_with_fades_within_bounds(self) -> None:
        """With fades that fit inside the trimmed segment, the total length
        must still match original minus trim amounts."""
        from pydub import AudioSegment
        from pydub.generators import Sine

        silence = AudioSegment.silent(duration=300)
        tone = Sine(440).to_audio_segment(duration=2000)
        audio = silence + tone + silence
        result = trim_and_fade(
            audio,
            threshold=-60,
            is_dry_run=False,
            apply_fade=True,
            fade_in_ms=100,
            fade_out_ms=100,
        )
        if result.has_silence:
            expected = len(audio) - result.start_trim_ms - result.end_trim_ms
            assert abs(len(result.trimmed) - expected) <= 5


# ─────────────────────────────────────────────────────────────────────────────
# get_export_args (shared)
# ─────────────────────────────────────────────────────────────────────────────
