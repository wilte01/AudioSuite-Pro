"""
test_lossless_gain.py — Tests for audio_suite_shared/lossless_gain.py.

Covers: side-info layout (offsets/strides/field counts), frame-size and
bitrate-table handling, frame walking, gain calculation, track/album gain
application, clamping, edge cases (no frames, non-MP3, empty file), undo
snapshot recording, and decode-based regression tests that measure the actual
per-channel output change of every frame type (stereo, joint stereo, mono,
MPEG-2 LSF).

Changed in 1.0.1: added a regression class asserting a valid MP3 already at a
gain clamp bound is a zero-change success (not "No valid MPEG frames").
"""

from __future__ import annotations

import array
import math
import os
import struct
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioFormatError
from audio_suite_shared.lossless_gain import (
    _frame_size,
    _is_valid_mpeg_frame,
    _is_xing_or_info_header,
    _side_info_layout,
    _side_info_size,
    apply_album_gain,
    apply_track_gain,
    calculate_gain_delta,
    get_frame_count,
    is_mp3_file,
    read_mp3_global_gains,
)

# MPEG version header bits
_MPEG1 = 0b11
_MPEG2 = 0b10
_MPEG25 = 0b00

# Channel-mode header bits
_MODE_STEREO = 0b00
_MODE_JOINT = 0b01
_MODE_DUAL = 0b10
_MODE_MONO = 0b11

_FFMPEG = "ffmpeg"
_FFPROBE = "ffprobe"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mp3(path: Path, duration_ms: int = 500) -> str:
    """Create a real MP3 file via pydub and return its path as a string."""
    AudioSegment.silent(duration=duration_ms).export(str(path), format="mp3")
    return str(path)


def _make_header(
    version: int,
    bitrate_idx: int,
    samplerate_idx: int,
    padding: int,
    channel_mode: int,
) -> int:
    """Build a 32-bit MPEG Layer III frame header word (no CRC)."""
    return (
        0xFFE00000
        | (version << 19)
        | (0b01 << 17)  # Layer III
        | (bitrate_idx << 12)
        | (samplerate_idx << 10)
        | (padding << 9)
        | (channel_mode << 6)
    )


def _make_tone_wav(
    path: Path, *, channels: int, sample_rate: int, duration_s: float = 1.5
) -> None:
    """Write a 440 Hz sine WAV (dual-mono for stereo) via the stdlib."""
    n = int(sample_rate * duration_s)
    frames = bytearray()
    for i in range(n):
        v = 0.4 * math.sin(2 * math.pi * 440 * i / sample_rate)
        q = struct.pack("<h", int(v * 28000))
        frames += q * channels
    import wave

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(frames))


def _make_tone_mp3(
    path: Path,
    *,
    channels: int,
    sample_rate: int,
    bitrate: str,
    joint_stereo: bool = False,
    duration_s: float = 1.5,
) -> str:
    """Encode a sine-tone MP3 with LAME via ffmpeg and return its path."""
    wav = path.with_suffix(".wav")
    _make_tone_wav(
        wav, channels=channels, sample_rate=sample_rate, duration_s=duration_s
    )
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-v",
            "error",
            "-i",
            str(wav),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-joint_stereo",
            "1" if joint_stereo else "0",
            str(path),
        ],
        check=True,
    )
    wav.unlink()
    return str(path)


def _first_audio_frame_header(data: bytes) -> int:
    """Return the byte offset of the first non Xing/Info/VBRI audio frame."""
    pos = 0
    while pos < len(data) - 4:
        if data[pos] != 0xFF or (data[pos + 1] & 0xE0) != 0xE0:
            pos += 1
            continue
        header = struct.unpack(">I", data[pos : pos + 4])[0]
        if not _is_valid_mpeg_frame(header):
            pos += 1
            continue
        if _is_xing_or_info_header(bytearray(data), pos, header):
            size = _frame_size(header) or 4
            pos += size
            continue
        return pos
    raise AssertionError("no audio frame found in fixture")


def _with_crc_protection(src: str) -> str:
    """Return a copy of *src* whose first audio frame has the CRC protection
    bit cleared (bit 16 = 0 ⇒ a 16-bit CRC follows the header)."""
    data = Path(src).read_bytes()
    offset = _first_audio_frame_header(data)
    header = struct.unpack(">I", data[offset : offset + 4])[0]
    crafted = bytearray(data)
    crafted[offset : offset + 4] = struct.pack(">I", header & ~0x00010000)
    out = Path(src).with_suffix(".crc.mp3")
    out.write_bytes(bytes(crafted))
    return str(out)


def _with_free_format(src: str) -> str:
    """Return a copy of *src* whose first audio frame has a zero bitrate index
    (bitrate index 0 ⇒ free-format, undefined frame size)."""
    data = Path(src).read_bytes()
    offset = _first_audio_frame_header(data)
    header = struct.unpack(">I", data[offset : offset + 4])[0]
    crafted = bytearray(data)
    crafted[offset : offset + 4] = struct.pack(">I", header & ~0x0000F000)
    out = Path(src).with_suffix(".free.mp3")
    out.write_bytes(bytes(crafted))
    return str(out)


def _decode_channel_count(path: str) -> int:
    """Return the decoded stream's channel count from one ffprobe."""
    probe = subprocess.run(
        [
            _FFPROBE,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=channels",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        check=True,
        text=True,
    ).stdout.strip()
    return int(probe)


def _decode_rms_db(path: str) -> list[float]:
    """Decode an audio file with ffmpeg and return per-channel RMS in dB.

    The channel count comes from a single ffprobe of the same stream (not a
    second full decode via pydub) so each measurement decodes exactly once.
    """
    nch = _decode_channel_count(path)
    raw = subprocess.run(
        [_FFMPEG, "-v", "error", "-i", path, "-map", "0:a", "-f", "s16le", "-"],
        capture_output=True,
        check=True,
    ).stdout
    samples = array.array("h")
    samples.frombytes(raw)
    n = len(samples) // nch
    rms: list[float] = []
    for ch in range(nch):
        acc = 0.0
        for i in range(ch, n * nch, nch):
            acc += samples[i] * samples[i]
        rms.append(10 * math.log10(acc / n) if n and acc else -120.0)
    return rms


def _apply_gain_and_measure(path: str, db: float) -> list[float]:
    """Apply *db* via apply_track_gain and return per-channel RMS deltas."""
    before = _decode_rms_db(path)
    with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
        apply_track_gain(path, db)
    after = _decode_rms_db(path)
    return [a - b for a, b in zip(after, before)]


# ── _side_info_layout / _side_info_size / _frame_size ───────────────────────


class TestSideInfoLayout:
    """Direct layout tests for all frame types, validated empirically.

    global_gain fields sit at a fixed first offset with a constant stride
    (both window-switching branches are 22 bits wide).  The exact-fill
    identities must hold: the fields consume the side info exactly.
    """

    def test_mpeg1_stereo_layout(self) -> None:
        # mdb 9 + private 3 + scfsi 8 + part2_3 12 + big_values 9
        assert _side_info_layout(_MPEG1, _MODE_STEREO) == (41, 59, 4)
        assert 9 + 3 + 8 + 4 * 59 == 32 * 8

    def test_mpeg1_joint_layout(self) -> None:
        assert _side_info_layout(_MPEG1, _MODE_JOINT) == (41, 59, 4)

    def test_mpeg1_dual_layout(self) -> None:
        assert _side_info_layout(_MPEG1, _MODE_DUAL) == (41, 59, 4)

    def test_mpeg1_mono_layout(self) -> None:
        # mdb 9 + private 5 + scfsi 4 (mono DOES carry scfsi)
        assert _side_info_layout(_MPEG1, _MODE_MONO) == (39, 59, 2)
        assert 9 + 5 + 4 + 2 * 59 == 17 * 8

    def test_mpeg2_stereo_layout(self) -> None:
        # mdb 8 + private 2, no scfsi; LSF scalefac_compress is 9 bits
        assert _side_info_layout(_MPEG2, _MODE_STEREO) == (31, 63, 2)
        assert 8 + 2 + 2 * 63 == 17 * 8

    def test_mpeg2_mono_layout(self) -> None:
        assert _side_info_layout(_MPEG2, _MODE_MONO) == (30, 63, 1)
        assert 8 + 1 + 63 == 9 * 8

    def test_mpeg25_stereo_layout(self) -> None:
        assert _side_info_layout(_MPEG25, _MODE_STEREO) == (31, 63, 2)

    def test_mpeg25_mono_layout(self) -> None:
        assert _side_info_layout(_MPEG25, _MODE_MONO) == (30, 63, 1)


class TestSideInfoSize:
    def test_mpeg1_stereo_32(self) -> None:
        assert _side_info_size(_MPEG1, _MODE_STEREO) == 32

    def test_mpeg1_joint_32(self) -> None:
        assert _side_info_size(_MPEG1, _MODE_JOINT) == 32

    def test_mpeg1_mono_17(self) -> None:
        assert _side_info_size(_MPEG1, _MODE_MONO) == 17

    def test_mpeg2_stereo_17(self) -> None:
        assert _side_info_size(_MPEG2, _MODE_STEREO) == 17

    def test_mpeg2_mono_9(self) -> None:
        assert _side_info_size(_MPEG2, _MODE_MONO) == 9

    def test_mpeg25_stereo_17(self) -> None:
        assert _side_info_size(_MPEG25, _MODE_STEREO) == 17

    def test_mpeg25_mono_9(self) -> None:
        assert _side_info_size(_MPEG25, _MODE_MONO) == 9


class TestFrameSize:
    def test_mpeg1_192k_44100_stereo(self) -> None:
        # 144 * 192000 / 44100 = 626.9 -> 626 (+1 with padding)
        assert _frame_size(_make_header(_MPEG1, 11, 0, 0, _MODE_STEREO)) == 626
        assert _frame_size(_make_header(_MPEG1, 11, 0, 1, _MODE_STEREO)) == 627

    def test_mpeg1_128k_44100_stereo(self) -> None:
        # 144 * 128000 / 44100 = 417.96 -> 417 (+1 with padding)
        assert _frame_size(_make_header(_MPEG1, 9, 0, 0, _MODE_STEREO)) == 417
        assert _frame_size(_make_header(_MPEG1, 9, 0, 1, _MODE_STEREO)) == 418

    def test_mpeg2_uses_lsf_bitrate_table_and_72_coefficient(self) -> None:
        # LSF bitrate index 8 is 64 kbps (NOT 112 as in the MPEG-1 table):
        # 72 * 64000 / 22050 = 208.97 -> 208 (+1 with padding)
        assert _frame_size(_make_header(_MPEG2, 8, 0, 0, _MODE_STEREO)) == 208
        assert _frame_size(_make_header(_MPEG2, 8, 0, 1, _MODE_STEREO)) == 209

    def test_mpeg25_8000Hz(self) -> None:
        # LSF bitrate index 1 = 8 kbps: 72 * 8000 / 8000 = 72 bytes
        assert _frame_size(_make_header(_MPEG25, 1, 2, 0, _MODE_MONO)) == 72

    def test_reserved_bitrate_gives_zero(self) -> None:
        assert _frame_size(_make_header(_MPEG1, 0, 0, 0, _MODE_STEREO)) == 0
        assert _frame_size(_make_header(_MPEG2, 15, 0, 0, _MODE_STEREO)) == 0

    def test_reserved_samplerate_gives_zero(self) -> None:
        assert _frame_size(_make_header(_MPEG1, 9, 3, 0, _MODE_STEREO)) == 0


# ── is_mp3_file ──────────────────────────────────────────────────────────────


class TestIsMp3File:
    def test_mp3_extension(self, tmp_path: Path) -> None:
        assert is_mp3_file(str(tmp_path / "song.mp3")) is True

    def test_mp3_uppercase(self, tmp_path: Path) -> None:
        assert is_mp3_file(str(tmp_path / "song.MP3")) is True

    def test_flac_not_mp3(self, tmp_path: Path) -> None:
        assert is_mp3_file(str(tmp_path / "song.flac")) is False

    def test_wav_not_mp3(self, tmp_path: Path) -> None:
        assert is_mp3_file(str(tmp_path / "song.wav")) is False

    def test_no_extension(self, tmp_path: Path) -> None:
        assert is_mp3_file(str(tmp_path / "song")) is False


# ── calculate_gain_delta ─────────────────────────────────────────────────────


class TestCalculateGainDelta:
    def test_zero_db_returns_zero(self) -> None:
        assert calculate_gain_delta(0.0) == 0

    def test_positive_db_positive_delta(self) -> None:
        delta = calculate_gain_delta(3.0)
        assert delta > 0

    def test_negative_db_negative_delta(self) -> None:
        delta = calculate_gain_delta(-3.0)
        assert delta < 0

    def test_known_value(self) -> None:
        # 1 unit ≈ 1.505 dB, so +1.506 dB → round(1.506 / 1.505) = 1 unit
        delta = calculate_gain_delta(1.506)
        assert delta == 1

    def test_symmetry(self) -> None:
        pos = calculate_gain_delta(5.0)
        neg = calculate_gain_delta(-5.0)
        assert pos == -neg

    def test_clamp_boundary(self) -> None:
        # Very large positive value should stay within int range
        delta = calculate_gain_delta(100.0)
        assert isinstance(delta, int)

    def test_replaygain_typical_values(self) -> None:
        # Typical ReplayGain track gain values
        for val in (-5.0, -2.0, 0.0, 2.0, 5.0):
            delta = calculate_gain_delta(val)
            assert isinstance(delta, int)


# ── read_mp3_global_gains ────────────────────────────────────────────────────


class TestReadMp3GlobalGains:
    def test_real_mp3_returns_gains(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains = read_mp3_global_gains(path)
        assert len(gains) > 0
        assert all(0 <= g <= 255 for g in gains)

    def test_non_mp3_raises_error(self, tmp_path: Path) -> None:
        path = tmp_path / "track.txt"
        path.write_text("not an mp3")
        with pytest.raises(AudioFormatError, match="No valid MPEG"):
            read_mp3_global_gains(str(path))

    def test_empty_file_raises_error(self, tmp_path: Path) -> None:
        path = tmp_path / "empty.mp3"
        path.write_bytes(b"")
        with pytest.raises(AudioFormatError, match="No valid MPEG"):
            read_mp3_global_gains(str(path))

    def test_returns_list_of_ints(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains = read_mp3_global_gains(path)
        assert all(isinstance(g, int) for g in gains)

    def test_field_count_matches_frame_type(self, tmp_path: Path) -> None:
        """Every frame contributes ngranules × nch fields (4 for stereo)."""
        path = _make_tone_mp3(
            tmp_path / "stereo.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        gains = read_mp3_global_gains(path)
        frames = get_frame_count(path)
        assert len(gains) == 4 * frames


# ── get_frame_count ──────────────────────────────────────────────────────────


class TestGetFrameCount:
    def test_real_mp3_positive_count(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        count = get_frame_count(path)
        assert count > 0

    def test_counts_frames_not_fields_for_stereo(self, tmp_path: Path) -> None:
        """Frame count must not multiply by granule/channel field count."""
        path = _make_tone_mp3(
            tmp_path / "stereo.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        frames = get_frame_count(path)
        gains = read_mp3_global_gains(path)
        assert frames > 0
        assert len(gains) == 4 * frames

    def test_non_mp3_raises_error(self, tmp_path: Path) -> None:
        path = tmp_path / "track.flac"
        path.write_bytes(b"not mp3")
        with pytest.raises(AudioFormatError):
            get_frame_count(str(path))


# ── apply_track_gain ─────────────────────────────────────────────────────────


class TestApplyTrackGain:
    def test_modifies_gain(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains_before = read_mp3_global_gains(path)

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +6.0)

        gains_after = read_mp3_global_gains(path)
        assert gains_before != gains_after

    def test_positive_gain_increases_values(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains_before = read_mp3_global_gains(path)

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +6.0)

        gains_after = read_mp3_global_gains(path)
        for before, after in zip(gains_before, gains_after):
            assert after >= before

    def test_negative_gain_decreases_values(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains_before = read_mp3_global_gains(path)

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, -6.0)

        gains_after = read_mp3_global_gains(path)
        for before, after in zip(gains_before, gains_after):
            assert after <= before

    def test_zero_gain_no_change(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        gains_before = read_mp3_global_gains(path)

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            modified = apply_track_gain(path, 0.0)

        gains_after = read_mp3_global_gains(path)
        assert gains_before == gains_after
        assert modified == 0

    def test_clamps_at_255(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +100.0)

        gains = read_mp3_global_gains(path)
        assert all(g <= 255 for g in gains)

    def test_clamps_at_0(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, -100.0)

        gains = read_mp3_global_gains(path)
        assert all(g >= 0 for g in gains)

    def test_returns_modified_count(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            count = apply_track_gain(path, +6.0)

        assert count > 0
        assert count == get_frame_count(path)

    def test_records_undo_snapshot(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")

        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            apply_track_gain(path, +6.0)

        mock_snap.assert_called_once_with(path, "lossless_gain_track")

    def test_non_mp3_raises_error(self, tmp_path: Path) -> None:
        path = tmp_path / "track.wav"
        path.write_bytes(b"RIFF" + b"\x00" * 100)
        with pytest.raises(AudioFormatError, match="No valid MPEG"):
            apply_track_gain(str(path), +6.0)

    def test_idempotent_application(self, tmp_path: Path) -> None:
        """Applying the same gain twice should double the effect."""
        path = _make_mp3(tmp_path / "track.mp3")
        gains_orig = read_mp3_global_gains(path)

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +3.0)
            gains_once = read_mp3_global_gains(path)
            apply_track_gain(path, +3.0)
            gains_twice = read_mp3_global_gains(path)

        # Each frame should have gained more after second application
        for o, once, twice in zip(gains_orig, gains_once, gains_twice):
            assert once >= o
            assert twice >= once

    def test_xing_info_frame_is_skipped(self, tmp_path: Path) -> None:
        """The encoder's Info/Xing frame must not count as an audio frame."""
        path = _make_tone_mp3(
            tmp_path / "xing.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        with open(path, "rb") as fh:
            data = fh.read()
        # ffmpeg/LAME CBR output carries an Info tag right after side info
        info_pos = data.find(b"Info")
        assert info_pos > 0

        frames = get_frame_count(path)
        gains = read_mp3_global_gains(path)
        assert frames > 0
        assert len(gains) == 4 * frames


# ── apply_album_gain ─────────────────────────────────────────────────────────


class TestApplyAlbumGain:
    def test_modifies_multiple_files(self, tmp_path: Path) -> None:
        paths = [_make_mp3(tmp_path / f"track{i}.mp3") for i in range(3)]
        gains_before = [read_mp3_global_gains(p) for p in paths]

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            results = apply_album_gain(paths, +6.0)

        assert len(results) == 3
        for p, count in results.items():
            assert count > 0

        gains_after = [read_mp3_global_gains(p) for p in paths]
        for before, after in zip(gains_before, gains_after):
            assert before != after

    def test_same_delta_across_files(self, tmp_path: Path) -> None:
        """All files should get the same global_gain delta."""
        paths = [_make_mp3(tmp_path / f"track{i}.mp3", 500) for i in range(2)]
        gains_before = [read_mp3_global_gains(p) for p in paths]

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_album_gain(paths, +6.0)

        gains_after = [read_mp3_global_gains(p) for p in paths]
        # The delta for field 0 of each file should be the same
        delta_0 = gains_after[0][0] - gains_before[0][0]
        delta_1 = gains_after[1][0] - gains_before[1][0]
        assert delta_0 == delta_1

    def test_zero_delta_no_change(self, tmp_path: Path) -> None:
        paths = [_make_mp3(tmp_path / f"track{i}.mp3") for i in range(2)]
        gains_before = [read_mp3_global_gains(p) for p in paths]

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_album_gain(paths, 0.0)

        gains_after = [read_mp3_global_gains(p) for p in paths]
        assert gains_before == gains_after

    def test_records_undo_snapshot_per_file(self, tmp_path: Path) -> None:
        paths = [_make_mp3(tmp_path / f"track{i}.mp3") for i in range(2)]

        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            apply_album_gain(paths, +6.0)

        assert mock_snap.call_count == 2
        for p in paths:
            mock_snap.assert_any_call(p, "lossless_gain_album")

    def test_empty_list_returns_empty(self, tmp_path: Path) -> None:
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            results = apply_album_gain([], +6.0)
        assert results == {}

    def test_non_mp3_in_list_raises_error(self, tmp_path: Path) -> None:
        good = _make_mp3(tmp_path / "good.mp3")
        bad = str(tmp_path / "bad.txt")
        Path(bad).write_text("not mp3")

        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            with pytest.raises(AudioFormatError, match="No valid MPEG"):
                apply_album_gain([good, bad], +6.0)


# ── Undo integration ─────────────────────────────────────────────────────────


class TestUndoIntegration:
    def test_apply_track_gain_calls_snapshot(self, tmp_path: Path) -> None:
        path = _make_mp3(tmp_path / "track.mp3")
        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            apply_track_gain(path, +6.0)
        mock_snap.assert_called_once_with(path, "lossless_gain_track")

    def test_apply_album_gain_calls_snapshot(self, tmp_path: Path) -> None:
        paths = [_make_mp3(tmp_path / f"t{i}.mp3") for i in range(2)]
        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            apply_album_gain(paths, +6.0)
        assert mock_snap.call_count == 2


# ── Decode-based regression tests (Sprint 0 / A3) ────────────────────────────
#
# These decode the output audio with ffmpeg instead of re-reading the written
# fields, so they catch wrong-offset / single-field bugs that self-consistent
# read-back tests cannot see.  The +6 dB request maps to a 4-unit global_gain
# delta ≈ +6.02 dB decoded.


class TestDecodeBasedGainStereo:
    """Decode-based checks on stereo MP3s (both channels must move)."""

    def test_stereo_mpeg1_both_channels_gain_6db(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "stereo_mpeg1.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert deltas[0] == pytest.approx(6.0, abs=0.5)
        assert deltas[1] == pytest.approx(6.0, abs=0.5)

    def test_joint_stereo_both_channels_gain_6db(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "joint_stereo.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
            joint_stereo=True,
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert deltas[0] == pytest.approx(6.0, abs=0.5)
        assert deltas[1] == pytest.approx(6.0, abs=0.5)

    def test_stereo_channel_balance_preserved(self, tmp_path: Path) -> None:
        """|ΔL − ΔR| must stay tiny — catches single-global_gain bugs."""
        path = _make_tone_mp3(
            tmp_path / "balance.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert abs(deltas[0] - deltas[1]) < 0.5

    def test_stereo_negative_gain_both_channels(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "stereo_neg.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        deltas = _apply_gain_and_measure(path, -6.0)
        assert deltas[0] == pytest.approx(-6.0, abs=0.5)
        assert deltas[1] == pytest.approx(-6.0, abs=0.5)

    def test_mpeg2_stereo_equal_per_channel_gain(self, tmp_path: Path) -> None:
        """LSF (22050 Hz) stereo: equal gain on both channels."""
        path = _make_tone_mp3(
            tmp_path / "mpeg2_stereo.mp3",
            channels=2,
            sample_rate=22050,
            bitrate="128k",
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert deltas[0] == pytest.approx(6.0, abs=0.5)
        assert deltas[1] == pytest.approx(6.0, abs=0.5)
        assert abs(deltas[0] - deltas[1]) < 0.5


class TestDecodeBasedGainMono:
    """Decode-based checks on mono MP3s."""

    def test_mono_mpeg1_gain_6db(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "mono_mpeg1.mp3",
            channels=1,
            sample_rate=44100,
            bitrate="192k",
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert deltas[0] == pytest.approx(6.0, abs=0.5)

    def test_mono_mpeg2_lsf_gain_6db(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "mono_mpeg2.mp3",
            channels=1,
            sample_rate=22050,
            bitrate="128k",
        )
        deltas = _apply_gain_and_measure(path, +6.0)
        assert deltas[0] == pytest.approx(6.0, abs=0.5)


class TestDecodeBasedIntegrity:
    """Clamping, no-reencode, and all-fields-moved invariants."""

    def test_clamp_high_does_not_corrupt(self, tmp_path: Path) -> None:
        """+1000 dB saturates every field at 255; output must still decode."""
        path = _make_tone_mp3(
            tmp_path / "clamp.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +1000.0)
        gains = read_mp3_global_gains(path)
        assert all(g == 255 for g in gains)
        rms = _decode_rms_db(path)  # must not raise
        assert all(r > -120.0 for r in rms)

    def test_no_reencode_file_size_unchanged(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "size.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        size_before = os.path.getsize(path)
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +6.0)
        assert os.path.getsize(path) == size_before

    def test_every_field_moves_by_the_same_delta(self, tmp_path: Path) -> None:
        """All granule/channel fields must shift equally (stereo: 4 fields)."""
        path = _make_tone_mp3(
            tmp_path / "allfields.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        before = read_mp3_global_gains(path)
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +6.0)
        after = read_mp3_global_gains(path)
        delta = calculate_gain_delta(6.0)
        assert len(before) == len(after) > 0
        for b, a in zip(before, after):
            assert a - b == delta


class TestGainSaturatedNoChange:
    """M6: a valid MP3 already at a clamp bound is a no-op, not a failure."""

    def _make_saturated(self, path: Path, db: float) -> Path:
        path = Path(_make_tone_mp3(path, channels=2, sample_rate=44100, bitrate="192k"))
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(str(path), db)
        return path

    def test_track_gain_at_upper_clamp_returns_zero(self, tmp_path: Path) -> None:
        path = self._make_saturated(tmp_path / "sat_hi.mp3", +1000.0)
        assert all(g == 255 for g in read_mp3_global_gains(str(path)))

        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            result = apply_track_gain(str(path), +6.0)

        assert result == 0
        # A no-op must not leave an undo row for a file that did not change.
        mock_snap.assert_not_called()

    def test_track_gain_at_lower_clamp_returns_zero(self, tmp_path: Path) -> None:
        path = self._make_saturated(tmp_path / "sat_lo.mp3", -1000.0)
        assert all(g == 0 for g in read_mp3_global_gains(str(path)))

        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            result = apply_track_gain(str(path), -6.0)

        assert result == 0
        mock_snap.assert_not_called()

    def test_album_gain_saturated_file_returns_zero(self, tmp_path: Path) -> None:
        path = self._make_saturated(tmp_path / "sat_album.mp3", +1000.0)
        with patch(
            "audio_suite_shared.lossless_gain.record_tag_edit_snapshot"
        ) as mock_snap:
            results = apply_album_gain([str(path)], +6.0)

        assert results == {str(path): 0}
        mock_snap.assert_not_called()

    def test_frameless_file_still_raises(self, tmp_path: Path) -> None:
        """The fix must narrow the error, not remove it: zero frames still raise."""
        path = tmp_path / "empty.mp3"
        path.write_bytes(b"")
        with pytest.raises(AudioFormatError, match="No valid MPEG"):
            apply_track_gain(str(path), +6.0)

    def test_album_gain_frameless_file_still_raises(self, tmp_path: Path) -> None:
        good = _make_mp3(tmp_path / "good.mp3")
        empty = tmp_path / "empty.mp3"
        empty.write_bytes(b"")
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            with pytest.raises(AudioFormatError, match="No valid MPEG"):
                apply_album_gain([good, str(empty)], +6.0)


# ── P1: CRC protection bit ───────────────────────────────────────────────────
#
# A CRC-protected MP3 clears bit 16 of the header (a 16-bit CRC follows the
# header, shifting every side-info offset by 16 bits).  A genuine CRC fixture
# is not obtainable from the encoders used here (ffmpeg/libmp3lame and LAME
# both emit the protection bit set by default), so per the plan Decision Log
# the walker REJECTS CRC-protected files with AudioFormatError rather than
# risking a silent +16-bit mis-offset.  The fixture hand-crafts one frame's
# protection bit to prove the reject path leaves the file untouched.


class TestCrcProtection:
    """CRC-protected (protection-bit-clear) frames are rejected cleanly."""

    def test_read_rejects_crc_protected_file(self, tmp_path: Path) -> None:
        src = _make_tone_mp3(
            tmp_path / "crc_src.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_crc_protection(src)
        # The parent file must still read fine (protection bit set).
        assert read_mp3_global_gains(src)
        with pytest.raises(AudioFormatError, match="[Cc][Rr][Cc]"):
            read_mp3_global_gains(crafted)

    def test_frame_count_rejects_crc_protected_file(self, tmp_path: Path) -> None:
        src = _make_tone_mp3(
            tmp_path / "crc_count.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_crc_protection(src)
        with pytest.raises(AudioFormatError, match="[Cc][Rr][Cc]"):
            get_frame_count(crafted)

    def test_apply_track_gain_rejects_without_modifying(self, tmp_path: Path) -> None:
        """Rejection must leave the on-disk file byte-identical."""
        src = _make_tone_mp3(
            tmp_path / "crc_apply.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_crc_protection(src)
        before = Path(crafted).read_bytes()
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            with pytest.raises(AudioFormatError, match="[Cc][Rr][Cc]"):
                apply_track_gain(crafted, +6.0)
        assert Path(crafted).read_bytes() == before

    def test_apply_album_gain_rejects_crc_in_list(self, tmp_path: Path) -> None:
        good = _make_tone_mp3(
            tmp_path / "crc_alb_good.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        bad = _with_crc_protection(good)
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            with pytest.raises(AudioFormatError, match="[Cc][Rr][Cc]"):
                apply_album_gain([good, bad], +6.0)

    def test_normal_file_keeps_protection_bit_set(self, tmp_path: Path) -> None:
        """LAME files must not be mistaken for CRC-protected (regression guard)."""
        path = _make_tone_mp3(
            tmp_path / "normal_prot.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        offset = _first_audio_frame_header(Path(path).read_bytes())
        header = struct.unpack(">I", Path(path).read_bytes()[offset : offset + 4])[0]
        assert (header & 0x00010000) != 0
        # And gain application still works end-to-end.
        gains_before = read_mp3_global_gains(path)
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            apply_track_gain(path, +6.0)
        assert read_mp3_global_gains(path) != gains_before


# ── P2: Free-format frames ───────────────────────────────────────────────────


class TestFreeFormatRejection:
    """Free-format frames (bitrate index 0) are rejected, not mis-scanned."""

    def test_read_rejects_free_format(self, tmp_path: Path) -> None:
        src = _make_tone_mp3(
            tmp_path / "free_src.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_free_format(src)
        assert read_mp3_global_gains(src)  # parent file still fine
        with pytest.raises(AudioFormatError, match="[Ff]ree"):
            read_mp3_global_gains(crafted)

    def test_apply_track_gain_rejects_without_modifying(self, tmp_path: Path) -> None:
        src = _make_tone_mp3(
            tmp_path / "free_apply.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_free_format(src)
        before = Path(crafted).read_bytes()
        with patch("audio_suite_shared.lossless_gain.record_tag_edit_snapshot"):
            with pytest.raises(AudioFormatError, match="[Ff]ree"):
                apply_track_gain(crafted, +6.0)
        assert Path(crafted).read_bytes() == before


# ── P3: Undo snapshot ordering ───────────────────────────────────────────────


class TestUndoSnapshotOrdering:
    """Snapshot rows are only recorded for files that were actually modified."""

    def test_invalid_file_records_no_snapshot(self, tmp_path: Path) -> None:
        """An invalid (CRC-protected) file inside a batch creates no undo row."""
        from audio_suite_shared.batch_undo import (
            BatchUndoLog,
            clear_active_batch,
            set_active_batch,
        )

        good = _make_tone_mp3(
            tmp_path / "order_good.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        crafted = _with_crc_protection(good)
        db = str(tmp_path / "undo.db")
        batch_id = set_active_batch("test", "tag_edit", db_path=db)
        try:
            with pytest.raises(AudioFormatError):
                apply_track_gain(crafted, +6.0)
        finally:
            clear_active_batch()
        with BatchUndoLog(db_path=db) as log:
            records = log.get_batch_records(batch_id)
        assert records == []

    def test_valid_file_records_snapshot(self, tmp_path: Path) -> None:
        """A successfully modified file still gets one undo row."""
        from audio_suite_shared.batch_undo import (
            BatchUndoLog,
            clear_active_batch,
            set_active_batch,
        )

        good = _make_tone_mp3(
            tmp_path / "order_valid.mp3",
            channels=2,
            sample_rate=44100,
            bitrate="192k",
        )
        db = str(tmp_path / "undo.db")
        batch_id = set_active_batch("test", "tag_edit", db_path=db)
        try:
            apply_track_gain(good, +6.0)
        finally:
            clear_active_batch()
        with BatchUndoLog(db_path=db) as log:
            records = log.get_batch_records(batch_id)
        assert len(records) == 1


# ── P4: MPEG-2.5 decode regression + measurement hygiene ─────────────────────


class TestDecodeBasedGainMpeg25:
    """MPEG-2.5 (8000 Hz) decode-based checks — the docstring claims support,
    so the actual audio outcome must be verified, not just the field offsets."""

    def test_mpeg25_8000hz_mono_gain_1_5db(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "mpeg25_mono.mp3",
            channels=1,
            sample_rate=8000,
            bitrate="48k",
        )
        deltas = _apply_gain_and_measure(path, 1.505)
        assert len(deltas) == 1
        assert deltas[0] == pytest.approx(1.505, abs=0.5)

    def test_mpeg25_8000hz_stereo_equal_per_channel(self, tmp_path: Path) -> None:
        path = _make_tone_mp3(
            tmp_path / "mpeg25_stereo.mp3",
            channels=2,
            sample_rate=8000,
            bitrate="64k",
        )
        deltas = _apply_gain_and_measure(path, 1.505)
        assert len(deltas) == 2
        assert deltas[0] == pytest.approx(1.505, abs=0.5)
        assert deltas[1] == pytest.approx(1.505, abs=0.5)
        assert abs(deltas[0] - deltas[1]) < 0.5
