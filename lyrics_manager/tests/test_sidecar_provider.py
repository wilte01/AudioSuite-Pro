"""
tests/test_sidecar_provider.py — tests for the local `.lrc` sidecar provider.

Covers:
- synced + plain lyric extraction from a real `.lrc` sidecar
- no sidecar → None
- malformed `.lrc` → None (logged warning, no crash)
- empty `.lrc` → None
- plain-only `.lrc` (no timestamps) is a parse error → None
- no-network guarantee (requests.get never called)
- registry integration (listed, resolvable)
- real-audio outcome: `process_single_file` writes sidecar lyrics into tags
- `_strip_timestamps` helper
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_suite_shared.tag_helper_reader import read_lyrics_tags
from audio_suite_shared.tag_helper_writer import write_synced_lyrics
from lyrics_manager.core.file_processor import process_single_file
from lyrics_manager.core.providers import (
    get_provider,
    get_provider_names,
)
from lyrics_manager.core.providers.registry import _registry
from lyrics_manager.core.providers.sidecar import SidecarProvider, _strip_timestamps

SYNCED_LRC = (
    "[ti:Test Song]\n[ar:Test Artist]\n[00:01.00]Hello world\n[00:03.50]Goodbye world\n"
)

SYNCED_LRC_NO_META = (
    "[00:00.50]First line\n[00:02.00]Second line\n[00:04.00]Third line\n"
)

PLAIN_ONLY_LRC = "Just some words\nWithout timestamps\n"


def _make_audio(tmp_path, name: str = "track.mp3", fmt: str = "mp3") -> str:
    """Create a silent audio file with artist/title tags."""
    from lyrics_manager.tests.test_file_processor import _tag_artist_title

    path = tmp_path / name
    AudioSegment.silent(duration=5000).export(str(path), format=fmt)
    _tag_artist_title(str(path), "Test Artist", "Test Song")
    return str(path)


class _SlotVar:
    def set(self, value):
        pass

    def get(self):
        return "IDLE"


def _slot_vars(n: int = 4):
    return [_SlotVar() for _ in range(n)]


@pytest.fixture
def fresh_registry():
    """Provide a clean registry and restore the original after the test."""
    snapshot = dict(_registry)
    _registry.clear()
    _registry.update(snapshot)
    try:
        yield _registry
    finally:
        _registry.clear()
        _registry.update(snapshot)


class TestStripTimestamps:
    def test_strips_mm_ss_timestamps(self):
        text = "[00:01.00]Hello\n[00:03.50]Goodbye"
        assert _strip_timestamps(text) == "Hello\nGoodbye"

    def test_strips_hh_mm_ss_timestamps(self):
        text = "[01:02:03.00]Line one\n[00:10:00.00]Line two"
        assert _strip_timestamps(text) == "Line one\nLine two"

    def test_empty_text_returns_empty(self):
        assert _strip_timestamps("") == ""

    def test_whitespace_only_lines_skipped(self):
        text = "[00:01.00]   \n[00:02.00]real text"
        assert _strip_timestamps(text) == "real text"


class TestSidecarProviderDirect:
    def test_search_returns_none_without_file_path(self):
        provider = SidecarProvider()
        result = provider.search("Artist", "Title")
        assert result is None

    def test_search_returns_none_when_no_sidecar(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))
        assert result is None

    def test_search_returns_synced_and_plain(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))

        assert result is not None
        assert result.has_lyrics
        assert result.synced_lyrics is not None
        assert "[00:01.00]" in result.synced_lyrics
        assert "Hello world" in result.synced_lyrics
        assert result.plain_lyrics is not None
        assert "Hello world" in result.plain_lyrics
        assert result.provider_name == "sidecar"

    def test_search_extracts_meta_tags(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))

        assert result is not None
        assert result.track_name == "Test Song"
        assert result.artist_name == "Test Artist"

    def test_search_no_meta_tags(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC_NO_META, encoding="utf-8")

        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))

        assert result is not None
        assert result.track_name is None
        assert result.artist_name is None
        assert result.synced_lyrics is not None
        assert result.plain_lyrics is not None

    def test_search_returns_none_for_malformed_lrc(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text("no timestamps here\n", encoding="utf-8")

        provider = SidecarProvider()
        with patch("lyrics_manager.core.providers.sidecar.logger") as log:
            result = provider.search("A", "T", file_path=str(audio))

        assert result is None
        log.warning.assert_called_once()
        assert "malformed" in str(log.warning.call_args)

    def test_search_returns_none_for_empty_lrc(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text("", encoding="utf-8")

        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))
        assert result is None

    def test_search_returns_none_for_lrc_with_only_meta(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text("[ti:No lyrics]\n[ar:Nobody]\n", encoding="utf-8")

        provider = SidecarProvider()
        result = provider.search("A", "T", file_path=str(audio))
        assert result is None

    def test_search_handles_unreadable_file(self, tmp_path):
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        with patch.object(
            type(sidecar), "read_text", side_effect=OSError("permission denied")
        ):
            with patch("lyrics_manager.core.providers.sidecar.logger") as log:
                result = provider.search("A", "T", file_path=str(audio))

        assert result is None
        log.warning.assert_called_once()
        assert "could not read" in str(log.warning.call_args)

    def test_search_with_different_extensions(self, tmp_path):
        """Sidecar resolves for any audio extension (.flac, .m4a, etc.)."""
        for ext in (".mp3", ".flac", ".ogg", ".m4a", ".opus"):
            audio = tmp_path / f"track{ext}"
            audio.write_bytes(b"\x00")
            sidecar = tmp_path / "track.lrc"
            sidecar.write_text(SYNCED_LRC_NO_META, encoding="utf-8")

            provider = SidecarProvider()
            result = provider.search("A", "T", file_path=str(audio))
            assert result is not None, f"Failed for {ext}"
            assert result.has_lyrics


class TestSidecarRegistry:
    def test_sidecar_registered_by_default(self, fresh_registry):
        assert "sidecar" in get_provider_names()

    def test_sidecar_resolvable(self, fresh_registry):
        provider = get_provider("sidecar")
        assert isinstance(provider, SidecarProvider)

    def test_sidecar_listed_alongside_lrclib(self, fresh_registry):
        names = get_provider_names()
        assert "lrclib" in names
        assert "sidecar" in names


class TestSidecarNoNetwork:
    def test_search_never_touches_network(self, tmp_path):
        """The sidecar provider reads a local file — requests.get must not be called."""
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"\x00")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        with patch("requests.get") as mock_get:
            result = provider.search("A", "T", file_path=str(audio))

        mock_get.assert_not_called()
        assert result is not None
        assert result.has_lyrics

    def test_integration_with_process_single_file_no_network(self, tmp_path):
        """Full integration: sidecar provider never calls network."""
        audio_path = _make_audio(tmp_path)
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        on_progress = MagicMock()

        with patch("requests.get") as mock_get:
            process_single_file(
                name="track.mp3",
                dir_path=str(tmp_path),
                is_dry_run=False,
                provider=provider,
                request_timeout=5.0,
                skip_existing=True,
                plain_fallback=True,
                slot_idx=0,
                lock=threading.Lock(),
                on_progress=on_progress,
                slot_vars=_slot_vars(),
            )

        mock_get.assert_not_called()
        tags = read_lyrics_tags(audio_path)
        assert tags.synced is not None
        assert "Hello world" in tags.synced


class TestSidecarRealAudioOutcome:
    def test_synced_lyrics_written_to_mp3_tags(self, tmp_path):
        """Real-audio outcome: synced lyrics from .lrc sidecar appear in the MP3 tag."""
        audio_path = _make_audio(tmp_path)
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )

        tags = read_lyrics_tags(audio_path)
        assert tags.synced is not None
        assert "[00:01.00]" in tags.synced
        assert "Hello world" in tags.synced

    def test_plain_lyrics_written_when_synced_not_supported(self, tmp_path):
        """M4A cannot store synced lyrics — plain text must be written instead."""
        audio_path = _make_audio(tmp_path, "song.m4a", "mp4")
        sidecar = tmp_path / "song.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="song.m4a",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )

        tags = read_lyrics_tags(audio_path)
        assert tags.synced is None
        assert tags.plain is not None
        assert "Hello world" in tags.plain

    def test_no_sidecar_reports_lyrics_not_found(self, tmp_path):
        """No .lrc file → the processor reports 'lyrics not found'."""
        _make_audio(tmp_path)
        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )
        assert any("lyrics not found" in str(c) for c in on_progress.call_args_list)

    def test_dry_run_never_writes(self, tmp_path):
        """Dry run: sidecar is found but no tags are written."""
        audio_path = _make_audio(tmp_path)
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=True,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )

        tags = read_lyrics_tags(audio_path)
        assert tags.synced is None
        assert tags.plain is None
        assert any("DRY RUN" in str(c) for c in on_progress.call_args_list)

    def test_skip_existing_skips_when_lyrics_present(self, tmp_path):
        """If file already has lyrics, skip_existing=True skips the sidecar."""
        audio_path = _make_audio(tmp_path)
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC, encoding="utf-8")

        # Pre-write lyrics into the file
        write_synced_lyrics(audio_path, "[00:00.01]existing\n")

        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )

        tags = read_lyrics_tags(audio_path)
        assert tags.synced is not None
        assert "[00:00.01]existing" in tags.synced
        assert any("already has lyrics" in str(c) for c in on_progress.call_args_list)

    def test_flac_synced_lyrics_written(self, tmp_path):
        """Real-audio outcome: synced sidecar lyrics appear in FLAC tags."""
        audio_path = _make_audio(tmp_path, "track.flac", "flac")
        sidecar = tmp_path / "track.lrc"
        sidecar.write_text(SYNCED_LRC_NO_META, encoding="utf-8")

        provider = SidecarProvider()
        on_progress = MagicMock()
        process_single_file(
            name="track.flac",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )

        tags = read_lyrics_tags(audio_path)
        assert tags.synced is not None
        assert "First line" in tags.synced
