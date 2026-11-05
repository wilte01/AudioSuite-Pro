"""ui_dialogs.py - the themed modal dialog used across the suite.

Split out of :mod:`audio_suite_shared.ui_common` in 2.4.3 (WP-9); the facade
re-exports :func:`show_message`, so existing importers are unchanged.

Changed in 2.4.3: split out of ``audio_suite_shared.ui_common``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

import logging
import threading
import tkinter as tk
from typing import cast

from . import styles

_log = logging.getLogger(f"audio_suite.{__name__}")


def _build_header(
    parent: tk.Toplevel, title: str, icon: str, icon_color: str
) -> tk.Frame:
    """Build the coloured header section of a show_message dialog.

    Args:
        parent: The dialog ``Toplevel``.
        title: The dialog title (also displayed in the header).
        icon: A short icon string prepended to the title.
        icon_color: Foreground colour for the icon/title label.

    Returns:
        The header ``Frame``.
    """
    header_bg = styles.get_main()
    header = tk.Frame(parent, bg=header_bg, pady=15)
    header.pack(fill="x")
    tk.Label(
        header,
        text=f"{icon}  {title}",
        font=styles.FONT_HEADER,
        bg=header_bg,
        fg=icon_color,
    ).pack()
    return header


def _build_content(parent: tk.Toplevel, message: str) -> tk.Frame:
    """Build the message-body section of a show_message dialog.

    Args:
        parent: The dialog ``Toplevel``.
        message: The text to display.

    Returns:
        The content ``Frame``.
    """
    content = tk.Frame(parent, bg=styles.BG_WHITE, padx=30, pady=30)
    content.pack(fill="both", expand=True)
    tk.Label(
        content,
        text=message,
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        wraplength=340,
        justify=tk.CENTER,
    ).pack(fill="both", expand=True)
    return content


def _build_action_row(parent: tk.Toplevel) -> tk.Button:
    """Build the OK button row of a show_message dialog.

    Binds hover effects and keyboard shortcuts (Return/Escape) to dismiss
    the dialog.

    Args:
        parent: The dialog ``Toplevel``.

    Returns:
        The OK ``Button`` (for external binding if needed).
    """
    btn_frame = tk.Frame(parent, bg=styles.BG_WHITE)
    btn_frame.pack(fill="x", pady=(0, 20))
    ok_btn = tk.Button(
        btn_frame,
        text="OK",
        width=15,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        command=parent.destroy,
        relief=tk.FLAT,
        bd=0,
    )
    ok_btn.pack()

    def _on_enter(_e: object) -> None:
        ok_btn["bg"] = styles.get_dark()

    def _on_leave(_e: object) -> None:
        ok_btn["bg"] = styles.get_main()

    ok_btn.bind("<Enter>", _on_enter)
    ok_btn.bind("<Leave>", _on_leave)
    parent.bind("<Return>", lambda _e: parent.destroy())
    parent.bind("<Escape>", lambda _e: parent.destroy())
    return ok_btn


def show_message(
    parent: tk.Misc,
    title: str,
    message: str,
    icon: str = "\u2139",
    icon_color: str = "#ffffff",
) -> None:
    """Show a themed modal dialog box with a coloured header.

    The dialog honours the suite palette, centres itself over *parent*,
    and closes on OK, Return, or Escape.  A warning is logged when
    called from a non-main thread (the dialog must be created on the
    main thread).

    Args:
        parent: The parent widget the dialog is transient to.
        title: Window title and header text.
        message: Body text displayed in the content area.
        icon: A short string prepended to the header title
            (default ``ℹ``).
        icon_color: Foreground colour for the header icon/title
            (default ``#ffffff``).
    """
    if threading.current_thread() is not threading.main_thread():
        _log.warning(
            "show_message() called from non-main thread - this is a bug. "
            "Use root.after(0, ...) to schedule dialog on the main thread."
        )
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=styles.BG_WHITE)
    dialog.resizable(False, False)
    dialog.transient(cast("tk.Wm", parent))
    dialog.attributes("-topmost", True)

    dialog.grab_set()

    dialog.update_idletasks()
    w = 400
    h = 240

    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw // 2) - (w // 2)
        y = py + (ph // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")
    except (OSError, tk.TclError) as _exc:
        _log.debug("Could not centre dialog: %s", _exc)
        dialog.geometry(f"{w}x{h}")

    _build_header(dialog, title, icon, icon_color)
    _build_content(dialog, message)
    _build_action_row(dialog)

    dialog.wait_window()
