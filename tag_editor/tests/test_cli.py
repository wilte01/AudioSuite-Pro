"""Tests for tag_editor.cli."""

from __future__ import annotations

import json as json_mod
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner
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
