"""
undo_gui.py — Friendly graphical interface for undoing Audio Suite changes.

Provides a self-contained Tk window (``UndoTagEditsApp``) that surfaces the
batch undo log to non-technical users.  Every tool that changes a file
records what it is about to change: tag-writing tools snapshot the tags, and
the tools that repair audio in place snapshot the complete file.  This window
lets a user pick one of those "runs" and put the files back the way they were
before that run, with plain-English descriptions and a clear confirmation
step.

The window reuses the shared ``batch_undo`` engine unchanged — no reads or
writes other than through its public functions:
``list_recent_batches``, ``get_batch_records`` (via ``BatchUndoLog``), and
``revert_batch_by_id``.

User-facing behaviour
---------------------
* A list of recent runs, each shown as a friendly description (e.g.
  ``Today 14:32 · BPM Analyzer · 50 files``) — the raw batch id is hidden.
* Selecting a run shows a preview of what would be reverted.
* Undoing requires an explicit confirmation warning that current file contents
  will be permanently overwritten with the pre-run versions.
* A refresh button re-reads the log (e.g. after the user has run a new tool).

Changed in 2.0.0: ``_TOOL_DISPLAY_NAMES`` gains ``stem_separator``, so a run
recorded by the new tool (Sprint 6, Item 6.1) reads as "Stem Separator" rather
than as its raw id.
"""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox
from typing import Sequence

from . import styles
from .batch_undo import (
    BatchInfo,
    BatchUndoLog,
    RevertResult,
    UndoRecord,
    list_recent_batches,
    revert_batch_by_id,
)

_log = logging.getLogger(f"audio_suite.{__name__}")

_TOOL_DISPLAY_NAMES: dict[str, str] = {
    "album_art_normalizer": "Album Art Normalizer",
    "album_art_sync": "Album Art Sync",
    "album_genre_tagger": "Album Genre Tagger",
    "asx_extractor": "ASX Playlist Extractor",
    "audio_fingerprinter": "Audio Fingerprinter",
    "audio_normalizer": "Audio Normalizer",
    "audio_refinery": "Audio Refinery",
    "bpm_analyzer": "BPM Analyzer",
    "file_reorganizer": "Tag-Based File Reorganizer",
    "genre_sync": "Genre Sync",
    "key_detector": "Key Detector",
    "lyrics_manager": "Lyrics Manager",
    "metadata_scrubber": "Metadata Scrubber",
    "mood_analysis_batch_tagger": "Mood Analysis Batch Tagger",
    "mood_analyzer": "Mood Analyzer",
    "music_format_converter": "Music Format Converter",
    "noise_reduction": "Noise Reduction",
    "pop_click_remover": "Pop & Click Remover",
    "replaygain_analyzer": "ReplayGain Analyzer",
    "silence_trimmer": "Silence Trimmer",
    "stem_separator": "Stem Separator",
    "tag_editor": "Tag Editor",
    "tag_field_updater": "Tag Field Updater",
    "tempo_analyzer": "Tempo Analyzer",
}

_MAX_PREVIEW_RECORDS = 8


# ---------------------------------------------------------------------------
# Pure helpers (kept free of Tk so they are trivially testable)
# ---------------------------------------------------------------------------


def friendly_tool_name(tool_name: str) -> str:
    """Map a raw tool identifier to a human-readable display name.

    Args:
        tool_name: Internal tool identifier (e.g. ``"bpm_analyzer"``).

    Returns:
        A friendly name, falling back to the raw identifier when unknown.
    """
    return _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)


def friendly_batch_description(batch: BatchInfo) -> str:
    """Render a single batch as a short, friendly, single-line description.

    Args:
        batch: The batch to describe.

    Returns:
        A human-readable label such as
        ``2026-09-07 14:32 · BPM Analyzer · 50 files``.  The raw batch id is
        not shown.
    """
    tool = friendly_tool_name(batch.tool_name)
    count = batch.record_count
    noun = "file" if count == 1 else "files"
    return f"{batch.created_at} · {tool} · {count} {noun}"


def record_preview_line(record: UndoRecord) -> str:
    """Render a single undo record as one human-readable preview line.

    Args:
        record: The undo record to describe.

    Returns:
        A short line describing what would be restored for one file.
    """
    if record.file_action == "move":
        return f"Move back: {record.dest_path}  →  {record.source_path}"
    if record.file_action == "copy":
        return f"Remove copy: {record.dest_path}"
    if record.file_action == "delete":
        return f"Restore deleted file: {record.file_path}"
    if record.file_action == "overwrite":
        return f"Restore original audio: {record.file_path}"
    return f"Restore tags: {record.file_path}"


def build_preview(records: Sequence[UndoRecord]) -> str:
    """Build the text shown in the preview pane for a selected run.

    Args:
        records: The batch records to summarise.

    Returns:
        A plain-English summary of what undoing the run would do.
    """
    if not records:
        return "This run has no recorded changes to undo."
    lines = [f"This will restore the state of {len(records)} file(s):"]
    shown = records[:_MAX_PREVIEW_RECORDS]
    for record in shown:
        lines.append(f"  • {record_preview_line(record)}")
    if len(records) > len(shown):
        lines.append(f"  … and {len(records) - len(shown)} more file(s).")
    return "\n".join(lines)


def describe_revert_result(result: RevertResult) -> str:
    """Render a ``RevertResult`` as a short summary for the user.

    Args:
        result: The outcome of a revert operation.

    Returns:
        A single human-readable status line.
    """
    return (
        f"Done. Reverted {result.reverted}, failed {result.failed}, "
        f"skipped {result.skipped}."
    )


# ---------------------------------------------------------------------------
# Tk window
# ---------------------------------------------------------------------------


class UndoTagEditsApp:
    """Graphical window for browsing and reverting undo batches.

    Designed to be testable without a real display via the
    ``object.__new__`` + ``MagicMock`` pattern used across the suite.
    All database access goes through methods that can be overridden or
    patched; the widget tree is built lazily by :meth:`build`.
    """

    HELP_GUIDE = "Undo_Tag_Edits_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        """Initialise the undo window.

        Args:
            root: The Tk root window.
        """
        self.root = root
        self.root.title("Undo Tag Edits")
        self.root.configure(bg=styles.BG_APP)
        try:
            from . import platform_utils, suite_config

            platform_utils.setup_window(
                root, 760, 620, suite_config, "undo_tag_edits_window"
            )
        except Exception:  # noqa: BLE001 - window fit is best-effort
            _log.debug("Window sizing setup skipped", exc_info=True)

        self._batches: list[BatchInfo] = []
        self._selected_batch_id: str | None = None
        self._batch_list: tk.Listbox | None = None
        self._preview_text: tk.Text | None = None
        self._undo_btn: tk.Button | None = None
        self._status_label: tk.Label | None = None

        self.build()
        self.refresh()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Database access (overridable/patched in tests) ───────────────────

    def _load_batches(self) -> list[BatchInfo]:
        """Return the recent undo batches, newest first."""
        return list_recent_batches()

    def _load_records(self, batch_id: str) -> list[UndoRecord]:
        """Return the records for a batch."""
        with BatchUndoLog() as log:
            return log.get_batch_records(batch_id)

    def _perform_revert(self, batch_id: str) -> RevertResult:
        """Revert a batch via the shared engine."""
        return revert_batch_by_id(batch_id)

    # ── Public actions ───────────────────────────────────────────────────

    def refresh(self) -> None:
        """Reload the batch list and reset the current selection."""
        try:
            self._batches = self._load_batches()
        except Exception:  # noqa: BLE001 - surfaces in the status line
            _log.exception("Could not load undo batch list")
            self._batches = []
        self._selected_batch_id = None

        if self._batch_list is not None:
            self._batch_list.delete(0, tk.END)
            for batch in self._batches:
                self._batch_list.insert(tk.END, friendly_batch_description(batch))
            self._batch_list.selection_clear(0, tk.END)

        self._update_preview()
        self._update_ui_state()

    def on_select(self, _event: object) -> None:
        """Handle a selection in the batch list (listbox event listener)."""
        index = (
            self._batch_list.index(tk.ANCHOR) if self._batch_list is not None else -1
        )
        if index < 0 or index >= len(self._batches):
            self._selected_batch_id = None
        else:
            self._selected_batch_id = self._batches[index].batch_id
        self._update_preview()
        self._update_ui_state()

    def preview_selected(self) -> str:
        """Return the preview text for the currently selected batch.

        Returns:
            A human-readable preview of the selected run, or an empty-state
            message when nothing is selected.
        """
        if self._selected_batch_id is None:
            if not self._batches:
                return (
                    "You have no saved undo history yet.\n\n"
                    "Undo history is recorded automatically whenever you run a "
                    "tag-editing tool (for example BPM Analyzer or Tempo "
                    "Analyzer) or a tool that repairs audio in place (Noise "
                    "Reduction, Pop & Click Remover). Run one of those tools "
                    "first, then return here to restore your files."
                )
            return "Select a run from the list above to see what it would undo."
        try:
            records = self._load_records(self._selected_batch_id)
        except Exception:  # noqa: BLE001 - surfaces in the preview pane
            _log.exception("Could not load records for batch")
            return "Could not load the details for the selected run."
        return build_preview(records)

    def confirm_and_undo(self) -> None:
        """Guard with a warning then revert the selected run."""
        if self._selected_batch_id is None:
            return
        proceed = messagebox.askyesno(
            "Undo Tag Edits",
            "This will permanently overwrite the current contents of the files "
            "in this run, restoring them to the way they were before the run "
            "happened.\n\n"
            "For a run that repaired audio in place (Noise Reduction, Pop & "
            "Click Remover) that means the original audio is put back, byte "
            "for byte, along with its tags.\n\n"
            "This action cannot be undone.\n\n"
            "Do you want to continue?",
        )
        if not proceed:
            return

        try:
            result = self._perform_revert(self._selected_batch_id)
        except Exception:  # noqa: BLE001 - the user is told directly
            _log.exception("Revert failed")
            messagebox.showerror(
                "Undo Tag Edits",
                "Could not complete the undo. See the log for details.",
            )
            return

        if result.failed:
            messagebox.showwarning(
                "Undo Tag Edits",
                describe_revert_result(result)
                + "\n\nSome files could not be restored. "
                "See the log for details.",
            )
        else:
            messagebox.showinfo("Undo Tag Edits", describe_revert_result(result))

        self.refresh()

    def _on_close(self) -> None:
        """Close the window (geometry persistence is handled by setup_window)."""
        self.root.destroy()

    # ── UI construction / state ──────────────────────────────────────────

    def _update_preview(self) -> None:
        if self._preview_text is not None:
            self._preview_text.config(state="normal")
            self._preview_text.delete("1.0", tk.END)
            self._preview_text.insert("1.0", self.preview_selected())
            self._preview_text.config(state="disabled")

    def _update_ui_state(self) -> None:
        if self._undo_btn is not None:
            enabled = self._selected_batch_id is not None
            self._undo_btn.config(state="normal" if enabled else "disabled")
        if self._status_label is not None:
            if not self._batches:
                self._status_label.config(
                    text="No undo history found.", fg=styles.FG_SUB
                )
            else:
                self._status_label.config(
                    text=f"{len(self._batches)} recent run(s) recorded.",
                    fg=styles.FG_SUB,
                )

    def _open_help(self) -> None:
        """Open the user guide for the undo tool."""
        from .ui_helpers import open_help_guide

        open_help_guide(self.HELP_GUIDE, None)

    def build(self) -> None:
        """Construct the window's widget tree."""
        container = tk.Frame(self.root, bg=styles.BG_APP, padx=16, pady=12)
        container.pack(fill="both", expand=True)

        title = tk.Label(
            container,
            text="Undo Tag Edits",
            font=styles.FONT_TITLE_L,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
        )
        title.pack(anchor="w")

        explain = tk.Label(
            container,
            justify="left",
            anchor="w",
            wraplength=700,
            text=(
                "Every time you run a tag-editing tool, Audio Suite saves a "
                "copy of the tags exactly as they were before that run. Tools "
                "that repair audio in place (Noise Reduction, Pop & Click "
                "Remover) save the whole file instead, so undoing one of those "
                "runs brings back the original audio byte for byte. Choose a "
                "run below and restore your files to the way they were before "
                "it happened."
            ),
            font=styles.FONT_BODY,
            bg=styles.BG_APP,
            fg=styles.FG_SUB,
        )
        explain.pack(fill="x", pady=(4, 10))

        # ── Recent runs list ──────────────────────────────────────────────
        list_label = tk.Label(
            container,
            text="Recent runs:",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
        )
        list_label.pack(anchor="w")

        list_frame = tk.Frame(container, bg=styles.BG_WHITE)
        list_frame.pack(fill="both", expand=True, pady=(2, 8))
        scroll = tk.Scrollbar(list_frame, orient="vertical")
        self._batch_list = tk.Listbox(
            list_frame,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectbackground=styles.get_main(),
            selectforeground="white",
            yscrollcommand=scroll.set,
            exportselection=False,
            height=8,
        )
        scroll.config(command=self._batch_list.yview)
        self._batch_list.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._batch_list.bind("<<ListboxSelect>>", self.on_select)

        # ── Preview ───────────────────────────────────────────────────────
        preview_label = tk.Label(
            container,
            text="What this will do:",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
        )
        preview_label.pack(anchor="w")

        preview_frame = tk.Frame(container, bg=styles.BG_WHITE)
        preview_frame.pack(fill="both", expand=True, pady=(2, 8))
        p_scroll = tk.Scrollbar(preview_frame, orient="vertical")
        self._preview_text = tk.Text(
            preview_frame,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            yscrollcommand=p_scroll.set,
            height=8,
            wrap="word",
            relief=tk.SUNKEN,
            padx=8,
            pady=8,
        )
        p_scroll.config(command=self._preview_text.yview)
        self._preview_text.pack(side="left", fill="both", expand=True)
        p_scroll.pack(side="right", fill="y")

        # ── Controls ──────────────────────────────────────────────────────
        control_row = tk.Frame(container, bg=styles.BG_APP)
        control_row.pack(fill="x", pady=(4, 2))

        self._undo_btn = tk.Button(
            control_row,
            text="Undo Selected Run",
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief=tk.RAISED,
            state="disabled",
            cursor="hand2",
            command=self.confirm_and_undo,
        )
        self._undo_btn.pack(side="left", padx=(0, 8))

        tk.Button(
            control_row,
            text="Refresh",
            font=styles.FONT_BUTTON,
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            relief=tk.RAISED,
            cursor="hand2",
            command=self.refresh,
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            control_row,
            text="Help",
            font=styles.FONT_BUTTON,
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            relief=tk.RAISED,
            cursor="hand2",
            command=self._open_help,
        ).pack(side="left")

        self._status_label = tk.Label(
            container,
            text="",
            font=styles.FONT_CAPTION,
            bg=styles.BG_APP,
            fg=styles.FG_SUB,
        )
        self._status_label.pack(anchor="w", pady=(4, 0))


def main() -> None:
    """Entry point used by the ``Undo_Tag_Edits.pyw`` launcher."""
    from .app_bootstrap import configure_logging

    configure_logging("undo_tag_edits")
    from .styles import bootstrap_theme

    root = tk.Tk()
    bootstrap_theme()
    UndoTagEditsApp(root)
    root.mainloop()
