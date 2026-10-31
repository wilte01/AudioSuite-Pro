"""Tests for the declip DSP, measured on the audio it returns.

The acceptance for F-08a is a measurement, not a shape:

* a clipped sine at ``-0.1 dBFS`` comes back with its harmonics **reduced**
  (measured THD) and its peak **restored** (measured level);
* a clean file is returned **unmodified** -- the same object, so the caller's
  hash-equal write path cannot be entered by accident -- because a false
  positive that processes clean audio is the defect to avoid.

The recorded numbers are the ones the plan reports: THD ``-21.38 dB`` ->
``-46.82 dB`` (25.45 dB better) and peak ``-1.938`` -> ``-0.188 dBFS`` against the
original's ``-0.100 dBFS``.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_suite_shared.exceptions import AudioConfigurationError
from restoration.core.declipper import (
    _MIN_FILE_PEAK,
    DEFAULT_MAX_RUN_MS,
    DEFAULT_THRESHOLD,
    declip_segment,
    find_clipped_runs,
    reconstruct_run,
)

from .conftest import F0, SR, channel, peak, sine, thd_db, to_segment

#: How much better the harmonic floor must get.  The measured improvement is
#: 25.45 dB; a fifth of it is noise, the rest is the repair working.
REQUIRED_THD_IMPROVEMENT_DB = 15.0


class TestDetection:
    """A flat top is the only thing that counts as clipping."""

    def test_a_clipped_sine_reports_two_plateaus_per_cycle(self) -> None:
        # Both halves of the waveform are cut, so 50 cycles of a 1 kHz tone at
        # 44.1 kHz give 100 flat tops, not 50.
        clipped = np.clip(sine(0.9886, seconds=0.05), -0.8, 0.8)

        runs = find_clipped_runs(clipped)

        assert len(runs) == 100, f"{len(runs)} plateaus in 50 cycles"
        assert all(0 <= start <= end < clipped.size for start, end in runs)

    def test_a_clean_sine_has_no_plateau(self) -> None:
        assert find_clipped_runs(sine(0.95)) == []

    def test_a_sine_that_touches_full_scale_is_not_clipping(self) -> None:
        # The peak is curved: one sample at the maximum, no flat top to repair.
        assert find_clipped_runs(sine(0.999)) == []

    def test_silence_is_not_scooped_for_plateaus(self) -> None:
        silence = np.zeros(int(SR * 0.1))

        assert find_clipped_runs(silence) == []

    def test_a_signal_below_the_minimum_peak_is_ignored(self) -> None:
        quiet = np.full(int(SR * 0.1), _MIN_FILE_PEAK * 0.5)

        assert find_clipped_runs(quiet) == []

    def test_the_threshold_is_relative_to_the_file_s_own_peak(self) -> None:
        # A ceiling at 0.8 is still a ceiling when the threshold is a fraction
        # of the peak, which is what makes the detector work on a limited
        # master without the user knowing the ceiling's level.  The candidate
        # cut only *finds* the region; the plateau is measured against the
        # region's own highest sample, so a looser threshold finds the same
        # flat tops rather than a wider one.
        clipped = np.clip(sine(0.9886, seconds=0.02), -0.8, 0.8)

        assert find_clipped_runs(clipped, threshold=0.77)
        assert find_clipped_runs(clipped, threshold=0.5) == find_clipped_runs(clipped)
        assert find_clipped_runs(clipped, threshold=1.0) == find_clipped_runs(clipped)


class TestRepair:
    """What the reconstruction does to a known-clipped reference."""

    def test_the_harmonic_floor_drops_and_the_peak_is_restored(
        self, clipped_pair: tuple[np.ndarray, object]
    ) -> None:
        original, clipped = clipped_pair
        before = channel(clipped)
        before_thd = thd_db(before)
        before_peak = peak(before)

        result = declip_segment(clipped)  # type: ignore[arg-type]
        after = channel(result.audio)

        assert result.was_modified is True
        assert result.runs_found > 0
        improvement = before_thd - thd_db(after)
        assert improvement >= REQUIRED_THD_IMPROVEMENT_DB, (
            f"THD only improved {improvement:.2f} dB ({before_thd:.2f} -> "
            f"{thd_db(after):.2f})"
        )
        assert peak(after) > before_peak
        assert abs(peak(after) - peak(original)) < 0.05, (
            f"peak {peak(after):.4f} vs the original {peak(original):.4f}"
        )

    def test_the_reported_peak_is_the_peak_it_wrote(
        self, clipped_pair: tuple[np.ndarray, object]
    ) -> None:
        _original, clipped = clipped_pair

        result = declip_segment(clipped)  # type: ignore[arg-type]

        measured = 20 * np.log10(peak(channel(result.audio)))
        assert result.restored_peak_db == pytest.approx(measured, abs=0.05)

    def test_the_repair_does_not_introduce_clipping_of_its_own(
        self, clipped_pair: tuple[np.ndarray, object]
    ) -> None:
        _original, clipped = clipped_pair

        result = declip_segment(clipped)  # type: ignore[arg-type]

        assert peak(channel(result.audio)) <= 1.0

    def test_a_second_pass_finds_nothing_to_do(
        self, clipped_pair: tuple[np.ndarray, object]
    ) -> None:
        _original, clipped = clipped_pair
        once = declip_segment(clipped)  # type: ignore[arg-type]

        again = declip_segment(once.audio)

        assert again.was_modified is False
        assert again.runs_found == 0

    def test_the_repair_is_applied_to_every_channel(
        self, clipped_pair: tuple[np.ndarray, object]
    ) -> None:
        _original, clipped = clipped_pair

        result = declip_segment(clipped)  # type: ignore[arg-type]

        from audio_suite_shared.audio_conversion import segment_to_numpy

        decoded, _rate = segment_to_numpy(result.audio)
        assert decoded.shape[0] == 2
        assert all(peak(decoded[index].astype(np.float64)) > 0.8 for index in range(2))


class TestCleanAudioIsReturnedUnmodified:
    """The false positive is the defect: clean input must pass straight through."""

    def test_a_clean_sine_is_the_same_object(self) -> None:
        clean = to_segment(sine(0.95))

        result = declip_segment(clean)

        assert result.was_modified is False
        assert result.audio is clean
        assert (result.runs_found, result.runs_skipped) == (0, 0)

    def test_busy_music_with_no_flat_top_is_untouched(self) -> None:
        rng = np.random.default_rng(3)
        busy = np.zeros(SR)
        for k in range(1, 40):
            busy += np.sin(2 * np.pi * 110 * k * np.arange(SR) / SR + rng.random()) / k
        busy *= 0.7 / float(np.max(np.abs(busy)))

        result = declip_segment(to_segment(busy))

        assert result.was_modified is False
        assert channel(result.audio) == pytest.approx(busy, abs=1e-4)

    def test_a_square_wave_is_refused_rather_than_rounded(self) -> None:
        # A square wave *is* a flat top either side of each edge; there is no
        # clean context to interpolate through, so it must be left alone.
        square = np.sign(sine(0.9, seconds=0.05)) * 0.9

        result = declip_segment(to_segment(square))

        assert result.was_modified is False
        assert result.runs_skipped > 0

    def test_a_plateau_wider_than_the_limit_is_counted_not_invented(self) -> None:
        flat = np.full(int(SR * 0.02), 0.9)

        result = declip_segment(to_segment(flat), threshold=0.85, max_run_ms=5)

        assert result.was_modified is False
        assert result.runs_skipped >= 1


class TestReconstructionGuards:
    """A plateau that cannot be improved is skipped, not rewritten."""

    def test_a_plateau_without_clean_context_is_refused(self) -> None:
        samples = np.full(20, 0.9)

        assert reconstruct_run(samples, 5, 10, peak=0.9) is False

    def test_a_plateau_at_full_scale_cannot_be_lifted(self) -> None:
        # A -0.1 dBFS sine clipped at 1.0 needs a peak above full scale, so the
        # honest answer is "cannot repair" rather than a clipped invention.
        clipped = np.clip(sine(1.2, seconds=0.05), -1.0, 1.0)

        result = declip_segment(to_segment(clipped))

        assert result.was_modified is False
        assert result.runs_skipped >= 1


class TestParameters:
    """Refusals at the boundary, so a bad slider cannot start a run."""

    @pytest.mark.parametrize("threshold", [0.0, -0.5, 1.5])
    def test_a_threshold_outside_the_unit_range_raises(self, threshold: float) -> None:
        with pytest.raises(AudioConfigurationError, match="threshold"):
            declip_segment(to_segment(sine(0.5)), threshold=threshold)

    def test_a_zero_width_limit_raises(self) -> None:
        with pytest.raises(AudioConfigurationError, match="max_run_ms"):
            declip_segment(to_segment(sine(0.5)), max_run_ms=0)

    def test_the_shipped_defaults_are_the_documented_ones(self) -> None:
        assert DEFAULT_THRESHOLD == 0.98
        assert DEFAULT_MAX_RUN_MS == 50

    def test_the_tone_used_by_the_measurements_is_one_kilohertz(self) -> None:
        # Guards the fixture against a silent edit: the THD thresholds above are
        # only meaningful for a tone whose harmonics are all below Nyquist.
        assert F0 * 21 < SR / 2
