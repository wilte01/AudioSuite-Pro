"""
test_audio_playback.py — Unit tests for audio_suite_shared.audio_playback.

Strategy
--------
Playback devices and codecs are mocked out.  The snapshot helpers (which only
touch the local filesystem) and the pure-logic functions are exercised against
real temp files.  ``sounddevice``/``pydub`` are never required at import time.
"""

from __future__ import annotations

import logging
import struct
import threading
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audio_suite_shared import audio_playback
from audio_suite_shared.audio_playback import (
    AudioPlaybackError,
    AuditionItem,
    can_audition,
    create_original_snapshot,
    describe_failure,
    peek_first_audio,
    play_audio,
    playback_status,
    snapshot_first_audio,
    stop_playback,
)

_EXTS: tuple[str, ...] = (".mp3", ".wav")


def _write_wav(
    path: Path,
    channels: int = 1,
    width: int = 2,
    rate: int = 8000,
    payload: bytes = b"",
) -> None:
    """Write a raw PCM WAV for _read_wav / _play_wav tests."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(width)
        wf.setframerate(rate)
        wf.writeframes(payload)


@pytest.fixture(autouse=True)
def _reset_playback_state() -> None:
    """Leave no temp snapshots or playback state across tests."""
    yield
    audio_playback.clear_snapshots()
    audio_playback._current_wav = None
    audio_playback._play_thread = None


# ---------------------------------------------------------------------------
# AuditionItem
# ---------------------------------------------------------------------------


class TestAuditionItem:
    def test_path_normalised_to_path(self) -> None:
        item = AuditionItem("C:/music/track.mp3", "Original")
        assert item.path == Path("C:/music/track.mp3")
        assert item.label == "Original"

    def test_default_label_empty(self) -> None:
        assert AuditionItem("a.mp3").label == ""

    def test_exists_true(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        assert AuditionItem(f).exists() is True

    def test_exists_false(self) -> None:
        assert AuditionItem("missing.mp3").exists() is False


# ---------------------------------------------------------------------------
# Decoding / _ensure_wav
# ---------------------------------------------------------------------------


class TestEnsureWav:
    def test_missing_file_raises(self) -> None:
        with pytest.raises(AudioPlaybackError) as err:
            audio_playback._ensure_wav(Path("missing.mp3"))
        assert err.value.context["path"] == str(Path("missing.mp3"))

    def test_undecodable_raises(self, tmp_path: Path) -> None:
        source = tmp_path / "bad.mp3"
        source.write_bytes(b"not audio")
        with (
            patch("pydub.AudioSegment.from_file", side_effect=RuntimeError("boom")),
            pytest.raises(AudioPlaybackError) as err,
        ):
            audio_playback._ensure_wav(source)
        assert err.value.original is not None

    def test_export_failure_cleans_temp_wav(self, tmp_path: Path) -> None:
        source = tmp_path / "ok.mp3"
        source.write_bytes(b"audio")
        segment = MagicMock()
        segment.export.side_effect = OSError("disk stuck")
        with (
            patch("pydub.AudioSegment.from_file", return_value=segment),
            patch.object(audio_playback, "_cleanup") as mock_cleanup,
            pytest.raises(AudioPlaybackError),
        ):
            audio_playback._ensure_wav(source)
        assert mock_cleanup.call_args[0][0] is not None


# ---------------------------------------------------------------------------
# stop_playback / _play_wav
# ---------------------------------------------------------------------------


class TestStopPlayback:
    def test_cleans_current_wav_and_flags_stop(self, tmp_path: Path) -> None:
        wav = tmp_path / "x.wav"
        wav.write_bytes(b"data")
        audio_playback._current_wav = wav
        with patch.object(audio_playback, "_cleanup") as mock_cleanup:
            stop_playback()
        mock_cleanup.assert_called_once_with(wav)
        assert audio_playback._current_wav is None
        assert audio_playback._stop_event.is_set()

    def test_joins_in_flight_thread(self) -> None:
        previous = MagicMock()
        previous.is_alive.return_value = True
        audio_playback._play_thread = previous
        stop_playback()
        previous.join.assert_called_once()
        assert audio_playback._stop_event.is_set()

    def test_does_not_join_dead_thread(self) -> None:
        previous = MagicMock()
        previous.is_alive.return_value = False
        audio_playback._play_thread = previous
        stop_playback()
        previous.join.assert_not_called()

    def test_never_raises_when_idle(self) -> None:
        stop_playback()
        stop_playback()


class TestPlayWav:
    def test_noop_when_backend_missing(self) -> None:
        with patch.object(audio_playback, "_sd", None):
            audio_playback._play_wav(Path("x.wav"), None, threading.Event())

    def test_stops_early_when_event_set(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        _write_wav(wav, channels=1, width=2, rate=8000, payload=b"\x00\x01" * 10)
        device = MagicMock()
        stop = threading.Event()
        stop.set()
        with patch.object(audio_playback, "_sd", device):
            audio_playback._play_wav(wav, None, stop)
        output = device.OutputStream.return_value.__enter__.return_value
        output.write.assert_not_called()

    def test_writes_all_blocks_when_not_stopped(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        # rate=100 → samples_per_block = int(100 * 0.05) = 5; 7 frames → 2 writes.
        _write_wav(wav, channels=1, width=2, rate=100, payload=b"\x00\x01" * 7)
        device = MagicMock()
        with patch.object(audio_playback, "_sd", device):
            audio_playback._play_wav(wav, None, threading.Event())
        device.OutputStream.assert_called_once()
        stream_kwargs = device.OutputStream.call_args.kwargs
        assert stream_kwargs["samplerate"] == 100
        assert stream_kwargs["channels"] == 1
        output = device.OutputStream.return_value.__enter__.return_value
        assert output.write.call_count == 2
        first, second = output.write.call_args_list
        assert first[0][0].shape == (5, 1)
        assert second[0][0].shape == (2, 1)

    def test_empty_wav_never_opens_stream(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        _write_wav(wav, channels=1, width=2, rate=8000, payload=b"")
        device = MagicMock()
        with patch.object(audio_playback, "_sd", device):
            audio_playback._play_wav(wav, None, threading.Event())
        device.OutputStream.assert_not_called()


class TestReadWav:
    def test_stereo_16bit(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        payload = struct.pack("<6h", 32767, -32768, 0, 0, 16384, -16384)
        _write_wav(wav, channels=2, width=2, rate=44100, payload=payload)
        data, rate = audio_playback._read_wav(wav)
        assert rate == 44100
        assert data.shape == (3, 2)
        assert data.dtype == np.float32
        np.testing.assert_allclose(data[0], [32767 / 32768, -1.0], atol=1e-6)
        np.testing.assert_allclose(data[2], [0.5, -0.5], atol=1e-6)

    def test_mono_8bit(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        _write_wav(wav, channels=1, width=1, rate=8000, payload=bytes([128, 255, 0]))
        data, rate = audio_playback._read_wav(wav)
        assert rate == 8000
        assert data.shape == (3, 1)
        np.testing.assert_allclose(data[:, 0], [0.0, 127 / 128, -1.0], atol=1e-6)

    def test_32bit(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        payload = struct.pack("<2i", 2**31 - 1, -(2**31))
        _write_wav(wav, channels=1, width=4, rate=48000, payload=payload)
        data, _ = audio_playback._read_wav(wav)
        np.testing.assert_allclose(data[:, 0], [1.0, -1.0], atol=1e-6)

    def test_unsupported_width_raises(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        _write_wav(wav, channels=1, width=3, rate=8000, payload=b"\x00" * 3)
        with pytest.raises(AudioPlaybackError) as err:
            audio_playback._read_wav(wav)
        assert err.value.context["sample_width"] == 3

    def test_empty_frames_shape(self, tmp_path: Path) -> None:
        wav = tmp_path / "s.wav"
        _write_wav(wav, channels=2, width=2, rate=8000, payload=b"")
        data, _ = audio_playback._read_wav(wav)
        assert data.shape == (0, 2)
        assert data.size == 0


# ---------------------------------------------------------------------------
# Backend status helpers
# ---------------------------------------------------------------------------


class TestBackendHelpers:
    def test_can_audition_requires_backend_and_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        with patch.object(audio_playback, "_HAS_BACKEND", True):
            assert can_audition(f) is True
        with patch.object(audio_playback, "_HAS_BACKEND", False):
            assert can_audition(f) is False
            assert can_audition("missing.mp3") is False

    def test_playback_status(self) -> None:
        with patch.object(audio_playback, "_HAS_BACKEND", True):
            assert playback_status() == "available"
        with patch.object(audio_playback, "_HAS_BACKEND", False):
            assert playback_status() == "unavailable"

    def test_describe_failure_missing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        assert describe_failure(f) == f"File not found: {f.name}"

    def test_describe_failure_no_backend(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        with patch.object(audio_playback, "_HAS_BACKEND", False):
            assert "not available" in describe_failure(f)

    def test_describe_failure_generic(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        with patch.object(audio_playback, "_HAS_BACKEND", True):
            assert "could not be decoded" in describe_failure(f)


# ---------------------------------------------------------------------------
# play_audio
# ---------------------------------------------------------------------------


class TestPlayAudio:
    def test_returns_false_without_backend(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"x")
        with patch.object(audio_playback, "_HAS_BACKEND", False):
            assert play_audio(f, block=True) is False

    def test_block_runs_full_path(self, tmp_path: Path) -> None:
        source = tmp_path / "a.mp3"
        source.write_bytes(b"x")
        wav = tmp_path / "out.wav"
        wav.write_bytes(b"w")
        with (
            patch.object(audio_playback, "_HAS_BACKEND", True),
            patch.object(audio_playback, "_ensure_wav", return_value=wav) as mock_wav,
            patch.object(audio_playback, "_play_wav") as mock_play,
        ):
            result = play_audio(source, device="dev", block=True)
        assert result is True
        mock_wav.assert_called_once_with(source)
        assert mock_play.call_args[0][0] == wav
        assert mock_play.call_args[0][1] == "dev"
        assert isinstance(mock_play.call_args[0][2], threading.Event)

    def test_preparation_failure_is_logged_and_swallowed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Worker-thread failures must reach the log, never the GUI thread."""
        with (
            patch.object(audio_playback, "_HAS_BACKEND", True),
            patch.object(
                audio_playback,
                "_ensure_wav",
                side_effect=RuntimeError("boom"),
            ),
            patch.object(audio_playback, "_play_wav") as mock_play,
        ):
            with caplog.at_level(
                logging.ERROR, logger="audio_suite_shared.audio_playback"
            ):
                result = play_audio(tmp_path / "a.mp3", block=True)
        assert result is True
        mock_play.assert_not_called()
        assert "Audition playback failed" in caplog.text

    def test_spawns_daemon_thread_when_not_blocking(self) -> None:
        with (
            patch.object(audio_playback, "_HAS_BACKEND", True),
            patch("audio_suite_shared.audio_playback.threading.Thread") as mock_thread,
        ):
            result = play_audio("C:/music/a.mp3")
        assert result is True
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
        kwargs = mock_thread.call_args.kwargs
        assert kwargs["daemon"] is True
        assert callable(kwargs["target"])
        assert audio_playback._play_thread is mock_thread.return_value

    def test_new_play_interrupts_previous_thread(self) -> None:
        """A second Play click must replace playback, never stack streams."""
        previous = MagicMock()
        previous.is_alive.return_value = True
        audio_playback._play_thread = previous
        old_event = threading.Event()
        audio_playback._stop_event = old_event
        with (
            patch.object(audio_playback, "_HAS_BACKEND", True),
            patch("audio_suite_shared.audio_playback.threading.Thread") as mock_thread,
        ):
            result = play_audio("C:/music/a.mp3")
        assert result is True
        assert old_event.is_set() is True
        previous.join.assert_called_once()
        assert not audio_playback._stop_event.is_set()
        mock_thread.return_value.start.assert_called_once()

    def test_new_play_skips_join_when_previous_dead(self) -> None:
        previous = MagicMock()
        previous.is_alive.return_value = False
        audio_playback._play_thread = previous
        with (
            patch.object(audio_playback, "_HAS_BACKEND", True),
            patch("audio_suite_shared.audio_playback.threading.Thread") as mock_thread,
        ):
            result = play_audio("C:/music/a.mp3")
        assert result is True
        previous.join.assert_not_called()
        mock_thread.return_value.start.assert_called_once()


# ---------------------------------------------------------------------------
# Snapshot helpers (real filesystem, no device required)
# ---------------------------------------------------------------------------


class TestSnapshots:
    def test_snapshot_dir_created_and_cleared(self) -> None:
        first = audio_playback.audition_snapshot_dir()
        assert first.is_dir()
        assert audio_playback.audition_snapshot_dir() == first
        audio_playback.clear_snapshots()
        assert audio_playback._snapshot_dir is None
        audio_playback.clear_snapshots()  # idempotent

    def test_create_original_snapshot_copies_file(self, tmp_path: Path) -> None:
        source = tmp_path / "track.mp3"
        source.write_bytes(b"payload")
        dest = create_original_snapshot(source, _EXTS)
        assert dest is not None
        assert dest.is_file()
        assert dest.read_bytes() == b"payload"
        assert dest.stem == "track_orig"
        assert dest.suffix == ".mp3"

    def test_create_original_snapshot_unsupported_returns_none(
        self, tmp_path: Path
    ) -> None:
        source = tmp_path / "track.txt"
        source.write_bytes(b"x")
        assert create_original_snapshot(source, _EXTS) is None

    def test_create_original_snapshot_missing_returns_none(
        self, tmp_path: Path
    ) -> None:
        assert create_original_snapshot(tmp_path / "nope.mp3", _EXTS) is None

    def test_snapshot_first_audio_directory_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.mp3").write_bytes(b"b")
        (tmp_path / "a.mp3").write_bytes(b"a")
        (tmp_path / "noise.txt").write_bytes(b"x")
        dest = snapshot_first_audio(tmp_path, _EXTS)
        assert dest is not None
        assert dest.stem == "a_orig"

    def test_snapshot_first_audio_from_file(self, tmp_path: Path) -> None:
        source = tmp_path / "single.wav"
        source.write_bytes(b"w")
        dest = snapshot_first_audio(source, _EXTS)
        assert dest is not None
        assert dest.read_bytes() == b"w"

    def test_snapshot_first_audio_no_match(self, tmp_path: Path) -> None:
        (tmp_path / "x.txt").write_bytes(b"x")
        assert snapshot_first_audio(tmp_path, _EXTS) is None

    def test_peek_first_audio_matches_snapshot_source(self, tmp_path: Path) -> None:
        first = tmp_path / "a.mp3"
        first.write_bytes(b"a")
        (tmp_path / "b.mp3").write_bytes(b"b")
        assert peek_first_audio(tmp_path, _EXTS) == first
        assert peek_first_audio(first, _EXTS) == first
        assert peek_first_audio(tmp_path / "c.mp3", _EXTS) is None
