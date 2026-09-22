"""
tests/test_synced_lyrics.py — MP3 (SYLT) + FLAC/OGG (SYNCEDLYRICS) round trips.

Uses pydub + mutagen to build real audio fixtures, mirroring
metadata_scrubber/tests/test_scrubber.py.
"""

from __future__ import annotations

from unittest.mock import patch

import mutagen
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioTagError
from audio_suite_shared.lrc_handler import LrcMetadata, LrcParseError, parse_lrc
from audio_suite_shared.tag_helper_reader import (
    read_lyrics_tags,
    read_synced_lyrics,
    read_tags_raw,
)
from audio_suite_shared.tag_helper_writer import write_plain_lyrics, write_synced_lyrics

LRC_TEXT = (
    "[ti:Test Song]\n"
    "[ar:Test Artist]\n"
    "[00:01.50]Hello\n"
    "[00:03.00]Middle verse\n"
    "[00:05.25]Bye\n"
)

PLAIN_TEXT = "Line one\nLine two\nLine three\n"


def _make_audio(tmp_path, name: str, fmt: str) -> str:
    path = tmp_path / name
    AudioSegment.silent(duration=100).export(str(path), format=fmt)
    return str(path)


def _set_raw_comment(path: str, key: str, value: str) -> None:
    """Set a single Vorbis comment field via mutagen and save."""
    audio = mutagen.File(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags[key] = [value]
    audio.save()


class TestMp3RoundTrip:
    def test_write_then_read_preserves_lyric_lines(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "track.mp3", "mp3")
        write_synced_lyrics(path, LRC_TEXT)
        out = read_synced_lyrics(path)
        assert out is not None
        doc = parse_lrc(out)
        assert [(line.timestamp_ms, line.text) for line in doc.lines] == [
            (1500, "Hello"),
            (3000, "Middle verse"),
            (5250, "Bye"),
        ]
        # ID3 SYLT carries no LRC meta tags.
        assert doc.metadata == LrcMetadata()

    def test_read_none_when_no_sylt(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "plain.mp3", "mp3")
        assert read_synced_lyrics(path) is None

    def test_rewrite_replaces_previous_frame(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "overwrite.mp3", "mp3")
        write_synced_lyrics(path, "[00:01.00]first\n")
        write_synced_lyrics(path, "[00:09.00]second\n")
        out = read_synced_lyrics(path)
        assert out is not None
        assert parse_lrc(out).lines[0].timestamp_ms == 9000

    def test_sylt_frame_metadata(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "frame.mp3", "mp3")
        write_synced_lyrics(path, "[00:01.00]x\n")
        tags = read_tags_raw(path)
        frames = tags.getall("SYLT")
        assert len(frames) == 1
        sylt = frames[0]
        assert sylt.type == 1  # lyrics
        assert sylt.format == 2  # enhanced text (LRC)
        assert sylt.lang == "XXX"

    def test_invalid_lrc_raises_and_nothing_written(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "bad.mp3", "mp3")
        with pytest.raises(LrcParseError, match="without a timestamp"):
            write_synced_lyrics(path, "no timestamp here\n")
        assert read_synced_lyrics(path) is None


class TestTxxxFallback:
    def test_read_falls_back_to_txxx_when_no_sylt(self, tmp_path) -> None:
        """TXXX:SYNCEDLYRICS written by Picard is readable as synced lyrics."""
        from mutagen.id3 import ID3, TXXX

        path = _make_audio(tmp_path, "picard.mp3", "mp3")
        lrc = "[00:01.50]Hello\n[00:03.00]Middle\n"
        tags = ID3(path)
        tags.add(TXXX(encoding=3, desc="SYNCEDLYRICS", text=lrc))
        tags.save(path)
        assert read_synced_lyrics(path) == lrc
        assert read_lyrics_tags(path).synced == lrc

    def test_write_removes_txxx_syncedlyrics(self, tmp_path) -> None:
        """Writing SYLT also cleans up the legacy TXXX frame."""
        from mutagen.id3 import ID3, TXXX

        path = _make_audio(tmp_path, "cleanup.mp3", "mp3")
        tags = ID3(path)
        tags.add(TXXX(encoding=3, desc="SYNCEDLYRICS", text="old LRC"))
        tags.save(path)
        write_synced_lyrics(path, "[00:05.00]new\n")
        tags = read_tags_raw(path)
        assert tags.getall("TXXX:SYNCEDLYRICS") == []
        assert len(tags.getall("SYLT")) == 1
        assert read_synced_lyrics(path) is not None

    def test_sylt_takes_priority_over_txxx(self, tmp_path) -> None:
        """When both frames exist, SYLT wins."""
        from mutagen.id3 import ID3, SYLT, TXXX, Encoding

        path = _make_audio(tmp_path, "both.mp3", "mp3")
        tags = ID3(path)
        tags.add(TXXX(encoding=3, desc="SYNCEDLYRICS", text="txxx LRC"))
        tags.add(
            SYLT(
                encoding=Encoding.UTF8,
                lang="XXX",
                format=2,
                type=1,
                desc="",
                text=[("sylt lyric", 1000)],
            )
        )
        tags.save(path)
        assert read_synced_lyrics(path) == "[00:01.00]sylt lyric"
        assert read_lyrics_tags(path).synced == "[00:01.00]sylt lyric"


class TestVorbisRoundTrip:
    @pytest.mark.parametrize(("ext", "fmt"), [("flac", "flac"), ("ogg", "ogg")])
    def test_write_then_read_verbatim(self, tmp_path, ext: str, fmt: str) -> None:
        path = _make_audio(tmp_path, f"track.{ext}", fmt)
        write_synced_lyrics(path, LRC_TEXT)
        assert read_synced_lyrics(path) == LRC_TEXT

    @pytest.mark.parametrize(("ext", "fmt"), [("flac", "flac"), ("ogg", "ogg")])
    def test_plain_lyrics_field_left_untouched(
        self, tmp_path, ext: str, fmt: str
    ) -> None:
        path = _make_audio(tmp_path, f"both.{ext}", fmt)
        write_synced_lyrics(path, LRC_TEXT)
        _set_raw_comment(path, "lyrics", "plain unsynced lyrics")
        assert read_synced_lyrics(path) == LRC_TEXT
        assert mutagen.File(path).tags["lyrics"] == ["plain unsynced lyrics"]

    @pytest.mark.parametrize(("ext", "fmt"), [("flac", "flac"), ("ogg", "ogg")])
    def test_read_falls_back_to_plain_lyrics(
        self, tmp_path, ext: str, fmt: str
    ) -> None:
        path = _make_audio(tmp_path, f"plain.{ext}", fmt)
        _set_raw_comment(path, "lyrics", "[00:01.00]legacy\n")
        assert read_synced_lyrics(path) == "[00:01.00]legacy\n"

    @pytest.mark.parametrize(("ext", "fmt"), [("flac", "flac"), ("ogg", "ogg")])
    def test_rewrite_overwrites_synced_field(
        self, tmp_path, ext: str, fmt: str
    ) -> None:
        path = _make_audio(tmp_path, f"rewrite.{ext}", fmt)
        write_synced_lyrics(path, "[00:01.00]first\n")
        write_synced_lyrics(path, "[00:02.00]second\n")
        assert read_synced_lyrics(path) == "[00:02.00]second\n"


class TestMp4Unsupported:
    def test_read_none_when_absent(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "track.m4a", "mp4")
        assert read_synced_lyrics(path) is None

    def test_write_raises_audio_tag_error(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "track.m4a", "mp4")
        with pytest.raises(AudioTagError, match="write_synced_lyrics"):
            write_synced_lyrics(path, "[00:01.00]x\n")


class TestPlainLyricsRoundTrip:
    @pytest.mark.parametrize(
        ("ext", "fmt"), [("mp3", "mp3"), ("flac", "flac"), ("ogg", "ogg")]
    )
    def test_write_then_read_verbatim(self, tmp_path, ext: str, fmt: str) -> None:
        path = _make_audio(tmp_path, f"plain.{ext}", fmt)
        write_plain_lyrics(path, PLAIN_TEXT)
        tags = read_lyrics_tags(path)
        assert tags.plain == PLAIN_TEXT
        assert tags.synced is None
        assert tags.has_any

    def test_m4a_write_plain_supported(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "plain.m4a", "mp4")
        write_plain_lyrics(path, PLAIN_TEXT)
        tags = read_lyrics_tags(path)
        assert tags.plain == PLAIN_TEXT
        assert tags.synced is None
        assert read_synced_lyrics(path) is None

    @pytest.mark.parametrize(
        ("ext", "fmt"), [("mp3", "mp3"), ("flac", "flac"), ("ogg", "ogg")]
    )
    def test_rewrite_replaces_previous_plain(
        self, tmp_path, ext: str, fmt: str
    ) -> None:
        path = _make_audio(tmp_path, f"overwrite.{ext}", fmt)
        write_plain_lyrics(path, "first version\n")
        write_plain_lyrics(path, PLAIN_TEXT)
        assert read_lyrics_tags(path).plain == PLAIN_TEXT

    @pytest.mark.parametrize(
        ("ext", "fmt"), [("mp3", "mp3"), ("flac", "flac"), ("ogg", "ogg")]
    )
    def test_synced_and_plain_coexist(self, tmp_path, ext: str, fmt: str) -> None:
        path = _make_audio(tmp_path, f"both.{ext}", fmt)
        write_synced_lyrics(path, "[00:01.00]synced line\n")
        write_plain_lyrics(path, PLAIN_TEXT)
        tags = read_lyrics_tags(path)
        assert (tags.synced or "").rstrip("\n") == "[00:01.00]synced line"
        assert tags.plain == PLAIN_TEXT

    @pytest.mark.parametrize(
        ("ext", "fmt"), [("mp3", "mp3"), ("flac", "flac"), ("ogg", "ogg")]
    )
    def test_synced_write_leaves_plain_untouched(
        self, tmp_path, ext: str, fmt: str
    ) -> None:
        path = _make_audio(tmp_path, f"synced_after.{ext}", fmt)
        write_plain_lyrics(path, PLAIN_TEXT)
        write_synced_lyrics(path, "[00:01.00]synced line\n")
        tags = read_lyrics_tags(path)
        assert tags.plain == PLAIN_TEXT
        assert (tags.synced or "").rstrip("\n") == "[00:01.00]synced line"

    def test_empty_file_reports_no_lyrics(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "quiet.mp3", "mp3")
        tags = read_lyrics_tags(path)
        assert not tags.has_any
        assert tags.plain is None
        assert tags.synced is None

    def test_plain_does_not_create_sylt_frame(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "uslt.mp3", "mp3")
        write_plain_lyrics(path, PLAIN_TEXT)
        tags = read_tags_raw(path)
        assert len(tags.getall("SYLT")) == 0
        uslt_frames = tags.getall("USLT")
        assert len(uslt_frames) == 1
        assert uslt_frames[0].lang == "XXX"


class TestFacades:
    def test_writer_snapshots_before_write(self, tmp_path) -> None:
        path = _make_audio(tmp_path, "snap.flac", "flac")
        with patch(
            "audio_suite_shared.tag_helper_writer.record_tag_edit_snapshot"
        ) as snapshot:
            write_synced_lyrics(path, "[00:01.00]x\n")
        snapshot.assert_called_once_with(path, "write_synced_lyrics")

    def test_reader_returns_none_on_missing_file(self, tmp_path) -> None:
        assert read_synced_lyrics(str(tmp_path / "nope.mp3")) is None
