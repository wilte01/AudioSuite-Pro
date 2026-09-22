"""
picker_dialog.py — Thread-safe modal artwork image picker.

The picker MUST run on the main tkinter thread.
show_threadsafe() is called from a background thread and blocks it
(via threading.Event) until the user accepts or rejects an image.

Candidates are received pre-filtered and quality-ranked from the API
modules, so they are shown in resolution order with mismatched album
names already removed.
"""

# ── Standard library imports ─────────────────────────────────────────────────
import io
import logging
import threading
import tkinter as tk
from typing import Optional

# ── Third-party imports ─────────────────────────────────────────────────────
import requests
from PIL import Image, ImageTk

# ── Shared-library imports ───────────────────────────────────────────────────
from audio_suite_shared import styles

# ── Local imports ────────────────────────────────────────────────────────────
from ..api.session import http
from ..config.settings import CONFIG
from ..core.ranker import RankedCandidate

logger = logging.getLogger(__name__)


class PickerDialog:
    """
    Modal image browser.
    Instantiate once and call show_threadsafe() from any thread.
    """

    def __init__(self, root: tk.Tk) -> None:
        self._root = root

    def show_threadsafe(
        self, items: list[RankedCandidate], artist: str, engine: str
    ) -> Optional[bytes]:
        """
        Schedule the picker on the main thread and block the calling thread
        until the user makes a choice.

        *items* is a pre-filtered, quality-ranked list of candidates.
        Returns selected image bytes, or None if rejected/closed.
        """
        result_holder: list[Optional[bytes]] = [None]
        done = threading.Event()

        def _run_on_main() -> None:
            result_holder[0] = self._show(items, artist, engine)
            done.set()

        self._root.after(0, _run_on_main)
        done.wait()
        return result_holder[0]

    def _show(
        self, items: list[RankedCandidate], artist: str, engine: str
    ) -> Optional[bytes]:
        """Build and display the picker Toplevel (main thread only)."""
        selected_data: list[Optional[bytes]] = [None]
        user_confirmed = tk.BooleanVar(value=False)
        idx = [0]

        def render(i: int) -> None:
            try:
                r = http.get(items[i].url, timeout=CONFIG["REQUEST_TIMEOUT"])
                r.raise_for_status()
                selected_data[0] = r.content
                assert selected_data[0] is not None
                img = Image.open(io.BytesIO(selected_data[0]))
                img.thumbnail((320, 320))
                tk_img = ImageTk.PhotoImage(img)
                lbl_img.config(image=tk_img)
                setattr(lbl_img, "image", tk_img)
                lbl_info.config(
                    text=(
                        f"{engine}: {items[i].title} "
                        f"({items[i].width}×{items[i].height}) "
                        f"({i + 1}/{len(items)})"
                    )
                )
            except requests.Timeout:
                lbl_info.config(text="Timeout loading image.")
            except requests.RequestException as exc:
                lbl_info.config(text=f"Network error: {exc}")
            except Exception as exc:
                logger.exception("Picker render error")
                lbl_info.config(text=f"Error: {exc}")

        win = tk.Toplevel(self._root)
        win.title(f"Select Artwork: {engine}")
        win.geometry("450x600")
        win.grab_set()
        # Handle window-manager close (X button) the same as REJECT
        win.protocol("WM_DELETE_WINDOW", win.destroy)

        lbl_img = tk.Label(win, bg="#eee", width=320, height=320, font=styles.FONT_BODY)
        lbl_img.pack(pady=10)
        lbl_info = tk.Label(win, text="Loading...", font=styles.FONT_BODY)
        lbl_info.pack()

        nav_f = tk.Frame(win)
        nav_f.pack(pady=10)

        def _nav_prev() -> None:
            idx[0] = max(0, idx[0] - 1)
            render(idx[0])

        def _nav_next() -> None:
            idx[0] = min(len(items) - 1, idx[0] + 1)
            render(idx[0])

        tk.Button(
            nav_f,
            text=" < ",
            font=styles.FONT_BUTTON,
            command=_nav_prev,
        ).pack(side=tk.LEFT, padx=5)
        tk.Button(
            nav_f,
            text=" > ",
            font=styles.FONT_BUTTON,
            command=_nav_next,
        ).pack(side=tk.LEFT, padx=5)

        act_f = tk.Frame(win)
        act_f.pack(pady=20)

        def _accept() -> None:
            user_confirmed.set(True)
            win.destroy()

        tk.Button(
            act_f,
            text="ACCEPT",
            bg=styles.get_main(),
            fg="white",
            width=12,
            font=styles.FONT_BUTTON,
            command=_accept,
        ).pack(side=tk.LEFT, padx=10)
        tk.Button(
            act_f,
            text="REJECT",
            bg="#666",
            fg="white",
            width=12,
            font=styles.FONT_BUTTON,
            command=win.destroy,
        ).pack(side=tk.LEFT, padx=10)

        render(0)
        self._root.wait_window(win)

        if user_confirmed.get():
            return selected_data[0]
        return None
