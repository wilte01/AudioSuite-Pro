"""Tests for the filename writer (F-01) — outcomes measured on disk.

A dry run is checked by **bytes and mtime**, not by "the write function was not
called": a snapshot or a save that slipped through would change one of them.
A live run is checked by re-reading the tag through a *fresh* handler, so the
value asserted is the one a later tool will see.

Changed in 2.2.0: new — F-01.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TCON, TIT2, TPE1
from pydub import AudioSegment

from audio_suite_shared.tag_helper import read_editable_tags
from tag_field_updater.core.filename_tags import apply_filename_fields


def digest(path: Path) -> str:
    """SHA-256 of the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def tagged_song(tmp_path: Path) -> Path:
    """A real MP3 carrying an existing title and genre, and no album."""
    path = tmp_path / "Artist - Title.mp3"
    try:
        AudioSegment.silent(duration=50).export(str(path), format="mp3")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode MP3 ({type(exc).__name__})")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Existing Title"]))
    tags.add(TCON(encoding=3, text=["Rock/Pop"]))
    tags.add(TPE1(encoding=3, text=["Existing Artist"]))
    tags.save(str(path))
    return path


class TestDryRunWritesNothing:
    def test_bytes_and_mtime_are_untouched(self, tagged_song: Path) -> None:
        before_digest = digest(tagged_song)
        before_mtime = tagged_song.stat().st_mtime_ns

        outcome = apply_filename_fields(
            tagged_song,
            {"artist": "Parsed Artist", "title": "Parsed Title", "album": "Parsed"},
            only_fill_blanks=False,
            dry_run=True,
        )

        assert outcome.updated is True
        assert outcome.written == ("artist", "title", "album")
        assert digest(tagged_song) == before_digest
        assert tagged_song.stat().st_mtime_ns == before_mtime
        stored = read_editable_tags(str(tagged_song))
        assert stored["artist"] == "Existing Artist"
        assert stored["album"] is None

    def test_the_live_run_then_does_write(self, tagged_song: Path) -> None:
        """The contrast half: the same call without the flag changes the file."""
        before = digest(tagged_song)

        apply_filename_fields(
            tagged_song,
            {"artist": "Parsed Artist", "title": "Parsed Title", "album": "Parsed"},
            only_fill_blanks=False,
        )

        assert digest(tagged_song) != before
        stored = read_editable_tags(str(tagged_song))
        assert stored["artist"] == "Parsed Artist"
        assert stored["title"] == "Parsed Title"
        assert stored["album"] == "Parsed"


class TestOnlyFillBlanks:
    def test_an_existing_value_is_kept_by_default(self, tagged_song: Path) -> None:
        outcome = apply_filename_fields(
            tagged_song,
            {"artist": "Parsed Artist", "album": "Parsed Album"},
        )

        assert outcome.skipped_existing == ("artist",)
        assert outcome.written == ("album",)
        stored = read_editable_tags(str(tagged_song))
        assert stored["artist"] == "Existing Artist"
        assert stored["album"] == "Parsed Album"

    def test_overwrite_replaces_it_when_asked(self, tagged_song: Path) -> None:
        outcome = apply_filename_fields(
            tagged_song,
            {"artist": "Parsed Artist"},
            only_fill_blanks=False,
        )

        assert outcome.skipped_existing == ()
        assert outcome.written == ("artist",)
        assert read_editable_tags(str(tagged_song))["artist"] == "Parsed Artist"

    def test_an_identical_value_is_not_rewritten(self, tagged_song: Path) -> None:
        before = digest(tagged_song)

        outcome = apply_filename_fields(
            tagged_song,
            {"artist": "Existing Artist"},
            only_fill_blanks=False,
        )

        assert outcome.updated is False
        assert outcome.unchanged == ("artist",)
        assert digest(tagged_song) == before


class TestTransformations:
    def test_a_genre_list_is_normalised(self, tagged_song: Path) -> None:
        apply_filename_fields(
            tagged_song, {"genre": "Rock/Pop"}, only_fill_blanks=False
        )
        assert read_editable_tags(str(tagged_song))["genre"] == "Rock; Pop"

    def test_an_artist_name_is_not_slash_rewritten(self, tagged_song: Path) -> None:
        """``AC/DC`` must not become ``AC; DC``: the rule exists for genre lists."""
        apply_filename_fields(tagged_song, {"artist": "AC/DC"}, only_fill_blanks=False)
        assert read_editable_tags(str(tagged_song))["artist"] == "AC/DC"


class TestFieldGuard:
    def test_a_field_the_tag_layer_cannot_write_is_refused(
        self, tagged_song: Path
    ) -> None:
        with pytest.raises(ValueError, match="cannot write field"):
            apply_filename_fields(tagged_song, {"mood_confidence": "0.9"})

    def test_a_blank_parsed_value_changes_nothing(self, tagged_song: Path) -> None:
        outcome = apply_filename_fields(tagged_song, {"album": "   "})
        assert outcome.updated is False
