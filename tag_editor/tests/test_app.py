"""Tests for tag_editor.ui.app."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_suite_shared.exceptions import AudioDirectoryError, AudioSuiteError
from tag_editor.core.csv_io import CsvImportPlan
from tag_editor.core.processor import EditResult, FieldEdit, TagRow
from tag_editor.ui.app import TagEditorApp, main


def _app(tmp_path: Path) -> TagEditorApp:
    app = object.__new__(TagEditorApp)
    app.root = MagicMock()
    app.processor = MagicMock()
    app.directory = MagicMock()
    app.field_var = MagicMock()
    app.value_var = MagicMock()
    app.clear_var = MagicMock()
    app.bulk_operation_var = MagicMock()
    app.bulk_field_var = MagicMock()
    app.second_field_var = MagicMock()
    app.case_mode_var = MagicMock()
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

    def test_apply_selection_error_dialog_excludes_successful_rows(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        ok_path = tmp_path / "ok.mp3"
        bad_path = tmp_path / "bad.mp3"
        app.tree.selection.return_value = [str(ok_path), str(bad_path)]
        app._rows[str(ok_path)] = (ok_path, {})
        app._rows[str(bad_path)] = (bad_path, {})
        app.field_var.get.return_value = "title"
        app.value_var.get.return_value = "New"
        app.clear_var.get.return_value = False
        app.dry_run.get.return_value = False
        app.processor.apply_edits.return_value = [
            EditResult(
                path=ok_path,
                field="title",
                old_value=None,
                new_value="New",
                changed=True,
                written=True,
            ),
            EditResult(
                path=bad_path,
                field="title",
                old_value=None,
                new_value="New",
                changed=False,
                written=False,
                error="write refused",
            ),
        ]
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_selection()
        messagebox.showwarning.assert_called_once()
        message = messagebox.showwarning.call_args.args[1]
        assert "write refused" in message
        assert "Unknown error" not in message

    def test_apply_bulk_selection_passes_operation_options(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {"genre": "Rock/Pop", "album": "Album"})
        app.bulk_operation_var.get.return_value = "Normalize Slashes (TXXX Rule)"
        app.bulk_field_var.get.return_value = "genre"
        app.second_field_var.get.return_value = "album"
        app.case_mode_var.get.return_value = "Title Case"
        app.dry_run.get.return_value = True
        result = EditResult(
            path=path,
            field="genre",
            old_value="Rock/Pop",
            new_value="Rock; Pop",
            changed=True,
            written=False,
        )
        app.processor.apply_bulk.return_value = [result]

        app.apply_bulk_selection()

        rows = app.processor.apply_bulk.call_args.args[0]
        assert rows[0].path == path
        assert rows[0].values["genre"] == "Rock/Pop"
        assert app.processor.apply_bulk.call_args.args[1:] == (
            "Normalize Slashes (TXXX Rule)",
            "genre",
        )
        assert app.processor.apply_bulk.call_args.kwargs == {
            "second_field": "album",
            "case_mode": "Title Case",
            "dry_run": True,
        }
        app.tree.set.assert_called_once_with(str(path), "genre", "Rock; Pop")

    def test_apply_bulk_selection_requires_selection(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.tree.selection.return_value = []
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_bulk_selection()
        messagebox.showwarning.assert_called_once()
        app.processor.apply_bulk.assert_not_called()

    def test_apply_bulk_selection_reports_validation_error(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {})
        app.bulk_operation_var.get.return_value = "Swap Fields"
        app.bulk_field_var.get.return_value = "title"
        app.second_field_var.get.return_value = "title"
        app.case_mode_var.get.return_value = "Title Case"
        app.dry_run.get.return_value = False
        app.processor.apply_bulk.side_effect = AudioSuiteError(
            "Swap Fields requires two different fields."
        )
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.apply_bulk_selection()
        messagebox.showerror.assert_called_once()

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


class TestTagEditorAppCsv:
    def test_import_csv_applies_plan_edits(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        app.dry_run.get.return_value = True
        path = tmp_path / "track.mp3"
        app._rows[str(path)] = (path, {"title": "Old"})
        app.processor.apply_edits.return_value = [
            EditResult(
                path=path,
                field="title",
                old_value="Old",
                new_value="New",
                changed=True,
                written=False,
            )
        ]
        plan = CsvImportPlan(edits=[FieldEdit(path, "title", "New")], row_count=1)

        with (
            patch("tag_editor.ui.app.filedialog.askopenfilename", return_value="e.csv"),
            patch("tag_editor.ui.app.build_import_plan", return_value=plan),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.import_csv()

        assert app.processor.apply_edits.call_args.kwargs["dry_run"] is True
        assert app._rows[str(path)][1]["title"] == "New"
        messagebox.showerror.assert_not_called()
        messagebox.showwarning.assert_not_called()

    def test_import_csv_requires_directory(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = ""
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.import_csv()
        messagebox.showerror.assert_called_once()
        app.processor.apply_edits.assert_not_called()

    def test_import_csv_cancelled_dialog_does_nothing(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        with patch(
            "tag_editor.ui.app.filedialog.askopenfilename", return_value=""
        ) as mock_dialog:
            app.import_csv()
        mock_dialog.assert_called_once()
        app.processor.apply_edits.assert_not_called()

    def test_import_csv_reports_validation_error(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        app.dry_run.get.return_value = False
        with (
            patch("tag_editor.ui.app.filedialog.askopenfilename", return_value="e.csv"),
            patch(
                "tag_editor.ui.app.build_import_plan",
                side_effect=AudioSuiteError("CSV must contain a file column."),
            ),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.import_csv()
        messagebox.showerror.assert_called_once()
        app.processor.apply_edits.assert_not_called()

    def test_import_csv_surfaces_row_errors_and_ignored_columns(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        app.dry_run.get.return_value = True
        plan = CsvImportPlan(
            edits=[],
            row_errors=["Row 2: file not found: gone.mp3"],
            ignored_columns=["cover"],
            row_count=2,
        )
        with (
            patch("tag_editor.ui.app.filedialog.askopenfilename", return_value="e.csv"),
            patch("tag_editor.ui.app.build_import_plan", return_value=plan),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.import_csv()

        messagebox.showwarning.assert_called_once()
        assert "file not found" in messagebox.showwarning.call_args.args[1]
        status = "".join(call.args[0] for call in app.status_var.set.call_args_list)
        assert "Ignored columns: cover" in status

    def test_export_csv_writes_rows(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        path = tmp_path / "track.mp3"
        app._rows[str(path)] = (path, {"title": "One", "artist": None})

        with (
            patch(
                "tag_editor.ui.app.filedialog.asksaveasfilename", return_value="out.csv"
            ),
            patch("tag_editor.ui.app.export_csv", return_value=1) as exporter,
        ):
            app.export_csv()

        rows = exporter.call_args.args[0]
        assert rows[0].path == path
        assert rows[0].values["title"] == "One"
        assert exporter.call_args.args[2] == tmp_path

    def test_export_csv_requires_loaded_grid(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            app.export_csv()
        messagebox.showwarning.assert_called_once()

    def test_export_csv_cancelled_dialog_does_nothing(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app._rows[str(tmp_path / "a.mp3")] = (tmp_path / "a.mp3", {})
        with (
            patch(
                "tag_editor.ui.app.filedialog.asksaveasfilename", return_value=""
            ) as mock_dialog,
            patch("tag_editor.ui.app.export_csv") as exporter,
        ):
            app.export_csv()
        mock_dialog.assert_called_once()
        exporter.assert_not_called()

    def test_export_csv_reports_write_error(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        app._rows[str(tmp_path / "a.mp3")] = (tmp_path / "a.mp3", {})
        with (
            patch(
                "tag_editor.ui.app.filedialog.asksaveasfilename", return_value="out.csv"
            ),
            patch(
                "tag_editor.ui.app.export_csv",
                side_effect=AudioSuiteError("Permission denied"),
            ),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.export_csv()
        messagebox.showerror.assert_called_once()


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


class TestBrowseDirectory:
    def test_browse_directory_sets_path_when_selected(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        with patch(
            "tag_editor.ui.app.filedialog.askdirectory",
            return_value=str(tmp_path),
        ):
            app._browse_directory()
        app.directory.set.assert_called_once_with(str(tmp_path))

    def test_browse_directory_does_nothing_when_cancelled(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        with patch(
            "tag_editor.ui.app.filedialog.askdirectory",
            return_value="",
        ) as mock_dialog:
            app._browse_directory()
        mock_dialog.assert_called_once()
        app.directory.set.assert_not_called()


class TestOnTreeSelect:
    def test_on_tree_select_populates_value_and_clears_flag(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {"title": "My Title"})
        app.field_var.get.return_value = "title"

        with patch("tag_editor.ui.app.normalize_field", return_value="title"):
            app._on_tree_select(None)

        app.value_var.set.assert_called_once_with("My Title")
        app.clear_var.set.assert_called_once_with(False)

    def test_on_tree_select_no_selection_returns_early(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.tree.selection.return_value = []

        app._on_tree_select(None)

        app.tree.selection.assert_called_once_with()
        app.value_var.set.assert_not_called()
        app.clear_var.set.assert_not_called()

    def test_on_tree_select_multiple_selections_returns_early(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        app.tree.selection.return_value = ["a.mp3", "b.mp3"]

        app._on_tree_select(None)

        app.tree.selection.assert_called_once_with()
        app.value_var.set.assert_not_called()
        app.clear_var.set.assert_not_called()

    def test_on_tree_select_unknown_iid_returns_early(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        app.tree.selection.return_value = ["unknown_iid"]

        app._on_tree_select(None)

        app.tree.selection.assert_called_once_with()
        app.value_var.set.assert_not_called()
        app.clear_var.set.assert_not_called()


class TestLoadLibraryAudioSuiteError:
    def test_load_library_shows_error_on_generic_audio_suite_error(
        self, tmp_path: Path
    ) -> None:
        app = _app(tmp_path)
        app.directory.get.return_value = str(tmp_path)
        app.processor.scan_directory.side_effect = AudioSuiteError("corrupt database")
        with patch("tag_editor.ui.app.messagebox") as messagebox:
            assert app.load_library() is False
        messagebox.showerror.assert_called_once()
        assert "corrupt database" in messagebox.showerror.call_args.args[1]


class TestApplySelectionErrors:
    def test_apply_selection_normalize_field_error(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {})
        app.field_var.get.return_value = "invalid_field"
        app.clear_var.get.return_value = False

        with (
            patch(
                "tag_editor.ui.app.normalize_field",
                side_effect=AudioSuiteError("Unsupported tag field: invalid_field"),
            ),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.apply_selection()

        messagebox.showerror.assert_called_once()
        assert "Unsupported tag field" in messagebox.showerror.call_args.args[1]
        app.processor.apply_edits.assert_not_called()

    def test_apply_selection_apply_edits_error(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = [str(path)]
        app._rows[str(path)] = (path, {"title": "Old"})
        app.field_var.get.return_value = "title"
        app.value_var.get.return_value = "New"
        app.clear_var.get.return_value = False
        app.dry_run.get.return_value = False
        app.processor.apply_edits.side_effect = AudioSuiteError("disk full")

        with (
            patch("tag_editor.ui.app.normalize_field", return_value="title"),
            patch("tag_editor.ui.app.messagebox") as messagebox,
        ):
            app.apply_selection()

        messagebox.showerror.assert_called_once()
        assert "disk full" in messagebox.showerror.call_args.args[1]


class TestUpdateRowIidGuard:
    def test_update_row_skips_unknown_iid(self, tmp_path: Path) -> None:
        app = _app(tmp_path)
        result = EditResult(
            path=tmp_path / "missing.mp3",
            field="title",
            old_value=None,
            new_value="New",
            changed=True,
            written=True,
        )
        app._update_row(result)
        app.tree.set.assert_not_called()

        known = tmp_path / "known.mp3"
        app._rows[str(known)] = (known, {"title": "Old"})
        app._update_row(
            EditResult(
                path=known,
                field="title",
                old_value="Old",
                new_value="New",
                changed=True,
                written=True,
            )
        )
        app.tree.set.assert_called_once_with(str(known), "title", "New")
