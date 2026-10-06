"""
tests/test_file_processor.py — pytest suite for the batch lyric processor.

``process_single_file`` is exercised against real audio fixtures built with
pydub + mutagen; ``run_fetch`` uses a registered fake provider so the suite
never touches the network.
"""

from __future__ import annotations

import threading
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from pydub import AudioSegment

from audio_suite_shared.tag_helper_reader import read_lyrics_tags
from audio_suite_shared.tag_helper_writer import write_synced_lyrics
from lyrics_manager.core.file_processor import process_single_file, run_fetch
from lyrics_manager.core.providers import (
    LyricProvider,
    LyricProviderError,
    LyricResult,
    register_provider,
)
from lyrics_manager.core.providers.registry import _registry

SYNCED_LRC = "[00:01.00]Hello\n[00:03.00]Bye\n"
PLAIN_TEXT = "Hello\nBye\n"


def _make_audio(tmp_path, name: str = "track.mp3", fmt: str = "mp3") -> str:
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format=fmt)
    return str(path)


def _tag_artist_title(path: str, artist: str, title: str) -> None:
    if path.endswith((".m4a", ".mp4")):
        m = MP4(path)
        if m.tags is None:
            m.add_tags()
        m["\xa9ART"] = [artist]
        m["\xa9nam"] = [title]
        m.save()
    elif path.endswith((".flac", ".ogg", ".opus")):
        f = FLAC(path) if path.endswith(".flac") else __import__("mutagen").File(path)
        if f.tags is None:
            f.add_tags()
        f["artist"] = [artist]
        f["title"] = [title]
        f.save()
    else:
        from mutagen.id3 import TIT2, TPE1

        a = MP3(path)
        if a.tags is None:
            a.add_tags()
        a.tags.add(TPE1(encoding=3, text=[artist]))
        a.tags.add(TIT2(encoding=3, text=[title]))
        a.save()


class _FakeProvider(LyricProvider):
    name = "fake_processor_provider"

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.searches = []

    def search(self, artist, title, *, timeout=10.0):
        self.searches.append((artist, title, timeout))
        if self._error is not None:
            raise self._error
        return self._result


class _SlotVar:
    def set(self, value):
        pass

    def get(self):
        return "IDLE"


def _slot_vars(n: int = 4):
    return [_SlotVar() for _ in range(n)]


class TestProcessSingleFile:
    def _process(
        self,
        tmp_path,
        provider,
        *,
        dry_run=False,
        skip_existing=True,
        plain_fallback=True,
        filename: str = "track.mp3",
        fmt: str = "mp3",
    ):
        path = _make_audio(tmp_path, filename, fmt)
        _tag_artist_title(path, "Artist", "Song")
        on_progress = MagicMock()
        process_single_file(
            name=filename,
            dir_path=str(tmp_path),
            is_dry_run=dry_run,
            provider=provider,
            request_timeout=5.0,
            skip_existing=skip_existing,
            plain_fallback=plain_fallback,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )
        return path, on_progress

    def test_writes_synced_lyrics(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(
                provider_name="fake", synced_lyrics=SYNCED_LRC, plain_lyrics=PLAIN_TEXT
            )
        )
        path, _ = self._process(tmp_path, provider)
        tags = read_lyrics_tags(path)
        assert tags.synced is not None
        assert tags.synced.strip().startswith("[00:01.00]Hello")

    def test_synced_unsupported_falls_back_to_plain(self, tmp_path):
        """M4A cannot store synced lyrics — must fall back to plain text."""
        provider = _FakeProvider(
            result=LyricResult(
                provider_name="fake", synced_lyrics=SYNCED_LRC, plain_lyrics=PLAIN_TEXT
            )
        )
        path, on_progress = self._process(
            tmp_path, provider, filename="song.m4a", fmt="mp4"
        )
        tags = read_lyrics_tags(path)
        assert tags.synced is None
        assert tags.plain is not None and PLAIN_TEXT.startswith(tags.plain.split()[0])
        assert any(
            "plain lyrics (synced unsupported)" in str(c)
            for c in on_progress.call_args_list
        )

    def test_writes_plain_when_only_plain_available(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", plain_lyrics=PLAIN_TEXT)
        )
        path, _ = self._process(tmp_path, provider)
        tags = read_lyrics_tags(path)
        assert tags.synced is None
        assert tags.plain == PLAIN_TEXT or tags.plain == PLAIN_TEXT.strip()

    def test_skip_existing_skips_without_calling_provider(self, tmp_path):
        path = _make_audio(tmp_path)
        _tag_artist_title(path, "Artist", "Song")
        write_synced_lyrics(path, "[00:01.00]already\n")
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", synced_lyrics=SYNCED_LRC)
        )
        on_progress = MagicMock()
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=False,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=on_progress,
            slot_vars=_slot_vars(),
        )
        assert provider.searches == []
        tags = read_lyrics_tags(path)
        assert tags.synced is not None
        assert "[00:01.00]already" in tags.synced
        assert any("already has lyrics" in str(c) for c in on_progress.call_args_list)

    def test_overwrites_when_skip_existing_false(self, tmp_path):
        path = _make_audio(tmp_path)
        _tag_artist_title(path, "Artist", "Song")
        write_synced_lyrics(path, "[00:01.00]old\n")
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", synced_lyrics="[00:02.00]new\n")
        )
        process_single_file(
            name="track.mp3",
            dir_path=str(tmp_path),
            is_dry_run=False,
            provider=provider,
            request_timeout=5.0,
            skip_existing=False,
            plain_fallback=False,
            slot_idx=0,
            lock=threading.Lock(),
            on_progress=MagicMock(),
            slot_vars=_slot_vars(),
        )
        tags = read_lyrics_tags(path)
        assert "[00:02.00]new" in tags.synced

    def test_unknown_tags_skipped_without_calling_provider(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", synced_lyrics=SYNCED_LRC)
        )
        path = _make_audio(tmp_path, "unknown.mp3")
        _tag_artist_title(path, "Unknown", "Unknown")
        on_progress = MagicMock()
        process_single_file(
            name="unknown.mp3",
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
        assert provider.searches == []
        assert any("no artist/title tags" in str(c) for c in on_progress.call_args_list)

    def test_no_result_reports_skipped(self, tmp_path):
        provider = _FakeProvider(result=None)
        _, on_progress = self._process(tmp_path, provider)
        assert any("lyrics not found" in str(c) for c in on_progress.call_args_list)

    def test_provider_error_reports_error(self, tmp_path):
        provider = _FakeProvider(error=LyricProviderError("network down"))
        _, on_progress = self._process(tmp_path, provider)
        assert any("lyric lookup failed" in str(c) for c in on_progress.call_args_list)

    def test_dry_run_never_writes(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", synced_lyrics=SYNCED_LRC)
        )
        path, on_progress = self._process(tmp_path, provider, dry_run=True)
        tags = read_lyrics_tags(path)
        assert tags.synced is None
        assert any("DRY RUN" in str(c) for c in on_progress.call_args_list)

    def test_synced_write_failure_without_fallback_reports_error(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(
                provider_name="fake",
                synced_lyrics="no timestamp here\n",
                plain_lyrics=None,
            )
        )
        _, on_progress = self._process(tmp_path, provider, plain_fallback=False)
        assert any(
            "could not embed synced lyrics" in str(c)
            for c in on_progress.call_args_list
        )

    def test_plain_only_with_fallback_disabled_skipped(self, tmp_path):
        provider = _FakeProvider(
            result=LyricResult(provider_name="fake", plain_lyrics=PLAIN_TEXT)
        )
        path, on_progress = self._process(tmp_path, provider, plain_fallback=False)
        tags = read_lyrics_tags(path)
        assert tags.plain is None
        assert any("SKIPPED" in str(c) for c in on_progress.call_args_list)


class TestRunFetch:
    @staticmethod
    @pytest.fixture()
    def registered_fake():
        class _Fake(LyricProvider):
            name = "fake_runfetch_provider"

            def search(self, artist, title, *, timeout=10.0):
                if title == "Song with plain":
                    return LyricResult(
                        provider_name=self.name, plain_lyrics="plain text"
                    )
                return None

        snapshot = dict(_registry)
        _registry.clear()
        _registry.update(snapshot)
        register_provider(_Fake)
        try:
            yield _Fake
        finally:
            _registry.clear()
            _registry.update(snapshot)

    def _make_dir(self, tmp_path):
        synced_path = tmp_path / "plain.mp3"
        AudioSegment.silent(duration=100).export(str(synced_path), format="mp3")
        _tag_artist_title(str(synced_path), "Artist", "Song with plain")
        nohit_path = tmp_path / "nohit.flac"
        AudioSegment.silent(duration=100).export(str(nohit_path), format="flac")
        _tag_artist_title(str(nohit_path), "Artist", "Not in db")
        return tmp_path

    def test_complete_callback_receives_counts(self, tmp_path, registered_fake):
        work = self._make_dir(tmp_path)
        counts = {}
        progress = []

        def on_complete(**kw):
            counts.update(kw)

        run_fetch(
            dir_path=str(work),
            is_dry_run=False,
            provider_name="fake_runfetch_provider",
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_vars=_slot_vars(),
            slot_queue=Queue(),
            on_progress=lambda **kw: progress.append(kw),
            on_complete=on_complete,
            on_error=lambda msg: None,
            parallel_mode=True,
            max_workers=2,
        )
        assert counts["total"] == 2
        assert counts["errors"] == 0
        assert counts["processed"] == 2
        assert counts["skipped"] == 1  # the "Not in db" file
        # plain lyrics written for the matching file.
        tags = read_lyrics_tags(str(work / "plain.mp3"))
        assert tags.plain == "plain text"

    def test_unknown_provider_does_not_raise(self, tmp_path, registered_fake):
        work = self._make_dir(tmp_path)
        errors = []

        run_fetch(
            dir_path=str(work),
            is_dry_run=True,
            provider_name="missing",
            request_timeout=5.0,
            skip_existing=True,
            plain_fallback=True,
            slot_vars=_slot_vars(),
            slot_queue=Queue(),
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda msg: errors.append(msg),
            parallel_mode=False,
            max_workers=1,
        )
        assert isinstance(errors, list)


class _FakeResponse:
    """Minimal requests response matching LRCLIBProvider use."""

    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self._body = body

    @property
    def content(self) -> bytes:
        return self._body

    def json(self) -> dict:
        import json as _json

        return _json.loads(self._body.decode("utf-8"))


class TestRegisteredLrclibWithMockedNetwork:
    def test_lrclib_search_with_mocked_requests(self):
        body = '{"syncedLyrics": "[00:01.00]x\\n", "plainLyrics": "x"}'.encode("utf-8")
        from lyrics_manager.core.providers import get_provider

        with patch("requests.get", return_value=_FakeResponse(200, body)):
            provider = get_provider("lrclib")
            result = provider.search("Artist", "Title")
        assert result is not None
        assert result.has_lyrics
