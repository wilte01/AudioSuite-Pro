"""Exact time-range trim: range resolution, the slice, and the stream copy.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E3).

Every lock here reads what was produced rather than the setting that produced
it: the re-encode slice is compared sample-for-sample with the source at the
same offset, and a copy's length and content are measured from the written file,
because a copy lands on a frame boundary rather than on the millisecond asked
for.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from audio_refinery.core.models import (
    EXACT_TRIM_MODE,
    StageConfig,
    TrimParams,
)
from audio_refinery.core.trim import (
    COPY_EXTENSIONS,
    ExactRange,
    check_copy_extension,
    check_copy_mode,
    copy_trim,
    exact_preview_message,
    exact_trim_message,
    probe_duration_ms,
    resolve_range,
    slice_segment,
)
from audio_suite_shared.exceptions import AudioConfigValueError

FS = 44100


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _sine(duration_ms: int = 2000, amplitude: float = 0.5) -> AudioSegment:
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    pcm = (amplitude * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _silence(duration_ms: int = 1000) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms, frame_rate=FS).set_channels(1)


def _marked_audio() -> AudioSegment:
    """1 s silence, 1 s tone, 0.5 s silence - an unambiguous kept window."""
    return _silence(1000) + _sine(1000) + _silence(500)


def _rms_db(audio: AudioSegment) -> float:
    samples = np.array(audio.get_array_of_samples(), dtype=float)
    if audio.channels > 1:
        samples = samples.reshape(-1, audio.channels)
    rms = float(np.sqrt(np.mean(samples**2)))
    return 20.0 * float(np.log10(max(rms, 1e-9) / 32768.0))


def _fingerprint(path: Path) -> tuple[str, int]:
    stat = path.stat()
    return hashlib.sha256(path.read_bytes()).hexdigest(), stat.st_size


def _params(**overrides: object) -> TrimParams:
    params = TrimParams(mode=EXACT_TRIM_MODE)
    for key, value in overrides.items():
        setattr(params, key, value)
    return params


def _ffmpeg_available() -> bool:
    # Changed in 2.5.0: both binaries resolve through audio_suite_shared.ffmpeg.
    from audio_suite_shared.ffmpeg import FFMPEG_PATH, FFPROBE_PATH

    return Path(FFMPEG_PATH).is_file() and Path(FFPROBE_PATH).is_file()


requires_ffmpeg = pytest.mark.skipif(
    not _ffmpeg_available(), reason="FFmpeg/FFprobe are not available"
)


# ── Range resolution ────────────────────────────────────────────────────────


class TestResolveRange:
    def test_an_end_plus_the_default_start_is_the_range(self) -> None:
        resolved = resolve_range(_params(end_ms=1600), source_duration_ms=2000)

        assert resolved == ExactRange(start_ms=0, end_ms=1600, duration_ms=1600)

    def test_a_start_and_end_are_kept_as_given(self) -> None:
        resolved = resolve_range(
            _params(start_ms=400, end_ms=1600), source_duration_ms=2000
        )

        assert (resolved.start_ms, resolved.end_ms, resolved.duration_ms) == (
            400,
            1600,
            1200,
        )

    def test_a_duration_replaces_the_end(self) -> None:
        resolved = resolve_range(
            _params(start_ms=500, duration_ms=750), source_duration_ms=2000
        )

        assert resolved.end_ms == 1250
        assert resolved.duration_ms == 750

    def test_an_end_and_a_duration_together_are_refused(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(
                _params(end_ms=1600, duration_ms=1000), source_duration_ms=2000
            )

        assert "not both" in raised.value.message

    def test_a_range_with_neither_end_nor_duration_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(_params(start_ms=400), source_duration_ms=2000)

        assert "end or a duration" in raised.value.message

    def test_an_end_before_the_start_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(_params(start_ms=900, end_ms=900), source_duration_ms=2000)

        assert "must be after its start" in raised.value.message

    def test_a_negative_start_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(_params(start_ms=-10, end_ms=500), source_duration_ms=2000)

        assert "zero or later" in raised.value.message

    def test_a_zero_duration_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(_params(duration_ms=0), source_duration_ms=2000)

        assert "must be positive" in raised.value.message

    def test_a_range_past_the_end_names_both_lengths(self) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(_params(start_ms=1500, end_ms=2500), source_duration_ms=2000)

        assert "2500 ms" in raised.value.message
        assert "2000 ms" in raised.value.message


# ── The re-encode slice ─────────────────────────────────────────────────────


class TestSliceSegment:
    def test_the_slice_is_the_sources_own_samples_at_the_offset(self) -> None:
        """Sample-exact: the output is the input's PCM, not a resynthesis."""
        audio = _sine(2000)
        resolved = resolve_range(
            _params(start_ms=250, end_ms=750), source_duration_ms=len(audio)
        )

        sliced = slice_segment(audio, resolved)

        start = 250 * FS // 1000
        end = 750 * FS // 1000
        np.testing.assert_array_equal(
            np.array(sliced.get_array_of_samples()),
            np.array(audio.get_array_of_samples())[start:end],
        )
        assert len(sliced) == 500

    def test_the_slice_keeps_the_tone_and_leaves_the_silence(self) -> None:
        """Decoded measurement of the slice: the marked window is what survives."""
        audio = _marked_audio()
        resolved = resolve_range(
            _params(start_ms=1000, end_ms=2000), source_duration_ms=len(audio)
        )

        sliced = slice_segment(audio, resolved)

        assert len(sliced) == 1000
        assert _rms_db(sliced) > -20.0
        assert _rms_db(slice_segment(audio, ExactRange(0, 1000, 1000))) < -50.0


# ── Copy mode ───────────────────────────────────────────────────────────────


class TestCopyTrim:
    @requires_ffmpeg
    def test_the_copy_keeps_the_requested_audio_and_reports_what_it_measured(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "marked.mp3"
        _marked_audio().export(source, format="mp3", bitrate="192k")
        before = _fingerprint(source)
        output = tmp_path / "out.mp3"
        resolved = ExactRange(start_ms=1000, end_ms=2000, duration_ms=1000)

        measured = copy_trim(source, output, resolved)

        # One MP3 frame is 1152 samples (~26 ms), so the copy may overrun the
        # requested range by up to one frame; it must not lose or add more.
        assert 1000 - 30 <= measured <= 1000 + 30
        assert measured == pytest.approx(probe_duration_ms(output), abs=1.0)

        decoded = AudioSegment.from_file(output)
        start = decoded[:300]
        assert _rms_db(start) > -20.0, (
            "the copy starts with the leading silence, so it did not begin at "
            "the requested offset"
        )
        assert abs(len(decoded) - measured) <= 30.0
        assert _fingerprint(source) == before

        message = exact_trim_message(resolved, measured, copy_mode=True)
        assert "frame-accurate stream copy" in message

    @requires_ffmpeg
    def test_the_copy_keeps_the_tags(self, tmp_path: Path) -> None:
        """A stream copy keeps the container's tags and the undo-safe rewrite."""
        from mutagen.id3 import ID3, TIT2, TPE1

        source = tmp_path / "tagged.mp3"
        _sine(2000).export(source, format="mp3", bitrate="192k")
        tags = ID3()
        tags.add(TIT2(encoding=3, text="Track One"))
        tags.add(TPE1(encoding=3, text="Album Artist"))
        tags.save(str(source))

        output = tmp_path / "out.mp3"
        copy_trim(source, output, ExactRange(0, 1000, 1000))

        written = ID3(str(output))
        assert str(written["TIT2"]) == "Track One"
        assert str(written["TPE1"]) == "Album Artist"

    @requires_ffmpeg
    def test_a_range_past_the_measured_file_is_refused(self, tmp_path: Path) -> None:
        source = tmp_path / "short.mp3"
        _sine(1000).export(source, format="mp3", bitrate="192k")

        with pytest.raises(AudioConfigValueError) as raised:
            resolve_range(
                _params(start_ms=500, end_ms=2000),
                int(probe_duration_ms(source)),
            )

        assert "the audio is only" in raised.value.message


class TestCopyExtensions:
    @pytest.mark.parametrize("ext", COPY_EXTENSIONS)
    def test_a_copy_container_is_accepted(self, ext: str) -> None:
        check_copy_extension(Path("track") / f"track{ext}")

    @pytest.mark.parametrize("ext", [".wav", ".aiff", ".ape"])
    def test_other_containers_are_refused_and_told_to_re_encode(self, ext: str) -> None:
        with pytest.raises(AudioConfigValueError) as raised:
            check_copy_extension(Path(f"track{ext}"))

        assert ext in raised.value.message
        assert "re-encode" in raised.value.message


class TestCheckCopyMode:
    def test_trim_only_is_allowed(self) -> None:
        config = StageConfig(
            declick=False, trim=True, enhance=False, normalise=False, reduce_noise=False
        )
        config.trim_params = _params(end_ms=1000)

        check_copy_mode(config)

    def test_a_decoding_stage_is_refused_by_name(self) -> None:
        config = StageConfig(declick=False, trim=True, enhance=True, normalise=False)
        config.trim_params = _params(end_ms=1000, copy_mode=True)

        with pytest.raises(AudioConfigValueError) as raised:
            check_copy_mode(config)

        assert "Enhance" in raised.value.message
        assert "copy mode off" in raised.value.message

    def test_the_silence_mode_is_untouched_by_the_check(self) -> None:
        config = StageConfig(declick=True, trim=True, enhance=True, normalise=True)
        config.trim_params = TrimParams(copy_mode=True)

        check_copy_mode(config)

    def test_copy_mode_off_is_untouched_by_the_check(self) -> None:
        config = StageConfig(declick=True, trim=True, enhance=True, normalise=True)
        config.trim_params = _params(end_ms=1000, copy_mode=False)

        check_copy_mode(config)


# ── Messages ────────────────────────────────────────────────────────────────


class TestMessages:
    def test_the_re_encode_message_names_the_mode_and_the_span(self) -> None:
        message = exact_trim_message(
            ExactRange(400, 1600, 1200), 1200.0, copy_mode=False
        )

        assert message == (
            "Exact trim to 1.200 s (0.400-1.600 s), sample-accurate re-encode"
        )

    def test_a_copy_within_a_millisecond_does_not_mention_rounding(self) -> None:
        message = exact_trim_message(ExactRange(0, 1000, 1000), 1000.4, copy_mode=True)

        assert "frame rounding" not in message
        assert "1.000 s" in message

    def test_a_copy_that_landed_on_the_next_frame_says_so(self) -> None:
        message = exact_trim_message(ExactRange(0, 1000, 1000), 1026.0, copy_mode=True)

        assert "1.026 s" in message
        assert "+26 ms of frame rounding" in message

    def test_the_preview_says_what_it_would_keep(self) -> None:
        assert exact_preview_message(ExactRange(400, 1600, 1200)) == (
            "Would trim to 1.200 s (0.400-1.600 s)"
        )
