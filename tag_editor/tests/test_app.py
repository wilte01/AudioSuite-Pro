"""Tests for tag_editor.ui.app."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_suite_shared.exceptions import AudioDirectoryError
from tag_editor.core.processor import EditResult, TagRow
from tag_editor.ui.app import TagEditorApp, main


def _app(tmp_path: Path) -> TagEditorApp:
    app = object.__new__(TagEditorApp)
    app.root = MagicMock()
    app.processor = MagicMock()
    app.directory = MagicMock()
    app.field_var = MagicMock()
    app.value_var = MagicMock()
    app.clear_var = MagicMock()
    app.dry_run = MagicMock()
    app.status_var = MagicMock()
    app.tree = MagicMock()
    app.tree.get_children.return_value = ()
    app._rows = {}
    return app


class TestTagEditorApp:
    def test_help_guide_is_registered(self) -> None:
        assert TagEditorApp.HELP_GUIDE == "Tag_Editor_User_Guide.docx"

    def test_load_library_populates_tree(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        row = TagRow(path=tmp_path / "track.mp3", values={"title": "Loaded"})
        app.processor.scan_directory.return_value = [row]

        with patch("tag_editor.ui.app.messagebox") as messagebox:
            assert app.load_library() is True

        app.tree.insert.assert_called_once()
        messagebox.showerror.assert_not_called()
        assert app._rows[str(row.path)][1]["title"] == "Loaded"

    def test_load_library_requires_directory(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = ""
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            assert app.load_library() is False
        messagebox.showerror.assert_called_once()

    def test_load_library_rejects_missing_directory(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path / "missing")
        app.processor.scan_directory.side_effect = AudioDirectoryError("missing")
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            assert app.load_library() is False
        messagebox.showerror.assert_called_once()

    def test_apply_selection_passes_clear_value(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {"title": "Old"})
        app.field_var.get.return_value = "title"
        app.value_var.get.return_value = "ignored"
        app.clear_var.get.return_value = True
        app.dry_run.get.return_value = False
        result = EditResult(
            path=path,
            field="title",
            old_value="Old",
            new_value=None,
            changed=True,
            written=True,
        )
        app.processor.apply_edits.return_value = [result]

        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_selection()

        edit = app.processor.apply_edits.call_args.args[0][0]
        assert edit.path == path
        assert edit.field == "title"
        assert edit.value is None
        assert app.processor.apply_edits.call_args.kwargs["dry_run"] is False
        messagebox.showwarning.assert_not_called()

    def test_apply_selection_passes_dry_run_flag(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {"title": "Old"})
        app.field_var.get.return_value = "title"
        app.value_var.get.return_value = "New"
        app.clear_var.get.return_value = False
        app.dry_run.get.return_value = True
        result = EditResult(
            path=path,
            field="title",
            old_value="Old",
            new_value="New",
            changed=True,
            written=False,
        )
        app.processor.apply_edits.return_value = [result]

        app.apply_selection()

        assert app.processor.apply_edits.call_args.kwargs["dry_run"] is True
        assert app.tree.set.call_args.args == (str(path), "title", "New")

    def test_apply_selection_requires_selection(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.tree.selection.return_value = []
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_selection()
        messagebox.showwarning.assert_called_once()
        app.processor.apply_edits.assert_not_called()

    def test_apply_selection_reports_errors(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {})
        app.field_var.get.return_value = "title"
        app.value_var.get.return_value = "New"
        app.clear_var.get.return_value = False
        app.dry_run.get.return_value = False
        app.processor.apply_edits.return_value = [
            EditResult(
                path=path,
                field="title",
                old_value=None,
                new_value="New",
                changed=False,
                written=False,
                error="write refused",
            )
        ]
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_selection()
        messagebox.showwarning.assert_called_once()
        app.tree.set.assert_not_called()

    def test_update_row_updates_cached_values(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        values: dict[str, str | None] = {"title": "Old"}
        app._rows[str(path)] = (path, values)
        result = EditResult(
            path=path,
            field="title",
            old_value="Old",
            new_value="New",
            changed=True,
            written=True,
        )
        app._update_row(result)
        assert values["title"] == "New"
        app.tree.set.assert_called_once_with(str(path), "title", "New")


class TestMainEntryPoint:
    def test_main_creates_app_and_enters_mainloop(self, tmp_path: Path) -> None:
        root = MagicMock()
        app = MagicMock()
        with (
            patch("tag_editor.ui.app.tk.Tk", return_value=root) as tk_factory,
            patch("tag_editor.ui.app.TagEditorApp", return_value=app) as app_factory,
        ):
            main(str(tmp_path), live_mode=True)
        tk_factory.assert_called_once()
        app_factory.assert_called_once_with(
            root, directory=str(tmp_path), live_mode=True
        )
        root.mainloop.assert_called_once()
