"""
app_bootstrap.py — Minimal standardized bootstrap for Audio Suite tool apps.

Provides a single helper that applies the window setup, theme, palette,
error logger, and ttk style initialisation shared by every tool in the
suite.  Tools remain free to override or skip steps via keyword arguments.

configure_logging() lives in audio_suite_shared.logging_setup, which is
Tk-free so the headless CLI can configure the same suite logging without
importing tkinter; it is re-exported here so the .pyw launchers keep
their original import path.
"""

import logging
import os
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from types import TracebackType

from . import platform_utils, styles, suite_config
from .cli_helpers import UniversalCLIHandler
from .error_logger import ErrorLogger, get_logger
from .logging_setup import _log_uncaught
from .logging_setup import configure_logging as configure_logging
from .ui_helpers import UIHelperMixin


def bootstrap_tool_app(
    root: tk.Tk,
    title: str,
    window_config_key: str,
    logger_name: str,
    width: int = 850,
    height: int = 950,
    apply_ttk_styles: bool = True,
) -> tuple[ErrorLogger, ttk.Style | None]:
    """
    Standardised initialisation sequence for a single Audio Suite tool.

    Returns a 2-tuple ``(error_logger, style)`` so the caller can store
    the objects on ``self`` (or ``self._root`` / ``self.style`` etc.)
    exactly as it did before.

    Parameters
    ----------
    root:
        The Tkinter root window.
    title:
        Window title passed to ``root.title()``.
    window_config_key:
        Config key used by ``platform_utils.setup_window`` for saved
        geometry / position.
    logger_name:
        Program name passed to ``get_logger``.
    width, height:
        Default window dimensions (default 850×950).
    apply_ttk_styles:
        If ``True`` (default), creates a ``ttk.Style`` and applies the
        suite palette via ``styles.apply_styles``.  Set to ``False``
        for tools that need custom style overrides (e.g. CD Ripper).

    Returns
    -------
    tuple[ErrorLogger, ttk.Style | None]
    """
    root.title(title)
    platform_utils.setup_window(root, width, height, suite_config, window_config_key)

    error_logger = get_logger(logger_name)
    error_logger.set_root(root)

    def _log_tk_callback_exception(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        """Log exceptions raised inside Tkinter callbacks (lost to stderr
        under pythonw by default)."""
        _log_uncaught(
            logging.ERROR,
            "Uncaught exception in Tkinter callback",
            exc_type,
            exc_value,
            exc_tb,
        )

    root.report_callback_exception = _log_tk_callback_exception

    styles.set_theme_mode(suite_config.load_theme_mode())
    styles.set_active_palette(suite_config.load_palette())
    styles.set_active_typography(
        suite_config.load_font_family(), suite_config.load_font_sizes()
    )

    root.configure(bg=styles.BG_APP)

    if apply_ttk_styles:
        style = ttk.Style()
        styles.apply_styles(style)
    else:
        style = None

    return error_logger, style


class BaseSuiteApp(UIHelperMixin):
    """
    Standardized base class for all Audio Suite tool applications.
    Consolidates logging, theming, threading pool management, and CLI logic.
    """

    def __init__(
        self,
        root: tk.Tk,
        title: str,
        window_key: str,
        logger_name: str,
        help_guide: str = "",
        num_workers: int = 4,
    ):
        self.root = root
        self.help_guide = help_guide
        self.num_workers = num_workers

        # 1. Standard Initialisation (Theming, Logging, Window)
        self.error_logger, _ = bootstrap_tool_app(root, title, window_key, logger_name)

        # 2. Standard Processing State
        self._log_path: str = ""
        self.auto_end: bool = False
        self.auto_start: bool = False

        # 3. Standard Worker Pool (for parallel processing)
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(num_workers)]
        self.slot_queue: Queue[int] = Queue()
        for i in range(num_workers):
            self.slot_queue.put(i)

        # 4. Standard CLI Handler
        self.cli_handler = UniversalCLIHandler(self)

    # ── Standard Helpers ──────────────────────────────────────────────────

    def _open_help(self) -> None:
        """Open the application help guide."""
        if self.help_guide:
            self._open_help_standard(self.help_guide)

    def _open_log(self) -> None:
        """Open the application processing log."""
        self._open_log_standard()

    def _open_folder(self) -> None:
        """
        Open the output folder.
        Child classes should set self._out_dir or override this.
        """
        folder_path = getattr(self, "_out_dir", "")
        if not folder_path and hasattr(self, "folder_path"):
            folder_path = self.folder_path.get()

        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Target folder not available.")

    def _on_error(self, message: str) -> None:
        """Standard error callback."""
        messagebox.showerror("Error", message)
        if hasattr(self, "start_btn"):
            self.start_btn.config(state="normal")
