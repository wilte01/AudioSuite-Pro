"""Tests for tag_editor.core.processor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from pydub import AudioSegment

from audio_suite_shared.batch_undo import list_recent_batches, revert_batch_by_id
from audio_suite_shared.exceptions import (
    AudioDirectoryError,
    AudioSuiteError,
    user_message_for,
)
from tag_editor.core.processor import (
    FieldEdit,
    TagEditorProcessor,
    normalize_field,
    summarize_results,
    validate_field_value,
)


def _silent(duration_ms: int = 100) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms)


@pytest.fixture
def mp3_file(tmp_path: Path) -> Path:
    path = tmp_path / "track.mp3"
    _silent().export(str(path), format="mp3")
    return path


@pytest.fixture
def flac_file(tmp_path: Path) -> Path:
    path = tmp_path / "track.flac"
    _silent().export(str(path), format="flac")
    return path


@pytest.fixture
def ogg_file(tmp_path: Path) -> Path:
    path = tmp_path / "track.ogg"
    _silent().export(str(path), format="ogg")
    return path


@pytest.fixture
def m4a_file(tmp_path: Path) -> Path:
    path = tmp_path / "track.m4a"
    _silent().export(str(path), format="mp4")
    return path


class TestFieldValidation:
    def test_normalize_field_accepts_display_spacing(self) -> None:
        assert normalize_field(" Album Artist ") == "album_artist"

    def test_normalize_field_rejects_unknown(self) -> None:
        with pytest.raises(AudioSuiteError, match="Unsupported tag field"):
            normalize_field("picture")

    def test_none_clears_field(self) -> None:
        assert validate_field_value("title", None) is None

    def test_empty_string_is_blank_not_clear(self) -> None:
        assert validate_field_value("comment", "") == ""

    def test_unicode_text_is_preserved(self) -> None:
        value = "Café — naïve & <tag>"
        assert validate_field_value("title", value) == value

    def test_multiline_comment_is_valid(self) -> None:
        value = "line one\nline two\r\nline three"
        assert validate_field_value("comment", value) == value

    def test_control_character_is_rejected(self) -> None:
        with pytest.raises(AudioSuiteError, match="control characters"):
            validate_field_value("title", "bad\x00value")

    def test_over_length_value_is_rejected(self) -> None:
        with pytest.raises(AudioSuiteError, match="4096"):
            validate_field_value("comment", "x" * 4097)

    def test_track_accepts_number_and_total(self) -> None:
        assert validate_field_value("track", "3") == "3"
        assert validate_field_value("track", "3/12") == "3/12"

    def test_track_rejects_zero(self) -> None:
        with pytest.raises(AudioSuiteError, match="Track"):
            validate_field_value("track", "0")

    def test_track_rejects_total_below_track(self) -> None:
        with pytest.raises(AudioSuiteError, match="total"):
            validate_field_value("track", "5/4")

    def test_year_accepts_year_and_iso_date(self) -> None:
        assert validate_field_value("year", "1999") == "1999"
        assert validate_field_value("year", "1999-06-15") == "1999-06-15"

    def test_year_rejects_partial_date(self) -> None:
        with pytest.raises(AudioSuiteError, match="Year"):
            validate_field_value("year", "199")


class TestScanDirectory:
    def test_rejects_missing_directory(self, tmp_path: Path) -> None:
        with pytest.raises(AudioDirectoryError):
            TagEditorProcessor().scan_directory(tmp_path / "missing")

    def test_loads_supported_files_recursively(self, tmp_path: Path) -> None:
        subdirectory = tmp_path / "artist"
        subdirectory.mkdir()
        (subdirectory / "a.mp3").touch()
        (subdirectory / "b.flac").touch()
        (tmp_path / "notes.txt").touch()

        with patch(
            "tag_editor.core.processor.read_editable_tags",
            return_value={field: None for field in ("title", "artist")},
        ) as reader:
            rows = TagEditorProcessor().scan_directory(tmp_path)

        assert reader.call_count == 2
        assert [row.path.name for row in rows] == ["a.mp3", "b.flac"]

    def test_read_error_becomes_row_error(self, tmp_path: Path) -> None:
        (tmp_path / "broken.mp3").touch()
        with patch(
            "tag_editor.core.processor.read_editable_tags",
            side_effect=AudioSuiteError("cannot read"),
        ):
            rows = TagEditorProcessor().scan_directory(tmp_path)
        assert rows[0].error is not None

    def test_progress_callback_receives_loaded_count(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        (tmp_path / "b.flac").touch()
        callback = MagicMock()
        with patch("tag_editor.core.processor.read_editable_tags", return_value={}):
            TagEditorProcessor().scan_directory(tmp_path, progress_callback=callback)
        assert callback.call_args_list[0].args == ("a.mp3", 1)
        assert callback.call_args_list[1].args == ("b.flac", 2)


class TestApplyEdits:
    def test_dry_run_compares_without_writing(self, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        with (
            patch(
                "tag_editor.core.processor.read_editable_tags",
                return_value={"title": "Old"},
            ),
            patch("tag_editor.core.processor.write_editable_tag") as writer,
        ):
            results = TagEditorProcessor().apply_edits(
                [FieldEdit(path, "title", "New")], dry_run=True
            )
        writer.assert_not_called()
        assert results[0].changed is True
        assert results[0].written is False
        assert summarize_results(results).changed == 1

    def test_live_write_uses_shared_writer(self, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        with (
            patch(
                "tag_editor.core.processor.read_editable_tags",
                return_value={"title": "Old"},
            ),
            patch("tag_editor.core.processor.write_editable_tag") as writer,
        ):
            results = TagEditorProcessor().apply_edits(
                [FieldEdit(path, "title", "New")]
            )
        writer.assert_called_once_with(str(path), "title", "New")
        assert results[0].written is True

    def test_unchanged_value_is_not_written(self, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        with (
            patch(
                "tag_editor.core.processor.read_editable_tags",
                return_value={"title": "Same"},
            ),
            patch("tag_editor.core.processor.write_editable_tag") as writer,
        ):
            results = TagEditorProcessor().apply_edits(
                [FieldEdit(path, "title", "Same")]
            )
        writer.assert_not_called()
        assert results[0].changed is False

    def test_invalid_value_raises_before_writes(self, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        with patch("tag_editor.core.processor.write_editable_tag") as writer:
            with pytest.raises(AudioSuiteError, match="Year"):
                TagEditorProcessor().apply_edits([FieldEdit(path, "year", "20")])
        writer.assert_not_called()

    def test_writer_failure_is_reported_per_file(self, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        with (
            patch(
                "tag_editor.core.processor.read_editable_tags",
                return_value={"title": "Old"},
            ),
            patch(
                "tag_editor.core.processor.write_editable_tag",
                side_effect=AudioSuiteError("write refused"),
            ),
        ):
            results = TagEditorProcessor().apply_edits(
                [FieldEdit(path, "title", "New")]
            )
        assert results[0].error == user_message_for(AudioSuiteError("write refused"))
        assert results[0].written is False


class TestRealAudioRoundTrip:
    pytestmark = pytest.mark.integration

    def _latest_tag_editor_batch(self) -> str:
        batches = list_recent_batches(limit=20)
        return next(
            batch.batch_id
            for batch in batches
            if batch.tool_name == "tag_editor" and batch.record_count > 0
        )

    def test_mp3_title_round_trip_and_undo(self, mp3_file: Path) -> None:
        results = TagEditorProcessor().apply_edits(
            [FieldEdit(mp3_file, "title", "New Title")]
        )
        assert results[0].written is True
        audio = MP3(str(mp3_file))
        assert str(audio.tags["TIT2"].text[0]) == "New Title"

        revert_batch_by_id(self._latest_tag_editor_batch())
        restored = MP3(str(mp3_file))
        assert restored.tags is None or restored.tags.get("TIT2") is None

    def test_flac_comment_write_and_clear(self, flac_file: Path) -> None:
        TagEditorProcessor().apply_edits(
            [FieldEdit(flac_file, "comment", "First comment")]
        )
        assert FLAC(str(flac_file))["comment"][0] == "First comment"

        TagEditorProcessor().apply_edits([FieldEdit(flac_file, "comment", None)])
        assert "comment" not in FLAC(str(flac_file))

    def test_ogg_track_and_year_round_trip(self, ogg_file: Path) -> None:
        TagEditorProcessor().apply_edits(
            [
                FieldEdit(ogg_file, "track", "7/12"),
                FieldEdit(ogg_file, "year", "1984"),
            ]
        )
        audio = OggVorbis(str(ogg_file))
        assert audio["tracknumber"][0] == "7/12"
        assert audio["date"][0] == "1984"

    def test_mp4_track_tuple_round_trip(self, m4a_file: Path) -> None:
        TagEditorProcessor().apply_edits([FieldEdit(m4a_file, "track", "3/12")])
        audio = MP4(str(m4a_file))
        assert audio.tags["trkn"] == [(3, 12)]

    def test_dry_run_leaves_real_file_untouched(self, mp3_file: Path) -> None:
        results = TagEditorProcessor().apply_edits(
            [FieldEdit(mp3_file, "title", "Preview Only")], dry_run=True
        )
        assert results[0].changed is True
        assert MP3(str(mp3_file)).tags is None or "TIT2" not in MP3(str(mp3_file)).tags

    def test_tagless_mp3_undo_removes_created_tags(self, mp3_file: Path) -> None:
        MP3(str(mp3_file)).delete()
        TagEditorProcessor().apply_edits([FieldEdit(mp3_file, "artist", "Undo Me")])
        assert str(MP3(str(mp3_file)).tags["TPE1"].text[0]) == "Undo Me"

        revert_batch_by_id(self._latest_tag_editor_batch())
        assert MP3(str(mp3_file)).tags is None

    def test_tagless_flac_undo_removes_created_comments(self, flac_file: Path) -> None:
        FLAC(str(flac_file)).delete()
        TagEditorProcessor().apply_edits([FieldEdit(flac_file, "album", "Undo Album")])
        assert FLAC(str(flac_file))["album"][0] == "Undo Album"

        revert_batch_by_id(self._latest_tag_editor_batch())
        assert FLAC(str(flac_file)).tags is None
