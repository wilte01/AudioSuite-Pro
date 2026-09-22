"""
Tkinter UI for Tag Field Updater.

Provides the graphical user interface for scanning and updating tag fields.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

from ..core.processor import ProcessingStats, TagProcessor

logger = logging.getLogger(__name__)


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
        button_frame.grid(row=4, column=0, pady=10)

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

        thread = threading.Thread(target=self._scan_thread, args=(directory,))
        thread.daemon = True
        thread.start()

    def _scan_thread(self, directory: str) -> None:
        """Worker thread: runs the directory scan and schedules finish on completion.

        Args:
            directory: Root directory path passed to :class:`TagProcessor`.
        """
        try:
            with active_batch("tag_field_updater", "tag_edit"):
                self.processor.scan_directory(
                    directory, progress_callback=self._on_progress
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

    def run(self) -> None:
        """Enter the Tkinter main event loop."""
        self.root.mainloop()


def main(directory: str | None = None) -> None:
    """Main entry point for the Tag Field Updater application.

    Args:
        directory: Optional path to pre-populate the directory field and
            start scanning immediately on launch.
    """
    app = TagFieldUpdaterApp(tk.Tk())

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
