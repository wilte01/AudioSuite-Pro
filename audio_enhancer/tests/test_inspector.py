"""
tests/test_inspector.py
Unit tests for audio_enhancer/core/inspector.py metadata reading and audio
file discovery.

The mutagen reads are mocked (no real media needed): mutagen.audio.File
metadata probing, MP3 info enrichment, and graceful fallback paths are all
exercised deterministically.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_enhancer.core.inspector import (
    SUPPORTED_EXTENSIONS,
    find_audio_files,
    inspect,
)
from audio_suite_shared.audio_formats import (
    SUPPORTED_EXTENSIONS as CANONICAL_EXTENSIONS,
)


def _fake_info(**overrides) -> MagicMock:
    """Build a mutagen-like audio_info object with configurable fields."""
    info = MagicMock()
    info.sample_rate = 44100
    info.channels = 2
    info.length = 3.5
    info.bitrate = 128000
    for key, value in overrides.items():
        setattr(info, key, value)
    return info


class TestInspect:
    def test_wav_populates_info_from_mutagen(self) -> None:
        mf = MagicMock()
        mf.info = _fake_info()
        mf.tags = MagicMock()
        type(mf.tags).__len__ = MagicMock(return_value=5)
        with patch("mutagen.File", return_value=mf):
            info = inspect(Path("/base/song.wav"))

        assert info.format == "WAV"
        assert info.sample_rate == 44100
        assert info.channels == 2
        assert info.duration_sec == 3.5
        assert info.bitrate_kbps == 128
        assert info.tag_count == 5

    def test_no_tags_counts_zero(self) -> None:
        mf = MagicMock()
        mf.info = _fake_info()
        mf.tags = None
        with patch("mutagen.File", return_value=mf):
            info = inspect(Path("/base/song.flac"))
        assert info.tag_count == 0

    def test_mutagen_returns_none_leaves_defaults(self) -> None:
        with patch("mutagen.File", return_value=None):
            info = inspect(Path("/base/song.wav"))
        assert info.format == "WAV"
        assert info.sample_rate == 44100
        assert info.channels == 2
        assert info.duration_sec == 0.0

    def test_opus_default_sample_rate_is_48000(self) -> None:
        # OggOpusInfo has no `sample_rate` attribute (see comment in
        # inspector.inspect); use a real object so getattr falls back.
        audio_info = type("_OggOpusInfo", (), {"channels": 1, "length": 2.0})()
        mf = MagicMock()
        mf.info = audio_info
        mf.tags = None
        with patch("mutagen.File", return_value=mf):
            info = inspect(Path("/base/song.opus"))
        assert info.sample_rate == 48000

    def test_mutagen_error_falls_back_to_defaults(self) -> None:
        with patch("mutagen.File", side_effect=OSError("unreadable")):
            info = inspect(Path("/base/song.wav"))
        assert info.format == "WAV"
        assert info.sample_rate == 44100


class TestEnrichMp3:
    @pytest.fixture(autouse=True)
    def _mp3_mocks(self):
        """Patch the mutagen symbols that inspect/_enrich_mp3 import
        lazily so a .mp3 path can be processed without real files.  A real
        ID3NoHeaderError is used for the no-header path."""
        from mutagen.id3 import ID3NoHeaderError

        class _BitrateMode:
            VBR = "VBR"
            ABR = "ABR"
            CBR = "CBR"

        mp3_info = MagicMock()
        mp3_info.bitrate_mode = _BitrateMode.VBR
        mp3_obj = MagicMock()
        mp3_obj.info = mp3_info
        id3_obj = MagicMock()
        type(id3_obj).version = (2, 4, 0)

        mf = MagicMock()
        mf.info = _fake_info()
        mf.tags = None

        patches = [
            patch("mutagen.File", return_value=mf),
            patch("mutagen.mp3.MP3", return_value=mp3_obj),
            patch("mutagen.mp3.BitrateMode", _BitrateMode),
            patch("mutagen.id3.ID3", return_value=id3_obj),
            patch("mutagen.id3.ID3NoHeaderError", ID3NoHeaderError),
        ]
        for p in patches:
            p.start()
        yield
        for p in reversed(patches):
            p.stop()

    def test_mp3_enrichment_sets_vbr_and_id3(self) -> None:
        info = inspect(Path("/base/song.mp3"))
        assert info.is_vbr is True
        assert info.id3_version == 4

    def test_no_mp3_info_keeps_is_vbr_false(self) -> None:
        with patch(
            "mutagen.mp3.MP3",
            return_value=MagicMock(info=None),
        ):
            info = inspect(Path("/base/song.mp3"))
        assert info.is_vbr is False

    def test_id3_no_header_defaults_to_version_3(self) -> None:
        from mutagen.id3 import ID3NoHeaderError

        with patch("mutagen.id3.ID3", side_effect=ID3NoHeaderError("none")):
            info = inspect(Path("/base/song.mp3"))
        assert info.id3_version == 3
        assert info.is_vbr is True  # MP3 info enrichment still ran

    def test_mp3_read_error_falls_back_gracefully(self) -> None:
        # A corrupt/unreadable MP3 must not escape inspect(); fields keep
        # their defaults while a warning is logged.
        with patch(
            "mutagen.mp3.MP3",
            side_effect=OSError("corrupt"),
        ):
            info = inspect(Path("/base/song.mp3"))
        assert info.is_vbr is False
        assert info.id3_version == 3


class TestFindAudioFiles:
    def test_supported_set_matches_canonical(self) -> None:
        """Regression: the enhancer's discovery set must match the canonical
        shared tuple (audio_formats.py) — it previously dropped .mp4."""
        assert set(SUPPORTED_EXTENSIONS) == set(CANONICAL_EXTENSIONS)

    def test_single_supported_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.mp3"
        f.write_bytes(b"")
        assert find_audio_files(f) == [f]

    def test_unsupported_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "a.txt"
        f.write_bytes(b"")
        assert find_audio_files(f) == []

    def test_directory_lists_supported_sorted(self, tmp_path: Path) -> None:
        (tmp_path / "b.flac").write_bytes(b"")
        (tmp_path / "a.mp3").write_bytes(b"")
        (tmp_path / "skip.txt").write_bytes(b"")
        result = find_audio_files(tmp_path)
        assert result == [tmp_path / "a.mp3", tmp_path / "b.flac"]

    def test_missing_path_returns_empty(self, tmp_path: Path) -> None:
        assert find_audio_files(tmp_path / "nope") == []

    def test_mp4_discovered_like_canonical(self, tmp_path: Path) -> None:
        """Regression: .mp4 is in the canonical set and must be discoverable
        (it previously was omitted from the enhancer's local set)."""
        f = tmp_path / "video.mp4"
        f.write_bytes(b"")
        assert find_audio_files(f) == [f]
