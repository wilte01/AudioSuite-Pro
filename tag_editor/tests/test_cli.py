"""Tests for tag_editor.cli."""

from __future__ import annotations

import csv
import json as json_mod
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from pydub import AudioSegment

from tag_editor.cli import tag_edit_cli
from tag_editor.core.processor import EditResult


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _result(error: str | None = None) -> EditResult:
    return EditResult(
        path=Path("/music/track.mp3"),
        field="title",
        old_value="Old",
        new_value="New",
        changed=error is None,
        written=error is None,
        error=error,
    )


class TestTagEditCli:
    def test_value_or_clear_is_required(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        result = runner.invoke(tag_edit_cli, [str(path), "--field", "title"])
        assert result.exit_code == 2
        assert "--value is required" in result.output

    def test_json_output(self, runner: CliRunner, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        with patch(
            "tag_editor.cli.TagEditorProcessor.apply_edits",
            return_value=[_result()],
        ) as apply_edits:
            result = runner.invoke(
                tag_edit_cli,
                [str(path), "--field", "title", "--value", "New", "--json"],
            )
        assert result.exit_code == 0
        payload = json_mod.loads(result.output)
        assert payload["changed"] is True
        assert payload["written"] is True
        assert apply_edits.call_args.kwargs["dry_run"] is False

    def test_dry_run_flag_reaches_processor(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        with patch(
            "tag_editor.cli.TagEditorProcessor.apply_edits",
            return_value=[
                EditResult(
                    path=path,
                    field="title",
                    old_value="Old",
                    new_value="New",
                    changed=True,
                    written=False,
                )
            ],
        ) as apply_edits:
            result = runner.invoke(
                tag_edit_cli,
                [str(path), "--field", "title", "--value", "New", "--dry"],
            )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert apply_edits.call_args.kwargs["dry_run"] is True

    def test_write_error_exits_nonzero(self, runner: CliRunner, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        with patch(
            "tag_editor.cli.TagEditorProcessor.apply_edits",
            return_value=[_result(error="write refused")],
        ):
            result = runner.invoke(
                tag_edit_cli,
                [str(path), "--field", "title", "--value", "New"],
            )
        assert result.exit_code == 1
        assert "write refused" in result.output

    def test_directory_path_without_csv_is_usage_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            tag_edit_cli, [str(tmp_path), "--field", "title", "--value", "New"]
        )
        assert result.exit_code == 2
        assert "--csv" in result.output

    def test_missing_field_is_usage_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        result = runner.invoke(tag_edit_cli, [str(path), "--value", "New"])
        assert result.exit_code == 2
        assert "--field is required" in result.output


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class TestTagEditCliCsvImport:
    def test_csv_import_applies_edits(self, runner: CliRunner, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [["a.mp3", "New"]])
        with patch(
            "tag_editor.cli.TagEditorProcessor.apply_edits",
            return_value=[_result()],
        ) as apply_edits:
            result = runner.invoke(
                tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--json"]
            )
        assert result.exit_code == 0
        payload = json_mod.loads(result.output)
        assert payload["rows_read"] == 1
        assert payload["edits_planned"] == 1
        edit = apply_edits.call_args.args[0][0]
        assert edit.path == tmp_path / "a.mp3"
        assert edit.field == "title"
        assert edit.value == "New"

    def test_csv_import_dry_run_reaches_processor(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [["a.mp3", "New"]])
        with patch(
            "tag_editor.cli.TagEditorProcessor.apply_edits",
            return_value=[
                EditResult(
                    path=tmp_path / "a.mp3",
                    field="title",
                    old_value="Old",
                    new_value="New",
                    changed=True,
                    written=False,
                )
            ],
        ) as apply_edits:
            result = runner.invoke(
                tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--dry"]
            )
        assert result.exit_code == 0
        assert "Dry run" in result.output
        assert apply_edits.call_args.kwargs["dry_run"] is True

    def test_csv_import_reports_row_errors(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        (tmp_path / "a.mp3").touch()
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "title"],
            [["gone.mp3", "New"]],
        )
        result = runner.invoke(
            tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--json"]
        )
        assert result.exit_code == 1
        payload = json_mod.loads(result.output)
        assert payload["row_errors"]

    def test_csv_with_file_path_is_usage_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "track.mp3"
        path.touch()
        csv_path = _write_csv(path, ["file", "title"], [])
        result = runner.invoke(tag_edit_cli, [str(path), "--csv", str(csv_path)])
        assert result.exit_code == 2
        assert "library directory" in result.output

    def test_csv_cannot_be_combined_with_field(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(tmp_path / "e.csv", ["file", "title"], [])
        result = runner.invoke(
            tag_edit_cli,
            [
                str(tmp_path),
                "--csv",
                str(csv_path),
                "--field",
                "title",
                "--value",
                "New",
            ],
        )
        assert result.exit_code == 2
        assert "cannot be combined" in result.output

    def test_csv_without_file_column_reports_error(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        csv_path = _write_csv(tmp_path / "e.csv", ["title"], [["New"]])
        result = runner.invoke(
            tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--json"]
        )
        assert result.exit_code == 1
        assert "file column" in json_mod.loads(result.output)["error"]


class TestTagEditCliCsvRealAudio:
    pytestmark = pytest.mark.integration

    def test_csv_import_writes_tags(self, runner: CliRunner, tmp_path: Path) -> None:
        AudioSegment.silent(duration=100).export(str(tmp_path / "a.mp3"), format="mp3")
        AudioSegment.silent(duration=100).export(
            str(tmp_path / "b.flac"), format="flac"
        )
        csv_path = _write_csv(
            tmp_path / "e.csv",
            ["file", "Title", "Album Artist"],
            [
                ["a.mp3", "CLI CSV Title", "Various"],
                ["b.flac", "FLAC CSV Title", "Various"],
            ],
        )
        result = runner.invoke(
            tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--json"]
        )
        assert result.exit_code == 0
        assert str(MP3(str(tmp_path / "a.mp3")).tags["TIT2"].text[0]) == (
            "CLI CSV Title"
        )
        assert FLAC(str(tmp_path / "b.flac"))["albumartist"][0] == "Various"

    def test_csv_dry_run_writes_nothing(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        AudioSegment.silent(duration=100).export(str(tmp_path / "a.mp3"), format="mp3")
        csv_path = _write_csv(
            tmp_path / "e.csv", ["file", "title"], [["a.mp3", "Preview"]]
        )
        result = runner.invoke(
            tag_edit_cli, [str(tmp_path), "--csv", str(csv_path), "--dry"]
        )
        assert result.exit_code == 0
        audio = MP3(str(tmp_path / "a.mp3"))
        assert audio.tags is None or "TIT2" not in audio.tags


class TestTagEditCliRealAudio:
    pytestmark = pytest.mark.integration

    def test_live_write_updates_mp3(self, runner: CliRunner, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        result = runner.invoke(
            tag_edit_cli,
            [str(path), "--field", "title", "--value", "CLI Title", "--json"],
        )
        assert result.exit_code == 0
        assert str(MP3(str(path)).tags["TIT2"].text[0]) == "CLI Title"

    def test_dry_run_does_not_write_mp3(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        result = runner.invoke(
            tag_edit_cli,
            [str(path), "--field", "title", "--value", "Preview", "--dry", "--json"],
        )
        assert result.exit_code == 0
        audio = MP3(str(path))
        assert audio.tags is None or "TIT2" not in audio.tags

    def test_clear_removes_mp3_field(self, runner: CliRunner, tmp_path: Path) -> None:
        path = tmp_path / "track.mp3"
        AudioSegment.silent(duration=100).export(str(path), format="mp3")
        TagEditor = MP3(str(path))
        from mutagen.id3 import TIT2

        TagEditor.tags.add(TIT2(encoding=3, text=["Remove Me"]))
        TagEditor.save()

        result = runner.invoke(
            tag_edit_cli,
            [str(path), "--field", "title", "--clear", "--json"],
        )
        assert result.exit_code == 0
        audio = MP3(str(path))
        assert audio.tags is None or "TIT2" not in audio.tags
