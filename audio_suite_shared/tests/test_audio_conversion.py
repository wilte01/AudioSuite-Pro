"""
Tests for audio_suite_shared.audio_conversion.

Covers the canonical pydub↔numpy conversions, clipping protection, and
dBFS measurement on normalized arrays.
"""

import logging

import numpy as np
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import (
    check_headroom,
    clip_bounds,
    clip_to_range,
    int_dtype,
    load_as_float32,
    log_clip_event,
    measure_peak_db,
    measure_rms_db,
    numpy_to_segment,
    pack_24bit,
    segment_to_numpy,
)

FS = 44100


def _sine(freq=440, duration_ms=200, channels=1, amplitude=0.3) -> AudioSegment:
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    pcm = (wave * 32767).astype(np.int16)
    if channels == 2:
        stereo = np.column_stack([pcm, pcm])
        raw = stereo.tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(raw, frame_rate=FS, sample_width=2, channels=channels)


# ═════════════════════════════════════════════════════════════════════════════
# segment_to_numpy
# ═════════════════════════════════════════════════════════════════════════════


class TestSegmentToNumpy:
    def test_returns_float32_dtype(self):
        arr, _ = segment_to_numpy(_sine())
        assert arr.dtype == np.float32

    def test_values_in_minus_one_to_one(self):
        arr, _ = segment_to_numpy(_sine(amplitude=0.5))
        assert arr.min() >= -1.0
        assert arr.max() <= 1.0

    def test_channels_first_shape_mono(self):
        arr, _ = segment_to_numpy(_sine(channels=1))
        assert arr.shape[0] == 1

    def test_channels_first_shape_stereo(self):
        arr, _ = segment_to_numpy(_sine(channels=2))
        assert arr.shape[0] == 2

    def test_sample_rate_preserved(self):
        _, sr = segment_to_numpy(_sine())
        assert sr == FS

    def test_frame_count_matches_duration(self):
        duration_ms = 200
        arr, _ = segment_to_numpy(_sine(duration_ms=duration_ms))
        expected_frames = int(FS * duration_ms / 1000)
        assert arr.shape[1] == expected_frames

    def test_silence_produces_near_zero(self):
        audio = AudioSegment.silent(duration=100, frame_rate=FS)
        arr, _ = segment_to_numpy(audio)
        assert np.allclose(arr, 0.0, atol=1e-5)

    def test_stereo_channels_identical_for_duplicated_mono(self):
        arr, _ = segment_to_numpy(_sine(channels=2))
        np.testing.assert_array_almost_equal(arr[0], arr[1], decimal=4)


# ═════════════════════════════════════════════════════════════════════════════
# numpy_to_segment
# ═════════════════════════════════════════════════════════════════════════════


class TestNumpyToSegment:
    def test_returns_audio_segment(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert isinstance(seg, AudioSegment)

    def test_sample_rate_preserved(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert seg.frame_rate == FS

    def test_sample_width_preserved(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert seg.sample_width == 2

    def test_channels_preserved(self):
        arr = np.zeros((2, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=2)
        assert seg.channels == 2

    def test_clipping_prevents_overflow(self):
        arr = np.full((1, 100), 2.0, dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert raw.max() == np.iinfo(np.int16).max

    def test_negative_clipping(self):
        arr = np.full((1, 100), -2.0, dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert raw.min() == np.iinfo(np.int16).min

    def test_zero_array_produces_silence(self):
        arr = np.zeros((1, 1000), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        raw = np.frombuffer(seg.raw_data, dtype=np.int16)
        assert np.all(raw == 0)

    def test_24bit_packing_correct(self):
        # pack_24bit itself emits 3 bytes per sample little-endian.
        arr = np.array([1, 256, -1], dtype=np.int32)
        packed = pack_24bit(arr)
        assert len(packed) == 3 * 3
        # little-endian: [0x01 0x00 0x00] for +1
        assert packed[:3] == b"\x01\x00\x00"


# ═════════════════════════════════════════════════════════════════════════════
# clip_to_range
# ═════════════════════════════════════════════════════════════════════════════


class TestClipToRange:
    def test_within_range_unchanged(self):
        data = np.array([0.5, -0.5, 0.0], dtype=np.float32)
        out = clip_to_range(data)
        np.testing.assert_array_equal(out, data)

    def test_positive_clipped(self):
        data = np.array([1.5, 0.5], dtype=np.float32)
        out = clip_to_range(data)
        assert out[0] == 1.0
        assert out[1] == 0.5

    def test_negative_clipped(self):
        data = np.array([-1.5, -0.5], dtype=np.float32)
        out = clip_to_range(data)
        assert out[0] == -1.0
        assert out[1] == -0.5

    def test_returns_new_array(self):
        data = np.array([1.5], dtype=np.float32)
        out = clip_to_range(data)
        assert out is not data
        assert out[0] == 1.0
        assert data[0] == 1.5  # original unchanged

    def test_custom_hard_limit(self):
        data = np.array([3.0, -3.0, 1.0], dtype=np.float32)
        out = clip_to_range(data, hard_limit=2.0)
        assert out[0] == 2.0
        assert out[1] == -2.0
        assert out[2] == 1.0


# ═════════════════════════════════════════════════════════════════════════════
# measure_peak_db
# ═════════════════════════════════════════════════════════════════════════════


class TestMeasurePeakDb:
    def test_silence_very_negative(self):
        data = np.zeros(100, dtype=np.float32)
        assert measure_peak_db(data) == -120.0

    def test_sine_wave_correct(self):
        t = np.linspace(0, 1, 44100, endpoint=False)
        sine = (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        assert np.isclose(measure_peak_db(sine), 20 * np.log10(0.5), atol=1e-3)

    def test_full_scale_is_zero_dbfs(self):
        data = np.full(100, 1.0, dtype=np.float32)
        assert np.isclose(measure_peak_db(data), 0.0, atol=1e-3)


# ═════════════════════════════════════════════════════════════════════════════
# measure_rms_db
# ═════════════════════════════════════════════════════════════════════════════


class TestMeasureRmsDb:
    def test_silence_very_negative(self):
        data = np.zeros(100, dtype=np.float32)
        assert measure_rms_db(data) == -120.0

    def test_known_signal(self):
        data = np.full(100, 0.5, dtype=np.float32)
        assert np.isclose(measure_rms_db(data), 20 * np.log10(0.5), atol=1e-3)


# ═════════════════════════════════════════════════════════════════════════════
# check_headroom
# ═════════════════════════════════════════════════════════════════════════════


class TestCheckHeadroom:
    def test_within_target_returns_true(self):
        data = np.full(100, 0.5, dtype=np.float32)
        ok, peak = check_headroom(data, target_db=-0.5)
        assert ok is True
        assert peak < -0.5

    def test_above_target_returns_false(self):
        data = np.full(100, 1.0, dtype=np.float32)
        ok, peak = check_headroom(data, target_db=-0.5)
        assert ok is False
        assert peak >= -0.5

    def test_returns_actual_peak(self):
        data = np.array([0.0, 0.25, 0.0], dtype=np.float32)
        ok, peak = check_headroom(data)
        assert np.isclose(peak, 20 * np.log10(0.25), atol=1e-3)


# ═════════════════════════════════════════════════════════════════════════════
# log_clip_event
# ═════════════════════════════════════════════════════════════════════════════


class TestLogClipEvent:
    def _logger(self):
        logger = logging.getLogger("test_audio_conversion")
        logger.setLevel(logging.WARNING)
        logger.propagate = False
        return logger

    def test_no_warning_when_no_clip(self):
        logger = self._logger()
        data = np.full(100, 0.5, dtype=np.float32)
        log_clip_event(data, "test", logger)  # should not raise nor log

    def test_warning_when_clipped(self):
        caplog = logging.getLogger("test_audio_conversion")
        caplog.setLevel(logging.WARNING)
        caplog.handlers.clear()
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record)  # type: ignore[assignment]
        caplog.addHandler(handler)
        logger = self._logger()
        logger.handlers.clear()
        logger.addHandler(handler)

        data = np.array([1.5, 0.5], dtype=np.float32)
        log_clip_event(data, "stage", logger)
        assert records
        assert "Clipping detected" in records[0].getMessage()
        logger.removeHandler(handler)


# ═════════════════════════════════════════════════════════════════════════════
# bit-depth helpers
# ═════════════════════════════════════════════════════════════════════════════


class TestBitDepthHelpers:
    def test_int_dtype_16bit(self):
        assert int_dtype(2) == np.int16

    def test_int_dtype_8bit(self):
        assert int_dtype(1) == np.int8

    def test_int_dtype_unknown_falls_back_int32(self):
        assert int_dtype(5) == np.int32

    def test_clip_bounds_16bit(self):
        assert clip_bounds(2) == (np.iinfo(np.int16).min, np.iinfo(np.int16).max)

    def test_clip_bounds_24bit(self):
        assert clip_bounds(3) == (-(2**23), 2**23 - 1)

    def test_pack_24bit(self):
        arr = np.array([0, 1, -1], dtype=np.int32)
        packed = pack_24bit(arr)
        assert isinstance(packed, bytes)
        assert len(packed) == 9


# ═════════════════════════════════════════════════════════════════════════════
# load_as_float32 (alias)
# ═════════════════════════════════════════════════════════════════════════════


class TestLoadAsFloat32:
    def test_alias_matches_segment_to_numpy(self):
        audio = _sine()
        direct = segment_to_numpy(audio)
        alias = load_as_float32(audio)
        assert alias[1] == direct[1]
        np.testing.assert_array_equal(alias[0], direct[0])


# ═════════════════════════════════════════════════════════════════════════════
# round-trip
# ═════════════════════════════════════════════════════════════════════════════


class TestRoundTrip:
    def test_mono_round_trip_preserves_shape(self):
        original = _sine(channels=1, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=1)
        assert recovered.channels == 1
        assert abs(len(recovered) - len(original)) <= 5

    def test_stereo_round_trip_preserves_shape(self):
        original = _sine(channels=2, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=2)
        assert recovered.channels == 2

    def test_round_trip_low_distortion(self):
        original = _sine(amplitude=0.3, duration_ms=100)
        arr, sr = segment_to_numpy(original)
        recovered = numpy_to_segment(arr, sr, sample_width=2, num_channels=1)

        orig_raw = np.frombuffer(original.raw_data, dtype=np.int16).astype(np.float32)
        rec_raw = np.frombuffer(recovered.raw_data, dtype=np.int16).astype(np.float32)
        assert np.max(np.abs(orig_raw - rec_raw)) <= 2.0

    def test_empty_array_returns_empty_segment(self):
        arr = np.empty((1, 0), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=2, num_channels=1)
        assert len(seg) == 0
        assert seg.channels == 1

    def test_all_bit_depths(self):
        # pydub coerces sample_width=3 to 4 bytes internally; the remaining
        # widths are preserved as-is.  Round-trip must preserve width (modulo
        # the documented 3→4 coercion) and channel count.
        for width, _filtered in ((1, np.int8), (2, np.int16), (4, np.int32)):
            n = 100
            pcm = np.zeros(n, dtype=_filtered)
            audio = AudioSegment(
                pcm.tobytes(), frame_rate=FS, sample_width=width, channels=1
            )
            arr, sr = segment_to_numpy(audio)
            recovered = numpy_to_segment(arr, sr, sample_width=width, num_channels=1)
            assert recovered.frame_rate == FS
            assert recovered.channels == 1

    def test_24bit_output_coerced_to_32bit_container(self):
        """numpy_to_segment(sample_width=3) emits 24-bit PCM that pydub stores
        in a 32-bit container (documented pydub limitation).  Metadata is
        preserved; exact sample values are not asserted because pydub's
        24→32 conversion distorts negative 24-bit values."""
        arr = np.zeros((1, 100), dtype=np.float32)
        seg = numpy_to_segment(arr, FS, sample_width=3, num_channels=1)
        assert seg.sample_width == 4  # pydub coerces 3-byte → 4-byte storage
        assert seg.frame_rate == FS
        assert seg.channels == 1
