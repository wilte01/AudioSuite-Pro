"""Tests for tag_editor.core.csv_io."""

from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from pydub import AudioSegment

from audio_suite_shared.batch_undo import list_recent_batches, revert_batch_by_id
from audio_suite_shared.exceptions import AudioDirectoryError, AudioSuiteError
from tag_editor.core.csv_io import (
    EXPORT_FIELDNAMES,
    build_import_plan,
    export_csv,
)
from tag_editor.core.processor import FieldEdit, TagEditorProcessor, TagRow


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class TestBuildImportPlan:
    def test_rejects_missing_root(self, tmp_path: Path) -> None:
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [])
        with pytest.raises(AudioDirectoryError):
            build_import_plan(csv_path, tmp_path / "missing")

    def test_requires_file_column(self, tmp_path: Path) -> None:
        csv_path = _write_csv(tmp_path / "e.csv", ["title"], [["New"]])
        with pytest.raises(AudioSuiteError, match="file column"):
            build_import_plan(csv_path, tmp_path)

    @pytest.mark.parametrize("column", ["file", "filename", "path", "File"])
    def test_file_column_aliases(self, tmp_path: Path, column: str) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(tmp_path / "e.csv", [column, "title"], [["a.mp3", "New"]])
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "title", "New")]

    def test_requires_editable_column(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "notes"], [["a.mp3", "x"]])
        with pytest.raises(AudioSuiteError, match="no editable tag columns"):
            build_import_plan(csv_path, tmp_path)

    def test_unknown_columns_are_reported_not_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title", "cover"],
            [["a.mp3", "New", "front.jpg"]],
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "title", "New")]
        assert plan.ignored_columns == ["cover"]

    def test_display_label_header_maps_to_field(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "Album Artist"], [["a.mp3", "Various"]]
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "album_artist", "Various")]

    def test_empty_cells_leave_field_unchanged(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title", "artist"],
            [["a.mp3", "New", ""]],
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "title", "New")]

    def test_relative_path_resolves_against_root(self, tmp_path: Path) -> None:
        subdirectory = tmp_path / "artist"
        subdirectory.mkdir()
        (subdirectory / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [["artist/a.mp3", "New"]]
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(subdirectory / "a.mp3", "title", "New")]

    def test_absolute_path_is_used_directly(self, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere" / "a.mp3"
        target.parent.mkdir()
        target.touch()
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [[str(target), "New"]]
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(target, "title", "New")]

    def test_missing_file_value_is_row_error(self, tmp_path: Path) -> None:
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [["", "New"]])
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == []
        assert plan.row_errors == ["Row 2: missing 'file' value."]

    def test_unsupported_extension_is_row_error(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").touch()
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [["a.txt", "New"]])
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == []
        assert "unsupported audio type" in plan.row_errors[0]

    def test_missing_file_is_row_error(self, tmp_path: Path) -> None:
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [["gone.mp3", "New"]]
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == []
        assert "file not found" in plan.row_errors[0]

    def test_invalid_value_is_row_error_not_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "track", "title"],
            [["a.mp3", "0", "New"]],
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "title", "New")]
        assert "Track" in plan.row_errors[0]

    def test_row_count_excludes_header(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["a.mp3", "One"], ["a.mp3", "Two"]],
        )
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.row_count == 2

    def test_utf8_bom_header_is_tolerated(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = tmp_path / "e.csv"
        csv_path.write_text("file,title\na.mp3,New\n", encoding="utf-8-sig", newline="")
        plan = build_import_plan(csv_path, tmp_path)
        assert plan.edits == [FieldEdit(tmp_path / "a.mp3", "title", "New")]

    def test_unreadable_csv_raises_audio_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "gone.csv"
        with pytest.raises(AudioSuiteError):
            build_import_plan(missing, tmp_path)


class TestPathContainment:
    """File values must resolve inside the library root.

    A raw ``root / "../.."`` is still reported as relative to *root*, so a
    containment check that skips normalisation passes traversal; these tests
    pin the normalised behaviour.
    """

    @staticmethod
    def _library(tmp_path: Path) -> tuple[Path, Path]:
        root = tmp_path / "lib"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.mp3").touch()
        (root / "track.mp3").touch()
        return root, outside

    def test_parent_traversal_is_rejected(self, tmp_path: Path) -> None:
        root, outside = self._library(tmp_path)
        assert (root / Path("../outside/secret.mp3")).is_relative_to(root)
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["../outside/secret.mp3", "Pwned"]],
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == []
        assert plan.row_errors == [
            "Row 2: outside the library folder: ../outside/secret.mp3"
        ]

    def test_deep_traversal_is_rejected(self, tmp_path: Path) -> None:
        root, _ = self._library(tmp_path)
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["../../../../Windows/System32/drivers/etc/hosts.mp3", "Pwned"]],
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == []
        assert "outside the library folder" in plan.row_errors[0]

    def test_absolute_path_outside_root_is_rejected(self, tmp_path: Path) -> None:
        root, outside = self._library(tmp_path)
        target = outside / "secret.mp3"
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [[str(target), "Pwned"]]
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == []
        assert plan.row_errors == [f"Row 2: outside the library folder: {target}"]

    def test_absolute_path_inside_root_is_accepted(self, tmp_path: Path) -> None:
        root, _ = self._library(tmp_path)
        target = root / "track.mp3"
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [[str(target), "New"]]
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == [FieldEdit(target, "title", "New")]
        assert plan.row_errors == []

    def test_inner_dot_dot_is_accepted(self, tmp_path: Path) -> None:
        root, _ = self._library(tmp_path)
        nested = root / "artist" / "album"
        nested.mkdir(parents=True)
        (nested / "b.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["artist/album/../album/b.mp3", "New"]],
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == [FieldEdit(nested / "b.mp3", "title", "New")]
        assert plan.row_errors == []

    def test_rejected_row_does_not_abort_the_import(self, tmp_path: Path) -> None:
        root, outside = self._library(tmp_path)
        target = root / "track.mp3"
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [
                [str(target), "Keep"],
                ["../outside/secret.mp3", "Pwned"],
            ],
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == [FieldEdit(target, "title", "Keep")]
        assert len(plan.row_errors) == 1
        assert plan.row_count == 2

    @pytest.mark.skipif(os.name != "nt", reason="Windows drive-relative paths")
    def test_drive_relative_value_is_rejected(self, tmp_path: Path) -> None:
        root, _ = self._library(tmp_path)
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [["C:elsewhere/x.mp3", "Pwned"]]
        )
        plan = build_import_plan(csv_path, root)
        assert plan.edits == []
        assert "outside the library folder" in plan.row_errors[0]

    def test_root_with_trailing_separator_still_contains(self, tmp_path: Path) -> None:
        root, _ = self._library(tmp_path)
        target = root / "track.mp3"
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["track.mp3", "New"], [str(target), "New"]],
        )
        plan = build_import_plan(csv_path, f"{root}{os.sep}")
        assert plan.edits == [
            FieldEdit(target, "title", "New"),
            FieldEdit(target, "title", "New"),
        ]
        assert plan.row_errors == []


class TestExportCsv:
    def test_writes_header_and_rows(self, tmp_path: Path) -> None:
        rows = [
            TagRow(tmp_path / "a.mp3", {"title": "One", "artist": None}),
            TagRow(tmp_path / "b.flac", {"title": None, "artist": "Two"}),
        ]
        target = tmp_path / "out.csv"
        assert export_csv(rows, target, tmp_path) == 2

        with open(target, newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        assert list(records[0]) == list(EXPORT_FIELDNAMES)
        assert records[0]["file"] == "a.mp3"
        assert records[0]["title"] == "One"
        assert records[0]["artist"] == ""
        assert records[1]["file"] == "b.flac"

    def test_paths_relative_to_root_when_inside(self, tmp_path: Path) -> None:
        subdirectory = tmp_path / "artist"
        subdirectory.mkdir()
        target = tmp_path / "out.csv"
        export_csv([TagRow(subdirectory / "a.mp3", {})], target, tmp_path)
        with open(target, newline="", encoding="utf-8") as handle:
            record = next(csv.DictReader(handle))
        assert record["file"] == "artist/a.mp3"

    def test_paths_absolute_when_outside_root(self, tmp_path: Path) -> None:
        row = TagRow(tmp_path / "elsewhere" / "a.mp3", {})
        target = tmp_path / "out.csv"
        export_csv([row], target, tmp_path / "other")
        with open(target, newline="", encoding="utf-8") as handle:
            record = next(csv.DictReader(handle))
        assert record["file"] == str(row.path)

    def test_error_rows_are_skipped(self, tmp_path: Path) -> None:
        rows = [
            TagRow(tmp_path / "ok.mp3", {"title": "One"}),
            TagRow(tmp_path / "bad.mp3", {}, error="unreadable"),
        ]
        target = tmp_path / "out.csv"
        assert export_csv(rows, target, tmp_path) == 1
        with open(target, newline="", encoding="utf-8") as handle:
            records = list(csv.DictReader(handle))
        assert [record["file"] for record in records] == ["ok.mp3"]

    def test_unwritable_destination_raises_audio_error(self, tmp_path: Path) -> None:
        with pytest.raises(AudioSuiteError):
            export_csv([], tmp_path / "missing-dir" / "out.csv")


class TestCsvRoundTrip:
    def test_export_then_import_preserves_empty_and_unchanged_values(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "a.mp3").touch()
        (tmp_path / "b.flac").touch()
        rows = [
            TagRow(tmp_path / "a.mp3", {"title": "One", "artist": ""}),
            TagRow(tmp_path / "b.flac", {"title": None, "artist": "Two"}),
        ]
        target = export_csv(rows, tmp_path / "out.csv", tmp_path)
        assert target == 2
        plan = build_import_plan(tmp_path / "out.csv", tmp_path)
        assert plan.row_errors == []
        assert plan.edits == [
            FieldEdit(tmp_path / "a.mp3", "title", "One"),
            FieldEdit(tmp_path / "b.flac", "artist", "Two"),
        ]


class TestRealAudioCsvRoundTrip:
    pytestmark = pytest.mark.integration

    def _latest_tag_editor_batch(self) -> str:
        batches = list_recent_batches(limit=20)
        return next(
            batch.batch_id
            for batch in batches
            if batch.tool_name == "tag_editor" and batch.record_count > 0
        )

    def _library(self, tmp_path: Path) -> tuple[Path, Path]:
        AudioSegment.silent(duration=100).export(str(tmp_path / "a.mp3"), format="mp3")
        AudioSegment.silent(duration=100).export(
            str(tmp_path / "b.flac"), format="flac"
        )
        return tmp_path / "a.mp3", tmp_path / "b.flac"

    def test_imported_csv_writes_mp3_and_flac(self, tmp_path: Path) -> None:
        mp3_path, flac_path = self._library(tmp_path)
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title", "genre"],
            [
                ["a.mp3", "CSV Title", "Rock"],
                ["b.flac", "FLAC Title", "Jazz"],
            ],
        )
        plan = build_import_plan(csv_path, tmp_path)
        results = TagEditorProcessor().apply_edits(plan.edits)

        assert len(results) == 4
        assert all(result.written for result in results)
        assert str(MP3(str(mp3_path)).tags["TIT2"].text[0]) == "CSV Title"
        assert str(MP3(str(mp3_path)).tags["TCON"].text[0]) == "Rock"
        assert FLAC(str(flac_path))["title"][0] == "FLAC Title"
        assert FLAC(str(flac_path))["genre"][0] == "Jazz"

        revert_batch_by_id(self._latest_tag_editor_batch())
        assert MP3(str(mp3_path)).tags is None or "TIT2" not in MP3(str(mp3_path)).tags
        assert "title" not in FLAC(str(flac_path))

    def test_export_of_real_files_round_trips_without_writing(
        self, tmp_path: Path
    ) -> None:
        mp3_path, _flac_path = self._library(tmp_path)
        processor = TagEditorProcessor()
        processor.apply_edits(
            [
                FieldEdit(mp3_path, "title", "Exported"),
                FieldEdit(mp3_path, "album", "Exported Album"),
            ]
        )
        rows = [processor.refresh_file(mp3_path)]
        export_csv(rows, tmp_path / "out.csv", tmp_path)

        plan = build_import_plan(tmp_path / "out.csv", tmp_path)
        results = processor.apply_edits(plan.edits)

        assert all(result.changed is False for result in results)
        assert all(result.written is False for result in results)
        assert str(MP3(str(mp3_path)).tags["TIT2"].text[0]) == "Exported"

    def test_dry_run_import_leaves_files_untouched(self, tmp_path: Path) -> None:
        mp3_path, _flac_path = self._library(tmp_path)
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [["a.mp3", "Preview"]]
        )
        plan = build_import_plan(csv_path, tmp_path)
        results = TagEditorProcessor().apply_edits(plan.edits, dry_run=True)

        assert results[0].changed is True
        assert results[0].written is False
        assert MP3(str(mp3_path)).tags is None or "TIT2" not in MP3(str(mp3_path)).tags
