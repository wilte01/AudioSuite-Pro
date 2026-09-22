"""
Tests for album_genre_tagger.core.tag_reader and album_genre_tagger.core.tag_writer
Gap G-11: read_titlegenre(), write_album_genre()
"""

import pytest
from mutagen.id3 import ID3, TXXX
from mutagen.mp3 import MP3

from album_genre_tagger.core.tag_reader import read_titlegenre
from album_genre_tagger.core.tag_writer import write_album_genre

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_mp3(tmp_path, filename="track.mp3", txxx_tags: dict = None) -> str:
    """Create a real MP3 (via pydub) with optional TXXX tags."""
    from pydub import AudioSegment

    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    audio = MP3(str(path), ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    for desc, value in (txxx_tags or {}).items():
        audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    audio.save()
    return str(path)


@pytest.fixture
def mp3_with_titlegenre(tmp_path):
    return _make_mp3(tmp_path, txxx_tags={"TITLEGENRE": "Rock"})


@pytest.fixture
def mp3_without_titlegenre(tmp_path):
    return _make_mp3(tmp_path)


# ── read_titlegenre ───────────────────────────────────────────────────────────


class TestReadTitlegenre:
    def test_returns_genre_when_present(self, mp3_with_titlegenre):
        genre, err = read_titlegenre(mp3_with_titlegenre)
        assert genre == "Rock"
        assert err is None

    def test_returns_none_and_message_when_absent(self, mp3_without_titlegenre):
        genre, err = read_titlegenre(mp3_without_titlegenre)
        assert genre is None
        assert err is not None
        assert "TITLEGENRE" in err

    def test_returns_tuple(self, mp3_with_titlegenre):
        result = read_titlegenre(mp3_with_titlegenre)
        assert isinstance(result, tuple) and len(result) == 2

    def test_nonexistent_file_returns_error(self, tmp_path):
        genre, err = read_titlegenre(str(tmp_path / "ghost.mp3"))
        assert genre is None
        assert err is not None

    def test_no_id3_tags_returns_error(self):
        """When the handler reports no raw ID3 tags, an explicit error is returned.
        Uses a mocked handler so no real audio file is required."""
        from unittest.mock import MagicMock, patch

        handler = MagicMock()
        handler.get_raw_tags.return_value = None
        with patch(
            "album_genre_tagger.core.tag_reader.TagHandlerFactory.get_handler",
            return_value=handler,
        ):
            genre, err = read_titlegenre("any.mp3")
        assert genre is None
        assert err == "No tags"

    def test_case_insensitive_tag_lookup(self, tmp_path):
        """read_titlegenre uses .upper() comparison — case-insensitive match."""
        path = _make_mp3(tmp_path, txxx_tags={"titlegenre": "Jazz"})
        genre, err = read_titlegenre(path)
        assert genre == "Jazz"
        assert err is None

    def test_multi_value_txxx_returns_first(self, tmp_path):
        """When TXXX has multiple text values, read_titlegenre returns the first."""
        from pydub import AudioSegment

        path = tmp_path / "multi.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        audio = MP3(str(path), ID3=ID3)
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TXXX(encoding=3, desc="TITLEGENRE", text=["Jazz", "Blues"]))
        audio.save()
        genre, err = read_titlegenre(str(path))
        assert genre == "Jazz"
        assert err is None

    def test_ignores_other_txxx_tags(self, tmp_path):
        path = _make_mp3(
            tmp_path, txxx_tags={"ALBUMGENRE": "Classical", "MOOD": "Calm"}
        )
        genre, err = read_titlegenre(path)
        assert genre is None
        assert err is not None

    def test_titlegenre_whitespace_not_stripped(self, tmp_path):
        """read_titlegenre performs no normalization — stray whitespace from
        third-party taggers is passed through verbatim. This matters because
        consolidator.py deduplicates via a plain set(), so " Rock" and "Rock"
        will NOT be merged into one genre. Documented here as current,
        unconfirmed-as-intentional behavior (see test_consolidator.py::
        TestGenreValueNormalization)."""
        path = _make_mp3(tmp_path, txxx_tags={"TITLEGENRE": " Rock "})
        genre, err = read_titlegenre(path)
        assert genre == " Rock "
        assert err is None

    def test_file_with_no_tags_returns_error(self, tmp_path):
        # Write a file with no ID3 tags at all
        path = tmp_path / "notagfile.mp3"
        path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 413)
        genre, err = read_titlegenre(str(path))
        assert genre is None
        assert err is not None


# ── write_album_genre ─────────────────────────────────────────────────────────


class TestWriteAlbumGenre:
    def test_dry_run_returns_true_and_no_changes_made(self, mp3_without_titlegenre):
        ok, msg = write_album_genre(
            mp3_without_titlegenre, "Rock; Jazz", is_dry_run=True
        )
        assert ok is True
        assert "dry" in msg.lower() or "no changes" in msg.lower()
        # Verify nothing was written
        audio = MP3(mp3_without_titlegenre, ID3=ID3)
        txxx_frames = [f for f in (audio.tags or {}).values() if isinstance(f, TXXX)]
        assert not any(f.desc == "ALBUMGENRE" for f in txxx_frames)

    def test_live_run_writes_albumgenre_tag(self, mp3_without_titlegenre):
        ok, msg = write_album_genre(
            mp3_without_titlegenre, "Classical; Jazz", is_dry_run=False
        )
        assert ok is True
        audio = MP3(mp3_without_titlegenre, ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMGENRE")
        assert frame is not None
        assert frame.text[0] == "Classical; Jazz"

    def test_live_run_writes_albumderived_tag(self, mp3_without_titlegenre):
        write_album_genre(mp3_without_titlegenre, "Rock", is_dry_run=False)
        audio = MP3(mp3_without_titlegenre, ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMDERIVED")
        assert frame is not None
        assert frame.text[0] == "Y"

    def test_overwrites_existing_albumgenre(self, tmp_path):
        path = _make_mp3(tmp_path, txxx_tags={"ALBUMGENRE": "Old Genre"})
        write_album_genre(path, "New Genre", is_dry_run=False)
        audio = MP3(path, ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMGENRE")
        assert frame.text[0] == "New Genre"

    def test_overwrites_existing_albumderived(self, tmp_path):
        path = _make_mp3(tmp_path, txxx_tags={"ALBUMDERIVED": "N"})
        write_album_genre(path, "Jazz", is_dry_run=False)
        audio = MP3(path, ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMDERIVED")
        assert frame.text[0] == "Y"

    def test_returns_tuple(self, mp3_without_titlegenre):
        result = write_album_genre(mp3_without_titlegenre, "Pop", is_dry_run=True)
        assert isinstance(result, tuple) and len(result) == 2

    def test_live_run_returns_updated_message(self, mp3_without_titlegenre):
        ok, msg = write_album_genre(mp3_without_titlegenre, "Pop", is_dry_run=False)
        assert ok is True
        assert "Updated" in msg or "updated" in msg.lower()

    def test_nonexistent_file_returns_false(self, tmp_path):
        ok, msg = write_album_genre(
            str(tmp_path / "ghost.mp3"), "Rock", is_dry_run=False
        )
        assert ok is False
        assert msg  # error message populated

    def test_semicolon_delimited_genre_preserved(self, mp3_without_titlegenre):
        genre_str = "Rock; Alternative; Indie"
        write_album_genre(mp3_without_titlegenre, genre_str, is_dry_run=False)
        audio = MP3(mp3_without_titlegenre, ID3=ID3)
        frame = audio.tags.get("TXXX:ALBUMGENRE")
        assert frame.text[0] == genre_str

    def test_empty_genre_string_written_as_is(self, mp3_without_titlegenre):
        # Edge case: write an empty genre string
        ok, msg = write_album_genre(mp3_without_titlegenre, "", is_dry_run=False)
        assert ok is True
