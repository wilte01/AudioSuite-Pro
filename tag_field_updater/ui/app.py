"""
Tkinter UI for Tag Field Updater.

Provides the graphical user interface for scanning and updating tag fields.

Changed in 1.0.1: parses the driver's argv and adds a Dry Run checkbox wired to the CLI
mode.

Changed in 1.2.0: records the files a scan skipped (unsupported format or no
readable tags) and the ones it could not update as the run's note, so a Master
Driver batch reports them on the Tag Field Updater step instead of only in the
completion dialog and the run log.
Changed in 2.2.0: the filename source (functional backlog F-01) — a pattern
box, the only-fill-blanks switch and saved action groups.  Turning the mode on
checks Dry Run, so the default is the CLI's default and unchecking it is the
explicit decision to write.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.run_outcome import record_caveats, shortfall

from ..core.filename_patterns import DEFAULT_PATTERNS, PatternError
from ..core.processor import ProcessingStats, TagProcessor
from ..utils import cli_args
from ..utils import config as action_config

logger = logging.getLogger(__name__)

#: Manifest id the Master Driver keys this tool's batch step by; a note
#: recorded under any other key is never read.  Locked to the manifest by
#: ``tests/test_run_outcome_contract.py``.
DRIVER_TOOL_ID = "tag_field_updater"


class TagFieldUpdaterApp(BaseSuiteApp):
    """Tkinter GUI application for Tag Field Updater."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the application window, variables, and processor."""
        super().__init__(
            root,
            "Tag Field Updater",
            "tag_field_updater_window",
            "tag_field_updater",
        )

        # Variables
        self.directory = tk.StringVar()
        self.dry_run = tk.BooleanVar(value=False)
        self.filename_mode = tk.BooleanVar(value=False)
        self.only_fill_blanks = tk.BooleanVar(value=True)
        self.action_group = tk.StringVar()
        self.scanning = tk.BooleanVar(value=False)
        self.current_file = tk.StringVar()
        self.processed_count = tk.IntVar(value=0)
        self.updated_count = tk.IntVar(value=0)
        self.error_count = tk.IntVar(value=0)

        # Statistics
        self.stats: ProcessingStats = ProcessingStats()

        # Initialize processor
        self.processor = TagProcessor()

        self.setup_ui()

    def setup_ui(self) -> None:
        """Build and layout all UI widgets."""
        # Main frame
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Directory selection
        dir_frame = ttk.LabelFrame(
            main_frame, text="Music Library Directory", padding="5"
        )
        dir_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Entry(dir_frame, textvariable=self.directory, width=60).grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5)
        )
        ttk.Button(dir_frame, text="Browse...", command=self.browse_directory).grid(
            row=0, column=1
        )
        ttk.Checkbutton(
            dir_frame,
            text="Dry Run (no changes written)",
            variable=self.dry_run,
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))

        # Info frame
        info_frame = ttk.LabelFrame(
            main_frame, text="Tag Fields to Update", padding="5"
        )
        info_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        info_text = """Tag Fields to Update:

TXXX Fields (Custom):
\u2022 TXXX/ALBUMARTISTGENRE - Album Artist Genre
\u2022 TXXX/ALBUMGENRE - Album Genre
\u2022 TXXX/ARTISTGENRE - Artist Genre

Standard ID3 Fields:
\u2022 TIT1 - Content Group Description
\u2022 TCON - Genre

Rules:
\u2022 Replace '/' with '; ' in existing values
\u2022 DO NOT replace ' / ' (space slash space) - preserve as-is
\u2022 Scan directories recursively
\u2022 Only update if field exists and contains '/'
\u2022 Support MP3, FLAC, MP4, OGG, WMA, M4A formats
\u2022 Update TXXX fields: ALBUMARTISTGENRE, ALBUMGENRE, ARTISTGENRE
\u2022 Update standard ID3 fields: TIT1 (Content Group), TCON (Genre)"""

        ttk.Label(info_frame, text=info_text, justify=tk.LEFT).grid(
            row=0, column=0, sticky=(tk.W, tk.E)
        )

        self._build_filename_frame(main_frame)

        # Progress frame
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="5")
        progress_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(progress_frame, text="Current File:").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Label(progress_frame, textvariable=self.current_file).grid(
            row=0, column=1, sticky=(tk.W, tk.E), padx=(5, 0)
        )

        # Statistics frame
        stats_frame = ttk.LabelFrame(main_frame, text="Statistics", padding="5")
        stats_frame.grid(row=3, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Label(stats_frame, text="Files Processed:").grid(
            row=0, column=0, sticky=tk.W
        )
        ttk.Label(stats_frame, textvariable=self.processed_count).grid(
            row=0, column=1, sticky=tk.W, padx=(5, 0)
        )

        ttk.Label(stats_frame, text="Files Updated:").grid(row=1, column=0, sticky=tk.W)
        ttk.Label(stats_frame, textvariable=self.updated_count).grid(
            row=1, column=1, sticky=tk.W, padx=(5, 0)
        )

        ttk.Label(stats_frame, text="Errors:").grid(row=2, column=0, sticky=tk.W)
        ttk.Label(stats_frame, textvariable=self.error_count).grid(
            row=2, column=1, sticky=tk.W, padx=(5, 0)
        )

        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=5, column=0, pady=10)

        self.start_button = ttk.Button(
            button_frame, text="Start Scanning", command=self.start_scanning
        )
        self.start_button.grid(row=0, column=0, padx=(0, 5))

        self.stop_button = ttk.Button(
            button_frame, text="Stop", command=self.stop_scanning, state=tk.DISABLED
        )
        self.stop_button.grid(row=0, column=1, padx=5)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        status_bar = ttk.Label(
            self.root, textvariable=self.status_var, relief=tk.SUNKEN
        )
        status_bar.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=(0, 5))

    def _build_filename_frame(self, parent: ttk.Frame) -> None:
        """Build the filename-source controls (F-01).

        Args:
            parent: The main frame the section is gridded into.
        """
        frame = ttk.LabelFrame(parent, text="Tag from Filenames", padding="5")
        frame.grid(row=4, column=0, sticky=(tk.W, tk.E), pady=(0, 10))

        ttk.Checkbutton(
            frame,
            text="Tag from filenames (patterns below, one per line, tried in order)",
            variable=self.filename_mode,
            command=self._on_filename_mode_toggled,
        ).grid(row=0, column=0, columnspan=3, sticky=tk.W)

        self.patterns_text = tk.Text(frame, height=5, width=70, wrap=tk.NONE)
        self.patterns_text.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E))
        self.patterns_text.insert("1.0", "\n".join(DEFAULT_PATTERNS))

        ttk.Checkbutton(
            frame,
            text="Only fill blank tags (never overwrite an existing value)",
            variable=self.only_fill_blanks,
        ).grid(row=2, column=0, columnspan=3, sticky=tk.W)

        ttk.Label(frame, text="Action group:").grid(
            row=3, column=0, sticky=tk.W, pady=(4, 0)
        )
        self.group_combo = ttk.Combobox(
            frame, textvariable=self.action_group, state="readonly", width=28
        )
        self.group_combo.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(5, 5))
        self.group_combo["values"] = sorted(action_config.load_action_groups())

        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, columnspan=3, sticky=tk.W, pady=(4, 0))
        ttk.Button(buttons, text="Load", command=self.load_action_group).grid(
            row=0, column=0, padx=(0, 5)
        )
        ttk.Button(buttons, text="Save as...", command=self.save_action_group).grid(
            row=0, column=1
        )

    def _on_filename_mode_toggled(self) -> None:
        """Make the filename mode dry by default.

        A filename parse is a guess about a naming convention: a wrong split
        writes plausible wrong tags, and the file looks tagged afterwards.  So
        enabling the mode checks Dry Run, and writing is an explicit untick.
        """
        if self.filename_mode.get():
            self.dry_run.set(True)
            self.status_var.set(
                "Filename mode: dry run checked. Untick Dry Run to write the "
                "parsed values."
            )

    def _patterns_from_box(self) -> tuple[str, ...]:
        """Return the non-blank pattern lines in the box, in order.

        Returns:
            The patterns as typed; empty when the box is blank.
        """
        raw = self.patterns_text.get("1.0", "end").splitlines()
        return tuple(line.strip() for line in raw if line.strip())

    def load_action_group(self) -> None:
        """Fill the pattern box and write mode from the selected action group."""
        name = self.action_group.get().strip()
        if not name:
            return
        group = action_config.get_action_group(name)
        if group is None:
            messagebox.showwarning(
                "Action Group", f"Action group {name!r} is not saved any more."
            )
            self.group_combo["values"] = sorted(action_config.load_action_groups())
            return
        self.patterns_text.delete("1.0", "end")
        self.patterns_text.insert("1.0", "\n".join(group.patterns))
        self.only_fill_blanks.set(group.only_fill_blanks)
        self.filename_mode.set(True)
        self._on_filename_mode_toggled()
        self.status_var.set(f"Loaded action group {name!r}.")

    def save_action_group(self) -> None:
        """Save the pattern box's contents under a name the user chooses."""
        patterns = self._patterns_from_box()
        if not patterns:
            messagebox.showwarning(
                "Action Group", "Add at least one filename pattern first."
            )
            return
        name = simpledialog.askstring(
            "Save Action Group", "Name for this pattern set:", parent=self.root
        )
        if not name:
            return
        try:
            saved = action_config.save_action_group(
                name, patterns, only_fill_blanks=self.only_fill_blanks.get()
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Action Group", str(exc))
            return
        self.group_combo["values"] = sorted(action_config.load_action_groups())
        self.action_group.set(saved.name)
        self.status_var.set(f"Saved action group {saved.name!r}.")

    def browse_directory(self) -> None:
        """Open a directory chooser and populate the directory entry field."""
        directory = filedialog.askdirectory(title="Select Music Library Directory")
        if directory:
            self.directory.set(directory)

    def _on_progress(self, filename: str, stats: ProcessingStats) -> None:
        """Worker-thread callback: marshals a UI update onto the main thread.

        Uses ``root.after(0, ...)`` so that all Tkinter widget mutations
        happen on the main thread, preserving thread safety.

        Args:
            filename: Name of the file just processed.
            stats: Current accumulated :class:`ProcessingStats`.
        """
        self.root.after(
            0,
            self._apply_progress_update,
            filename,
            stats.processed_files,
            stats.updated_files,
            stats.error_files,
        )

    def _apply_progress_update(
        self,
        filename: str,
        processed: int,
        updated: int,
        errors: int,
    ) -> None:
        """Apply progress values to Tkinter variables on the main thread.

        Args:
            filename: Name of the file just processed.
            processed: Total files processed so far.
            updated: Total files updated so far.
            errors: Total error files so far.
        """
        self.current_file.set(filename)
        self.processed_count.set(processed)
        self.updated_count.set(updated)
        self.error_count.set(errors)

    def start_scanning(self) -> None:
        """Validate the selected directory and launch the scan worker thread."""
        directory = self.directory.get().strip()
        if not directory or not os.path.exists(directory):
            messagebox.showerror("Error", "Please select a valid directory.")
            return

        # Configure the source before the thread starts: a bad pattern is a
        # message here, not a half-tagged library later.
        if self.filename_mode.get():
            patterns = self._patterns_from_box()
            if not patterns:
                messagebox.showwarning(
                    "Filename Pattern",
                    "Add at least one filename pattern, or untick filename mode.",
                )
                return
            try:
                self.processor.use_filename_patterns(
                    patterns, only_fill_blanks=self.only_fill_blanks.get()
                )
            except PatternError as exc:
                messagebox.showerror("Filename Pattern", str(exc))
                return
        else:
            self.processor.use_filename_patterns(())

        # Reset statistics
        self.stats = ProcessingStats()

        self.processed_count.set(0)
        self.updated_count.set(0)
        self.error_count.set(0)

        # Update UI
        self.scanning.set(True)
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.status_var.set("Scanning...")

        dry_run = self.dry_run.get()
        thread = threading.Thread(target=self._scan_thread, args=(directory, dry_run))
        thread.daemon = True
        thread.start()

    def _scan_thread(self, directory: str, dry_run: bool) -> None:
        """Worker thread: runs the directory scan and schedules finish on completion.

        Args:
            directory: Root directory path passed to :class:`TagProcessor`.
            dry_run: When True, compute the rewrites and report them but
                persist nothing to disk.
        """
        try:
            with active_batch("tag_field_updater", "tag_edit"):
                self.processor.scan_directory(
                    directory, dry_run=dry_run, progress_callback=self._on_progress
                )
        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"directory": directory})
            logger.error(
                "[%s] Unhandled scan error: %s",
                type(mapped).__name__,
                user_message_for(mapped),
                exc_info=True,
            )
        finally:
            self.root.after(0, self.finish_scanning)

    def stop_scanning(self) -> None:
        """Request the processor to stop and update the status bar."""
        self.processor.stop()
        self.status_var.set("Stopping...")

    def finish_scanning(self) -> None:
        """Reset UI controls and display a completion summary dialog."""
        try:
            self.scanning.set(False)
            self.start_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.DISABLED)
            self.current_file.set("")

            stats = self.processor.stats
            # Recorded before the dialog: the batch report must not depend on a
            # Tk dialog succeeding, and the note is the durable half of this.
            self._record_run_note(stats)

            summary = (
                f"\nScan Complete!\n\n"
                f"Statistics:\n"
                f"\u2022 Files Processed: {stats.processed_files}\n"
                f"\u2022 Files Updated: {stats.updated_files}\n"
                f"\u2022 Files Skipped: {stats.skipped_files}\n"
                f"\u2022 Errors: {stats.error_files}\n\n"
                f"Log file created with detailed information.\n"
            )

            self.status_var.set("Scan Complete")
            messagebox.showinfo("Scan Complete", summary)

            logger.info(
                "Scan complete. Processed: %d, Updated: %d, Errors: %d",
                stats.processed_files,
                stats.updated_files,
                stats.error_files,
            )

        except Exception as exc:
            logger.error("Error in finish_scanning: %s", exc, exc_info=True)

    def _record_run_note(self, stats: ProcessingStats) -> None:
        """Record the files this scan skipped or could not update.

        The completion dialog and the run log carry the same counts; this is
        the one-line version the Master Driver reads after the window closes.
        A clean scan records nothing, which clears any earlier note.

        Args:
            stats: The finished scan's accumulated statistics.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(
                stats.error_files,
                stats.total_files,
                "file",
                "could not be updated",
            )
            if stats.error_files
            else "",
            shortfall(
                stats.skipped_files,
                stats.total_files,
                "file",
                "were skipped (unsupported format or no readable tags)",
            )
            if stats.skipped_files
            else "",
        )

    def run(self) -> None:
        """Enter the Tkinter main event loop."""
        self.root.mainloop()


def main(directory: str | None = None) -> None:
    """Main entry point for the Tag Field Updater application.

    Args:
        directory: Optional path to pre-populate the directory field and
            start scanning immediately on launch.  When ``None``, the
            Master-Driver / CLI argv is parsed instead (mirror
            ``Tag_Editor.pyw``).
    """
    if directory is None:
        args = parse_cli_args(cli_args.parse)
        directory = args.folder_path or None
        dry_run = not args.live_mode
    else:
        dry_run = False

    app = TagFieldUpdaterApp(tk.Tk())
    app.dry_run.set(dry_run)

    if directory:
        if not os.path.exists(directory):
            logger.error("Launch directory does not exist: %s", directory)
            sys.exit(1)
        if not os.path.isdir(directory):
            logger.error("Launch path is not a directory: %s", directory)
            sys.exit(1)

        app.directory.set(directory)
        app.start_scanning()

    app.run()
