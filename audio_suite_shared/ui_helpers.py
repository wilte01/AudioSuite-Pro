"""
ui_helpers.py — Shared UI helper functions for Audio Suite applications.

Provides standardized implementations for common UI operations:
- Folder browsing dialogs with error handling
- Help guide opening
- Log file opening
- Output folder opening

This reduces code duplication across all 19 Audio Suite applications.

Changed in 2.7.0: adds :func:`open_licence_viewer` and
``UIHelperMixin._open_licences_standard``, so the licence texts the installer
stages can be read from the app (Help > Licences) instead of by browsing the
install folder.
"""

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any, Optional

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

from . import licences, platform_utils, suite_config

logger = logging.getLogger(f"audio_suite.{__name__}")


def show_error_from_exception(exc: Exception, title: str = "Error") -> None:
    """
    Display a user-friendly error dialog from any exception.

    Maps the exception to the nearest :class:`AudioSuiteError` and shows a
    message box using the standardized user-facing phrasing, so every tool
    presents the same style of error dialog for the same error type.

    Args:
        exc: The exception to display to the user.
        title: Dialog title; defaults to "Error".
    """
    mapped = map_to_audio_error(exc)
    logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
    messagebox.showerror(title, user_message_for(mapped))


def browse_folder_dialog(
    title: str,
    initial_dir: str = "",
    error_logger: Any = None,
    save_last_dir: bool = True,
    path_variable: Any = None,
) -> Optional[str]:
    """
    Standardized folder browsing dialog with enhanced error handling.

    Args:
        title: Dialog title
        initial_dir: Starting directory for the dialog
        error_logger: Error logger instance for error reporting
        save_last_dir: Whether to save the selected directory as last used
        path_variable: Tkinter StringVar to set with the selected path

    Returns:
        Selected folder path or None if cancelled
    """
    try:
        folder = filedialog.askdirectory(title=title, initialdir=initial_dir or "")
        if folder:
            # Validate directory exists
            if not os.path.exists(folder):
                error_msg = f"The selected directory does not exist:\n{folder}"
                messagebox.showerror("Invalid Directory", error_msg)
                return None

            if not os.path.isdir(folder):
                error_msg = f"The selected path is not a directory:\n{folder}"
                messagebox.showerror("Invalid Directory", error_msg)
                return None

            # Set the path variable if provided
            if path_variable:
                path_variable.set(folder)

            # Save as last directory if requested
            if save_last_dir:
                suite_config.save_last_directory(folder)

            return folder
        return None
    except (OSError, PermissionError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        error_msg = f"Failed to browse for folder:\n{user_message_for(mapped)}"
        messagebox.showerror("Browse Error", error_msg)
        return None


def open_help_guide(
    help_guide_filename: str, current_file_path: Optional[str] = None
) -> None:
    """
    Open the help guide document for the application.

    Args:
        help_guide_filename: Name of the help guide file
        current_file_path: Path to the current application file (no longer used)
    """
    try:
        platform_utils.open_help(help_guide_filename)
    except (OSError, PermissionError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Help Guide Error",
            f"Failed to open help guide:\n{user_message_for(mapped)}",
        )


def open_log_file(log_path: str) -> None:
    """
    Open the log file for viewing.

    Args:
        log_path: Path to the log file to open
    """
    try:
        if log_path and os.path.exists(log_path):
            platform_utils.open_path(log_path)
        else:
            messagebox.showinfo("Log File", "No log file available yet.")
    except (OSError, PermissionError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Log File Error", f"Failed to open log file:\n{user_message_for(mapped)}"
        )


def open_folder_path(folder_path: str) -> None:
    """
    Open a folder in the system file manager.

    Args:
        folder_path: Path to the folder to open
    """
    try:
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Output folder not available.")
    except (OSError, PermissionError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Folder Error", f"Failed to open folder:\n{user_message_for(mapped)}"
        )


#: Cap on how much of one licence the viewer renders. The LGPL text is about
#: 27 kB and the provenance record a few kB, so this only bounds a pathological
#: file; it is not a pagination scheme.
_MAX_LICENCE_CHARS = 400_000


def open_licence_viewer(parent: Any) -> tk.Toplevel:
    """Show this installation's licence texts in a read-only window.

    The window lists what the copy actually ships and renders the selected
    document, so a user can read the licence of anything the product bundles
    without knowing the install layout or a filename. Nothing is editable, and
    the text is read on selection rather than up front, so a large licence
    cannot slow the window's construction.

    Args:
        parent: The window that owns the new one. A standalone window is opened
            when it is ``None``, which keeps the helper usable from a test or a
            future CLI-driven launch.

    Returns:
        The ``tk.Toplevel`` that was created, so a caller can raise or close it.
    """
    documents = licences.licence_documents()

    window = tk.Toplevel(parent) if parent is not None else tk.Toplevel()
    window.title("Licences")
    window.geometry("860x560")
    window.minsize(620, 400)
    if parent is not None:
        window.transient(parent)

    body = tk.Frame(window, padx=10, pady=10)
    body.pack(fill="both", expand=True)

    listing = tk.Frame(body)
    listing.pack(side="left", fill="y")
    listbox = tk.Listbox(listing, width=28, exportselection=False)
    listbox.pack(fill="y", expand=True)
    for document in documents:
        listbox.insert("end", document.title)

    text_frame = tk.Frame(body)
    text_frame.pack(side="left", fill="both", expand=True, padx=(10, 0))
    scrollbar = tk.Scrollbar(text_frame)
    scrollbar.pack(side="right", fill="y")
    viewer = tk.Text(
        text_frame,
        wrap="word",
        state="disabled",
        padx=8,
        pady=8,
        yscrollcommand=scrollbar.set,
    )
    viewer.pack(side="left", fill="both", expand=True)
    scrollbar.config(command=viewer.yview)

    def _render(index: int) -> None:
        text = licences.read_licence(documents[index], limit=_MAX_LICENCE_CHARS)
        viewer.config(state="normal")
        viewer.delete("1.0", "end")
        viewer.insert("1.0", text)
        viewer.config(state="disabled")

    def _on_select(_event: object) -> None:
        selected = listbox.curselection()
        if selected:
            _render(selected[0])

    listbox.bind("<<ListboxSelect>>", _on_select)

    if documents:
        listbox.selection_set(0)
        _render(0)
    else:
        viewer.config(state="normal")
        viewer.insert("1.0", licences.missing_message())
        viewer.config(state="disabled")

    buttons = tk.Frame(window, padx=10)
    buttons.pack(fill="x", pady=(0, 10))

    def _open_externally() -> None:
        selected = listbox.curselection()
        if not selected:
            return
        try:
            platform_utils.open_path(str(documents[selected[0]].path))
        except OSError as exc:
            show_error_from_exception(exc, "Licences")

    tk.Button(
        buttons,
        text="Open in default app",
        command=_open_externally,
        state="normal" if documents else "disabled",
    ).pack(side="left")
    tk.Button(buttons, text="Close", command=window.destroy).pack(side="right")

    window.lift()
    return window


class UIHelperMixin:
    """
    Mixin class that provides common UI helper methods for Audio Suite applications.

    Applications can inherit from this mixin to get standardized UI functionality
    without duplicating code.
    """

    def _browse_folder_standard(
        self,
        title: str = "Select Folder",
        path_variable: Any = None,
        save_last_dir: bool = True,
    ) -> None:
        """Standard folder browsing with error handling."""
        initial_dir = ""
        if path_variable:
            initial_dir = path_variable.get()

        browse_folder_dialog(
            title=title,
            initial_dir=initial_dir,
            error_logger=getattr(self, "error_logger", None),
            save_last_dir=save_last_dir,
            path_variable=path_variable,
        )

    def _open_help_standard(self, help_guide_filename: str) -> None:
        """Standard help guide opening."""
        open_help_guide(help_guide_filename, None)

    def _open_log_standard(self) -> None:
        """Standard log file opening."""
        log_path = getattr(self, "_log_path", "")
        open_log_file(log_path)

    def _open_folder_standard(self) -> None:
        """Standard folder opening."""
        folder_path = getattr(self, "_out_dir", "")
        open_folder_path(folder_path)

    def _open_licences_standard(self) -> None:
        """Show this installation's licence texts (Help > Licences)."""
        open_licence_viewer(getattr(self, "root", None))
