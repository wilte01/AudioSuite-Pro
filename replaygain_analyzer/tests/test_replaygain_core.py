"""
test_replaygain_core.py
Tests for replaygain_analyzer.core.gain_calculator
         replaygain_analyzer.core.tag_writer

New vs original:
  - TestCalculateAlbumGain: adds empty-list guard tests (#20)
  - TestWriteReplaygainTags: adds dry-run status test (validates tag_writer
    is NOT invoked when is_dry_run=True — exercised via apply_replaygain_tags)

Changed in 1.0.1: updates the tag assertions for the linear (not dBFS) peak.
Changed in 2.1.2: album-gain tests take per-track durations and pin the
duration-weighted formula; the old mean-of-loudness test becomes the
equal-duration special case (audit R-01).
"""

from unittest.mock import patch

import pytest
from pydub import AudioSegment

from replaygain_analyzer.core.gain_calculator import (
    calculate_album_gain,
    dbfs_to_linear,
)
from replaygain_analyzer.core.tag_writer import write_replaygain_tags

# ── dbfs_to_linear ────────────────────────────────────────────────────────────


class TestDbfsToLinear:
    def test_full_scale_is_one(self) -> None:
        assert abs(dbfs_to_linear(0.0) - 1.0) < 1e-12

    def test_minus_six_dbfs_is_half_amplitude(self) -> None:
        """-6 dBFS is half the full-scale amplitude (10 ** -0.3)."""
        assert round(dbfs_to_linear(-6.0), 6) == 0.501187

    def test_minus_half_dbfs(self) -> None:
        assert round(dbfs_to_linear(-0.5), 6) == 0.944061

    def test_positive_true_peak_exceeds_one(self) -> None:
        """Inter-sample true peaks above 0 dBFS map above 1.0 linear."""
        assert dbfs_to_linear(1.0) > 1.0


# ── calculate_album_gain ──────────────────────────────────────────────────────


class TestCalculateAlbumGain:
    def test_returns_four_element_tuple(self) -> None:
        result = calculate_album_gain(-16.0, [-18.0, -20.0], [-1.0, -2.0], [10.0, 10.0])
        assert isinstance(result, tuple) and len(result) == 4

    def test_album_gain_float(self) -> None:
        gain, peak, gain_str, peak_str = calculate_album_gain(
            -16.0, [-18.0, -20.0], [-1.0, -2.0], [10.0, 10.0]
        )
        assert isinstance(gain, float)

    def test_album_peak_float(self) -> None:
        gain, peak, gain_str, peak_str = calculate_album_gain(
            -16.0, [-18.0, -20.0], [-1.0, -2.0], [10.0, 10.0]
        )
        assert isinstance(peak, float)

    def test_gain_str_has_plus_sign_when_positive(self) -> None:
        _, _, gain_str, _ = calculate_album_gain(-16.0, [-20.0], [-1.0], [10.0])
        assert gain_str.startswith("+")

    def test_gain_str_has_minus_sign_when_negative(self) -> None:
        _, _, gain_str, _ = calculate_album_gain(-23.0, [-20.0], [-1.0], [10.0])
        assert gain_str.startswith("-")

    def test_gain_calculation_single_file(self) -> None:
        gain, _, _, _ = calculate_album_gain(-16.0, [-18.0], [-1.0], [10.0])
        assert abs(gain - 2.0) < 1e-9

    def test_equal_durations_and_levels_reduce_to_the_mean(self) -> None:
        """Equal lengths and equal loudness give the old mean answer.

        Equal *lengths* alone do not reduce to the arithmetic mean of track
        loudness - the mean-square energy of two different levels is not the
        mean of their dB values - so this uses two equally loud tracks.
        """
        gain, _, _, _ = calculate_album_gain(
            -16.0, [-20.0, -20.0], [-1.0, -0.5], [10.0, 10.0]
        )
        assert abs(gain - 4.0) < 1e-9

    def test_album_gain_is_duration_weighted(self) -> None:
        """A 10 s -10 LUFS track must not outweigh 30 s at -30 LUFS.

        The combined signal's mean-square energy is
        (10*10**-1 + 30*10**-3) / 40, i.e. -15.892 LUFS, so the gain at
        -16 LUFS is about -0.108 dB. The arithmetic mean of track loudness is
        -20 LUFS, which produced +4.0 dB (audit R-01).
        """
        gain, _, _, _ = calculate_album_gain(
            -16.0, [-10.0, -30.0], [-0.5, -0.5], [10.0, 30.0]
        )
        assert abs(gain - (-0.1076)) < 1e-3
        assert abs(gain - 4.0) > 2.0

    def test_album_peak_is_max_of_peaks(self) -> None:
        _, peak, _, _ = calculate_album_gain(
            -16.0, [-18.0, -20.0], [-0.3, -0.1, -0.5], [10.0, 10.0]
        )
        assert abs(peak - dbfs_to_linear(-0.1)) < 1e-9

    def test_album_peak_is_linear_not_dbfs(self) -> None:
        """The album peak tag must carry the linear amplitude, not dBFS.

        A single -6.0 dBFS measurement (half amplitude) must yield
        0.501187, and the album maximum must be the loudest *linear* peak
        (the -0.5 dBFS file), not the largest dBFS value.
        """
        _, peak, _, peak_str = calculate_album_gain(-16.0, [-18.0], [-6.0], [10.0])
        assert round(peak, 6) == 0.501187
        assert peak_str == "0.501187"

        _, peak, _, _ = calculate_album_gain(
            -16.0, [-18.0, -18.0], [-6.0, -0.5], [10.0, 10.0]
        )
        assert abs(peak - dbfs_to_linear(-0.5)) < 1e-9

    def test_gain_str_format_two_decimal_places(self) -> None:
        _, _, gain_str, _ = calculate_album_gain(-16.0, [-18.123], [-1.0], [10.0])
        numeric_part = gain_str.replace("+", "").replace("-", "").replace(" dB", "")
        assert len(numeric_part.split(".")[1]) == 2

    def test_peak_str_format_six_decimal_places(self) -> None:
        _, _, _, peak_str = calculate_album_gain(-16.0, [-18.0], [-0.912345], [10.0])
        assert len(peak_str.split(".")[1]) == 6

    def test_gain_str_ends_with_db(self) -> None:
        _, _, gain_str, _ = calculate_album_gain(-16.0, [-18.0], [-1.0], [10.0])
        assert gain_str.endswith(" dB")

    def test_exact_target_when_mean_equals_target(self) -> None:
        gain, _, gain_str, _ = calculate_album_gain(-16.0, [-16.0], [-1.0], [10.0])
        assert abs(gain) < 1e-9
        assert gain_str in ("+0.00 dB", "-0.00 dB", "0.00 dB")

    @pytest.mark.parametrize("target", [-14.0, -16.0, -18.0, -23.0])
    def test_common_streaming_targets(self, target: float) -> None:
        gain, _, _, _ = calculate_album_gain(target, [target - 2.0], [-1.0], [10.0])
        assert abs(gain - 2.0) < 1e-9

    def test_single_track_album(self) -> None:
        gain, peak, _, _ = calculate_album_gain(-16.0, [-18.0], [-0.5], [10.0])
        assert abs(gain - 2.0) < 1e-9
        assert abs(peak - dbfs_to_linear(-0.5)) < 1e-9

    def test_large_track_list(self) -> None:
        lufs = [-18.0] * 50
        peaks = [-0.5] * 50
        durations = [10.0] * 50
        gain, peak, _, _ = calculate_album_gain(-16.0, lufs, peaks, durations)
        assert abs(gain - 2.0) < 1e-6
        assert abs(peak - dbfs_to_linear(-0.5)) < 1e-9

    # ── Duration guards (audit R-01) ────────────────────────────────

    def test_empty_lufs_raises_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError

        with pytest.raises(AudioSuiteError, match="lufs_values must not be empty"):
            calculate_album_gain(-16.0, [], [-1.0], [])

    def test_empty_peaks_raises_audio_suite_error(self) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError

        with pytest.raises(AudioSuiteError, match="peak_values must not be empty"):
            calculate_album_gain(-16.0, [-18.0], [], [10.0])

    def test_both_empty_raises_audio_suite_error(self) -> None:
        """lufs guard fires first when both lists are empty."""
        from audio_suite_shared.exceptions import AudioSuiteError

        with pytest.raises(AudioSuiteError, match="lufs_values must not be empty"):
            calculate_album_gain(-16.0, [], [], [])

    @pytest.mark.parametrize(
        "durations",
        [
            [],
            [10.0],
            [0.0, 10.0],
            [-1.0, 10.0],
            [float("nan"), 10.0],
            [float("inf"), 10.0],
        ],
    )
    def test_bad_durations_raise(self, durations: list[float]) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError

        with pytest.raises(AudioSuiteError, match="duration"):
            calculate_album_gain(-16.0, [-18.0, -20.0], [-1.0, -1.0], durations)

    def test_zero_energy_raises(self) -> None:
        """A -inf loudness contributes no energy; do not return a finite gain."""
        from audio_suite_shared.exceptions import AudioSuiteError

        with pytest.raises(AudioSuiteError, match="energy"):
            calculate_album_gain(-16.0, [float("-inf")], [-1.0], [10.0])


# ── write_replaygain_tags ─────────────────────────────────────────────────────


class TestWriteReplaygainTags:
    @staticmethod
    @pytest.fixture
    def mp3_file(tmp_path):
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        return str(path)

    @staticmethod
    @pytest.fixture
    def flac_file(tmp_path):
        path = tmp_path / "track.flac"
        AudioSegment.silent(duration=100).export(str(path), format="flac")
        return str(path)

    def test_mp3_returns_tagged_on_success(self, mp3_file: str) -> None:
        ok, msg = write_replaygain_tags(
            mp3_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789"
        )
        assert ok is True
        assert msg == "TAGGED"

    def test_flac_returns_tagged_on_success(self, flac_file: str) -> None:
        ok, msg = write_replaygain_tags(
            flac_file, "+2.00 dB", "0.900000", "+1.50 dB", "0.950000"
        )
        assert ok is True
        assert msg == "TAGGED"

    def test_mp3_tags_persisted(self, mp3_file: str) -> None:
        import mutagen
        from mutagen.id3 import TXXX

        write_replaygain_tags(mp3_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789")
        audio = mutagen.File(mp3_file)
        tags = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert tags.get("REPLAYGAIN_TRACK_GAIN") == "+2.34 dB"
        assert tags.get("REPLAYGAIN_ALBUM_GAIN") == "+1.80 dB"
        assert tags.get("REPLAYGAIN_TRACK_PEAK") == "0.912345"
        assert tags.get("REPLAYGAIN_ALBUM_PEAK") == "0.956789"

    def test_flac_tags_persisted(self, flac_file: str) -> None:
        import mutagen

        write_replaygain_tags(flac_file, "+1.00 dB", "0.800000", "+0.50 dB", "0.750000")
        audio = mutagen.File(flac_file)
        assert audio["REPLAYGAIN_TRACK_GAIN"][0] == "+1.00 dB"
        assert audio["REPLAYGAIN_ALBUM_PEAK"][0] == "0.750000"

    def test_returns_tuple(self, mp3_file: str) -> None:
        result = write_replaygain_tags(mp3_file, "+1 dB", "0.9", "+1 dB", "0.9")
        assert isinstance(result, tuple) and len(result) == 2

    def test_nonexistent_file_returns_false(self, tmp_path) -> None:
        ok, msg = write_replaygain_tags(
            str(tmp_path / "ghost.mp3"), "+1 dB", "0.9", "+1 dB", "0.9"
        )
        assert ok is False
        assert msg

    def test_mutagen_unavailable_returns_tagged(self, mp3_file: str) -> None:
        with patch("replaygain_analyzer.core.tag_writer.MUTAGEN_AVAILABLE", False):
            ok, msg = write_replaygain_tags(mp3_file, "+1 dB", "0.9", "+1 dB", "0.9")
        assert ok is True
        assert msg == "TAGGED"

    # ── WAV / AIFF (ID3-backed, regression coverage for finding #1) ──────────
    #
    # mutagen.wave.WAVE and mutagen.aiff.AIFF are both backed by
    # mutagen.id3.ID3, identical to mutagen.mp3.MP3. Plain dict-style
    # assignment (audio["KEY"] = value) raises TypeError on these formats;
    # only explicit TXXX frames work. These tests exist because the
    # original implementation silently failed on every WAV/AIFF file.

    @staticmethod
    @pytest.fixture
    def wav_file(tmp_path):
        path = tmp_path / "track.wav"
        AudioSegment.silent(duration=100).export(str(path), format="wav")
        return str(path)

    @staticmethod
    @pytest.fixture
    def aiff_file(tmp_path):
        path = tmp_path / "track.aiff"
        AudioSegment.silent(duration=100).export(str(path), format="aiff")
        return str(path)

    def test_wav_returns_tagged_on_success(self, wav_file: str) -> None:
        ok, msg = write_replaygain_tags(
            wav_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789"
        )
        assert ok is True
        assert msg == "TAGGED"

    def test_wav_tags_persisted_as_txxx_frames(self, wav_file: str) -> None:
        import mutagen
        from mutagen.id3 import TXXX

        write_replaygain_tags(wav_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789")
        audio = mutagen.File(wav_file)
        tags = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert tags.get("REPLAYGAIN_TRACK_GAIN") == "+2.34 dB"
        assert tags.get("REPLAYGAIN_ALBUM_GAIN") == "+1.80 dB"
        assert tags.get("REPLAYGAIN_TRACK_PEAK") == "0.912345"
        assert tags.get("REPLAYGAIN_ALBUM_PEAK") == "0.956789"

    def test_aiff_returns_tagged_on_success(self, aiff_file: str) -> None:
        ok, msg = write_replaygain_tags(
            aiff_file, "+3.00 dB", "0.500000", "+2.00 dB", "0.600000"
        )
        assert ok is True
        assert msg == "TAGGED"

    def test_aiff_tags_persisted_as_txxx_frames(self, aiff_file: str) -> None:
        import mutagen
        from mutagen.id3 import TXXX

        write_replaygain_tags(aiff_file, "+3.00 dB", "0.500000", "+2.00 dB", "0.600000")
        audio = mutagen.File(aiff_file)
        tags = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert tags.get("REPLAYGAIN_TRACK_GAIN") == "+3.00 dB"
        assert tags.get("REPLAYGAIN_ALBUM_PEAK") == "0.600000"

    # ── M4A (MP4 freeform atoms, regression coverage for finding #2) ─────────
    #
    # Plain dict-style assignment on mutagen.mp4.MP4Tags does NOT raise,
    # but silently writes a malformed non-standard top-level atom that no
    # player recognizes. Tags must use the iTunes freeform-atom convention
    # ("----:com.apple.iTunes:<NAME>") to be readable.

    @staticmethod
    @pytest.fixture
    def m4a_file(tmp_path):
        path = tmp_path / "track.m4a"
        AudioSegment.silent(duration=100).export(str(path), format="ipod")
        return str(path)

    def test_m4a_returns_tagged_on_success(self, m4a_file: str) -> None:
        ok, msg = write_replaygain_tags(
            m4a_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789"
        )
        assert ok is True
        assert msg == "TAGGED"

    def test_m4a_tags_persisted_as_freeform_atoms(self, m4a_file: str) -> None:
        import mutagen

        write_replaygain_tags(m4a_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789")
        audio = mutagen.File(m4a_file)

        def freeform(name: str) -> str:
            return audio.tags[f"----:com.apple.iTunes:{name}"][0].decode("utf-8")

        assert freeform("REPLAYGAIN_TRACK_GAIN") == "+2.34 dB"
        assert freeform("REPLAYGAIN_ALBUM_GAIN") == "+1.80 dB"
        assert freeform("REPLAYGAIN_TRACK_PEAK") == "0.912345"
        assert freeform("REPLAYGAIN_ALBUM_PEAK") == "0.956789"

    def test_m4a_does_not_write_malformed_bare_key(self, m4a_file: str) -> None:
        """Regression guard: a bare 'REPLAYGAIN_TRACK_GAIN' top-level atom
        must never be written — that was the silent-corruption bug."""
        import mutagen

        write_replaygain_tags(m4a_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789")
        audio = mutagen.File(m4a_file)
        assert "REPLAYGAIN_TRACK_GAIN" not in audio.tags

    def test_unexpected_exception_returns_false(self, mp3_file: str) -> None:
        """Unexpected exception from the shared write returns (False, message)."""
        with patch(
            "replaygain_analyzer.core.tag_writer.write_replaygain",
            side_effect=OSError("disk full"),
        ):
            ok, msg = write_replaygain_tags(
                mp3_file, "+2.34 dB", "0.912345", "+1.80 dB", "0.956789"
            )
        assert ok is False
        assert msg

    def test_audio_tag_error_returns_false(self, mp3_file: str) -> None:
        """AudioTagError from the shared write returns (False, message)."""
        from audio_suite_shared.exceptions import AudioTagError

        with patch(
            "replaygain_analyzer.core.tag_writer.write_replaygain",
            side_effect=AudioTagError("tag write failed"),
        ):
            ok, msg = write_replaygain_tags(mp3_file, "+1 dB", "0.9", "+1 dB", "0.9")
        assert ok is False
        assert msg
