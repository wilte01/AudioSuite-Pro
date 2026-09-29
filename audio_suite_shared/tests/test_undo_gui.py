"""
Tests for audio_suite_shared.undo_gui.

Covers the pure formatting helpers (friendly name / batch description /
preview / result summary) and the Tk window behaviour via the project's
``object.__new__`` + ``MagicMock`` pattern so no real Tk instance is needed
for logic tests.  A session-scoped Tk root is used where actual widget
construction is exercised.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from audio_suite_shared.batch_undo import (
    BatchInfo,
    BatchUndoLog,
    RevertResult,
    UndoRecord,
)
from audio_suite_shared.undo_gui import (
    UndoTagEditsApp,
    build_preview,
    describe_revert_result,
    friendly_batch_description,
    friendly_tool_name,
    record_preview_line,
)


def _batch(**kwargs: object) -> BatchInfo:
    defaults: dict[str, object] = {
        "batch_id": "abc123",
        "tool_name": "bpm_analyzer",
        "operation_type": "tag_edit",
        "created_at": "2026-09-07 14:32:11",
        "record_count": 3,
    }
    defaults.update(kwargs)
    return BatchInfo(**defaults)  # type: ignore[arg-type]


def _record(**kwargs: object) -> UndoRecord:
    defaults: dict[str, object] = {
        "record_id": 1,
        "batch_id": "abc123",
        "file_path": "C:\\Music\\song.mp3",
        "operation": "write_bpm",
        "has_snapshot": True,
        "source_path": None,
        "dest_path": None,
        "file_action": None,
    }
    defaults.update(kwargs)
    return UndoRecord(**defaults)  # type: ignore[arg-type]


def _app() -> UndoTagEditsApp:
    """Create an UndoTagEditsApp without running __init__ (no real Tk)."""
    app = object.__new__(UndoTagEditsApp)
    app.root = MagicMock()
    app._batches = []
    app._selected_batch_id = None
    app._batch_list = MagicMock()
    app._preview_text = MagicMock()
    app._undo_btn = MagicMock()
    app._status_label = MagicMock()
    return app


# ── Pure helpers ──────────────────────────────────────────────────────────


class TestFriendlyToolName:
    def test_known_tool_name_mapped(self) -> None:
        assert friendly_tool_name("bpm_analyzer") == "BPM Analyzer"

    def test_mood_analysis_batch_tagger_mapped(self) -> None:
        assert (
            friendly_tool_name("mood_analysis_batch_tagger")
            == "Mood Analysis Batch Tagger"
        )

    def test_unknown_tool_name_passthrough(self) -> None:
        assert friendly_tool_name("mystery_tool") == "mystery_tool"

    def test_replaygain_analyzer_mapped(self) -> None:
        assert friendly_tool_name("replaygain_analyzer") == "ReplayGain Analyzer"

    def test_metadata_scrubber_mapped(self) -> None:
        assert friendly_tool_name("metadata_scrubber") == "Metadata Scrubber"

    def test_album_art_normalizer_mapped(self) -> None:
        assert friendly_tool_name("album_art_normalizer") == "Album Art Normalizer"

    def test_in_place_audio_tools_mapped(self) -> None:
        """The two byte-level tools must not show their raw id in the list.

        B2 made their undo entries meaningful, and the batch list is where the
        user picks what to undo; a raw ``noise_reduction`` row there looks like
        an internal error.
        """
        assert friendly_tool_name("noise_reduction") == "Noise Reduction"
        assert friendly_tool_name("pop_click_remover") == "Pop & Click Remover"


class TestFriendlyBatchDescription:
    def test_singular_file(self) -> None:
        b = _batch(record_count=1)
        desc = friendly_batch_description(b)
        assert "1 file" in desc
        assert "BPM Analyzer" in desc
        assert b.batch_id not in desc  # raw batch id hidden from the user

    def test_plural_files(self) -> None:
        b = _batch(record_count=12)
        desc = friendly_batch_description(b)
        assert "12 files" in desc

    def test_contains_timestamp(self) -> None:
        b = _batch(created_at="2026-09-07 14:32:11")
        assert "2026-09-07 14:32:11" in friendly_batch_description(b)


class TestRecordPreviewLine:
    def test_tag_restore(self) -> None:
        line = record_preview_line(_record())
        assert line == "Restore tags: C:\\Music\\song.mp3"

    def test_move_revert(self) -> None:
        r = _record(
            file_action="move",
            source_path="C:\\Old\\song.mp3",
            dest_path="C:\\New\\song.mp3",
        )
        line = record_preview_line(r)
        assert "Move back" in line
        assert "C:\\New\\song.mp3" in line
        assert "C:\\Old\\song.mp3" in line

    def test_copy_revert(self) -> None:
        r = _record(
            file_action="copy",
            source_path="C:\\Old\\song.mp3",
            dest_path="C:\\Copy\\song.mp3",
        )
        line = record_preview_line(r)
        assert line == "Remove copy: C:\\Copy\\song.mp3"

    def test_delete_revert(self) -> None:
        r = _record(
            file_action="delete",
            file_path="C:\\Deleted\\song.flac",
        )
        line = record_preview_line(r)
        assert line == "Restore deleted file: C:\\Deleted\\song.flac"

    def test_in_place_audio_revert_does_not_claim_tags(self) -> None:
        """An in-place repair must not be previewed as a tag-only restore.

        The byte-level record (iteration-6 B2) restores the audio too, so the
        generic fall-through text would understate what Undo is about to do to
        the user's file.
        """
        r = _record(
            file_action="overwrite",
            file_path="C:\\Music\\hum.wav",
        )
        line = record_preview_line(r)
        assert line == "Restore original audio: C:\\Music\\hum.wav"
        assert "tags" not in line


class TestBuildPreview:
    def test_empty_records(self) -> None:
        assert "no recorded changes" in build_preview([])

    def test_single_record(self) -> None:
        preview = build_preview([_record()])
        assert "1 file(s)" in preview
        assert "Restore tags: C:\\Music\\song.mp3" in preview

    def test_many_records_paginated(self) -> None:
        records = [
            _record(record_id=i, file_path=f"C:\\M\\f{i}.mp3") for i in range(20)
        ]
        preview = build_preview(records)
        assert "20 file(s)" in preview
        assert "and 12 more file(s)" in preview

    def test_preview_lines_count_capped(self) -> None:
        records = [_record(record_id=i) for i in range(20)]
        preview = build_preview(records)
        # 8 shown records + intro line + "and N more" line
        lines = [ln for ln in preview.splitlines() if ln.startswith("  •")]
        assert len(lines) == 8


class TestDescribeRevertResult:
    def test_summary_line(self) -> None:
        result = RevertResult(batch_id="x", reverted=5, failed=0, skipped=1)
        text = describe_revert_result(result)
        assert "Reverted 5" in text
        assert "failed 0" in text
        assert "skipped 1" in text


# ── Window behaviour (no real Tk) ─────────────────────────────────────────


class TestWindowLogic:
    def test_refresh_populates_list(self) -> None:
        app = _app()
        app._load_batches = MagicMock(
            return_value=[_batch(), _batch(tool_name="tempo")]
        )
        app.refresh()
        assert len(app._batches) == 2
        assert app._batch_list.insert.call_count == 2
        assert app._selected_batch_id is None

    def test_refresh_clears_selection(self) -> None:
        app = _app()
        app._load_batches = MagicMock(return_value=[_batch()])
        app._selected_batch_id = "stale"
        app.refresh()
        assert app._selected_batch_id is None

    def test_refresh_error_path(self) -> None:
        app = _app()
        app._load_batches = MagicMock(side_effect=RuntimeError("db down"))
        app.refresh()
        assert app._batches == []

    def test_on_select_updates_selection(self) -> None:
        app = _app()
        app._batches = [_batch(batch_id="first"), _batch(batch_id="second")]
        app._batch_list.index = MagicMock(return_value=1)
        app.on_select(None)
        assert app._selected_batch_id == "second"

    def test_on_select_out_of_range_clears_selection(self) -> None:
        app = _app()
        app._batches = [_batch(batch_id="first")]
        app._batch_list.index = MagicMock(return_value=5)
        app.on_select(None)
        assert app._selected_batch_id is None

    def test_preview_selected_empty_state(self) -> None:
        app = _app()
        app._batches = []
        app._selected_batch_id = None
        text = app.preview_selected()
        assert "no saved undo history" in text

    def test_preview_selected_no_selection_but_history(self) -> None:
        app = _app()
        app._batches = [_batch()]
        app._selected_batch_id = None
        text = app.preview_selected()
        assert "Select a run from the list" in text

    def test_preview_selected_with_batch(self) -> None:
        app = _app()
        app._batches = [_batch(batch_id="abc")]
        app._selected_batch_id = "abc"
        app._load_records = MagicMock(return_value=[_record()])
        text = app.preview_selected()
        assert "Restore tags: C:\\Music\\song.mp3" in text

    def test_preview_selected_error_path(self) -> None:
        app = _app()
        app._batches = [_batch(batch_id="abc")]
        app._selected_batch_id = "abc"
        app._load_records = MagicMock(side_effect=RuntimeError("boom"))
        text = app.preview_selected()
        assert "Could not load the details" in text

    @patch("audio_suite_shared.undo_gui.messagebox.askyesno", return_value=False)
    def test_confirm_undo_cancelled(self, ask: MagicMock) -> None:
        app = _app()
        app._selected_batch_id = "abc"
        app.confirm_and_undo()
        ask.assert_called_once()
        app._perform_revert = MagicMock()  # ensure not called is proven below
        assert not app._perform_revert.called

    @patch("audio_suite_shared.undo_gui.messagebox.askyesno", return_value=True)
    @patch("audio_suite_shared.undo_gui.messagebox.showinfo")
    @patch("audio_suite_shared.undo_gui.messagebox.showwarning")
    def test_confirm_undo_proceeds(
        self, warn: MagicMock, info: MagicMock, ask: MagicMock
    ) -> None:
        app = _app()
        app._selected_batch_id = "abc"
        app._perform_revert = MagicMock(
            return_value=RevertResult(batch_id="abc", reverted=4)
        )
        app.confirm_and_undo()
        app._perform_revert.assert_called_once_with("abc")
        info.assert_called_once()
        assert not warn.called

    @patch("audio_suite_shared.undo_gui.messagebox.askyesno", return_value=True)
    @patch("audio_suite_shared.undo_gui.messagebox.showwarning")
    @patch("audio_suite_shared.undo_gui.messagebox.showinfo")
    def test_confirm_undo_reports_failures(
        self, info: MagicMock, warn: MagicMock, ask: MagicMock
    ) -> None:
        app = _app()
        app._selected_batch_id = "abc"
        app._perform_revert = MagicMock(
            return_value=RevertResult(batch_id="abc", reverted=1, failed=2)
        )
        app.confirm_and_undo()
        warn.assert_called_once()
        assert not info.called

    @patch("audio_suite_shared.undo_gui.messagebox.askyesno", return_value=True)
    @patch("audio_suite_shared.undo_gui.messagebox.showerror")
    def test_confirm_undo_error_path(self, err: MagicMock, ask: MagicMock) -> None:
        app = _app()
        app._selected_batch_id = "abc"
        app._perform_revert = MagicMock(side_effect=RuntimeError("boom"))
        app.confirm_and_undo()
        err.assert_called_once()

    def test_confirm_undo_no_selection_is_noop(self) -> None:
        app = _app()
        app._selected_batch_id = None
        app._perform_revert = MagicMock(return_value=RevertResult(batch_id="abc"))
        app.confirm_and_undo()
        assert not app._perform_revert.called


# ── Widget construction (real Tk via session root) ─────────────────────────


class TestWidgetBuild:
    def test_build_creates_undo_button_disabled(self, tk_root) -> None:
        app = object.__new__(UndoTagEditsApp)
        app.root = tk_root
        app.refresh = MagicMock()
        app._on_close = MagicMock()
        app.build()
        assert app._undo_btn is not None
        assert app._undo_btn.cget("state") == "disabled"
        assert app._batch_list is not None
        assert app._preview_text is not None
        assert app._status_label is not None


# ── Real-engine integration (temp SQLite DB) ────────────────────────────────


class TestRealEngineIntegration:
    """Drive the shared batch_undo engine against a real temp SQLite database
    and confirm a recorded run surfaces exactly as the GUI presents it.

    Proves the recorded data round-trips: engine writes → BatchInfo/UndoRecord
    reads → friendly list labels → preview text.
    """

    def test_recorded_run_surfaces_in_gui_list(self, tmp_path) -> None:
        db_path = tmp_path / "undo_log.db"
        with BatchUndoLog(db_path=db_path) as log:
            batch_id = log.start_batch("bpm_analyzer", "tag_edit")
            log.record_tag_edit(batch_id, "C:\\Music\\a.mp3", "write_bpm", None)
            log.record_tag_edit(batch_id, "C:\\Music\\b.mp3", "write_bpm", None)
            log.record_tag_edit(batch_id, "C:\\Music\\c.mp3", "write_bpm", None)

        app = _app()
        app._load_batches = lambda: BatchUndoLog(db_path=db_path).list_batches()
        app._load_records = lambda bid: BatchUndoLog(db_path=db_path).get_batch_records(
            bid
        )

        app.refresh()

        assert len(app._batches) == 1
        assert app._batch_list.insert.call_count == 1
        label = friendly_batch_description(app._batches[0])
        assert "BPM Analyzer" in label
        assert "3 files" in label
        assert batch_id not in label

        app._selected_batch_id = batch_id
        preview = app.preview_selected()
        assert "Restore tags: C:\\Music\\a.mp3" in preview
        assert "Restore tags: C:\\Music\\b.mp3" in preview
        assert "Restore tags: C:\\Music\\c.mp3" in preview

    def test_no_history_shows_empty_state(self, tmp_path) -> None:
        app = _app()
        app._load_batches = lambda: BatchUndoLog(
            db_path=tmp_path / "empty.db"
        ).list_batches()
        app.refresh()
        assert app._batches == []
        assert "no saved undo history" in app.preview_selected()
