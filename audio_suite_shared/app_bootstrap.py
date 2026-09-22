"""
app_bootstrap.py — Minimal standardized bootstrap for Audio Suite tool apps.

Provides a single helper that applies the window setup, theme, palette,
error logger, and ttk style initialisation shared by every tool in the
suite.  Tools remain free to override or skip steps via keyword arguments.

configure_logging() is the only addition to the original file.
It has no tkinter dependency and is safe to call before tk.Tk() exists.
"""

import logging
import logging.handlers
import os
import sys
import tempfile
import threading
import tkinter as tk
from pathlib import Path
from queue import Queue
from tkinter import messagebox, ttk
from types import TracebackType

from . import platform_utils, styles, suite_config
from .cli_helpers import UniversalCLIHandler
from .error_logger import ErrorLogger, get_logger
from .ui_helpers import UIHelperMixin

# ---------------------------------------------------------------------------
# configure_logging — the only addition to the original file
# ---------------------------------------------------------------------------

_HOOK_MARKER = "_audio_suite_hook"


def _log_uncaught(
    level: int,
    message: str,
    exc_type: type[BaseException],
    exc_value: BaseException | None,
    exc_tb: TracebackType | None,
) -> None:
    """Write an uncaught exception (with traceback) to the audio_suite log."""
    logger = logging.getLogger("audio_suite")
    if exc_value is None:
        logger.log(level, "%s: %s", message, exc_type.__name__)
        return
    logger.log(level, message, exc_info=(exc_type, exc_value, exc_tb))


def _log_fatal_exception(
    exc_type: type[BaseException],
    exc_value: BaseException,
    exc_tb: TracebackType | None,
) -> None:
    """Route an uncaught exception into the audio_suite log.

    Installed as ``sys.excepthook`` so crashes are captured in
    audio_suite.log even when running under pythonw (no console).
    """
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    _log_uncaught(logging.CRITICAL, "Uncaught exception", exc_type, exc_value, exc_tb)


_log_fatal_exception._audio_suite_hook = True  # type: ignore[attr-defined]


def _log_thread_exception(args: threading.ExceptHookArgs) -> None:
    """Route an uncaught worker-thread exception into the audio_suite log."""
    thread_name = args.thread.name if args.thread is not None else "unknown"
    _log_uncaught(
        logging.CRITICAL,
        f"Uncaught exception in thread {thread_name}",
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )


_log_thread_exception._audio_suite_hook = True  # type: ignore[attr-defined]


def _install_excepthooks() -> None:
    """Install fatal-exception hooks once (idempotent via marker attribute)."""
    if getattr(sys.excepthook, _HOOK_MARKER, False) is not True:
        sys.excepthook = _log_fatal_exception
    if getattr(threading.excepthook, _HOOK_MARKER, False) is not True:
        threading.excepthook = _log_thread_exception


def configure_logging(program_name: str) -> None:
    """
    Configure the root audio_suite logger for the current process.

    Call this once, early in each .pyw launcher, after setup_sys_path()
    but before import tkinter.  Subsequent calls are safe but do nothing
    (the handler guard prevents duplicate handlers being registered).

    Writes to <suite_root>/logs/audio_suite.log with rotation:
    2 MB per file, 5 backup files (10 MB total on disk).

    Also installs sys.excepthook / threading.excepthook so uncaught
    exceptions (including their tracebacks) are written to the log —
    without this they only reach stderr, which is lost under pythonw.

    Args:
        program_name: Short identifier for the startup log entry,
                      e.g. "bpm_analyzer".
    """
    suite_root = Path(__file__).parent.parent
    logs_dir = suite_root / "logs"

    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        logs_dir = Path(tempfile.gettempdir()) / "audio_suite_logs"
        logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / "audio_suite.log"

    root_logger = logging.getLogger("audio_suite")
    root_logger.setLevel(logging.DEBUG)

    if not root_logger.handlers:
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s  %(name)-40s  %(levelname)-8s  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root_logger.addHandler(handler)

    root_logger.info("=== %s started ===", program_name)
    _install_excepthooks()


# ---------------------------------------------------------------------------
# Everything below is the original file — unchanged
# ---------------------------------------------------------------------------


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
        self.error_logger, self.style = bootstrap_tool_app(
            root, title, window_key, logger_name
        )

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
