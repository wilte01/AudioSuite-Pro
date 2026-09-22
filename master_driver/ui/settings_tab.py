"""
settings_tab.py — Builds the ⚙ Settings tab content.

Provides palette selection. The chosen palette is written to
audio_suite_config.json and takes effect when each tool is next launched.
"""

import tkinter as tk

from audio_suite_shared import styles

from ..state.app_state import AppState
from .cards import palette_card, theme_card, typography_card

# Locate suite root (file → ui/ → master_driver/ → tool_root/ → suite_root/)


_NOTE_FG = "#999999"


def build(parent: tk.Frame, state: "AppState") -> None:
    """
    Build the Settings tab content into *parent*.
    state must have a `palette_var` tk.StringVar.
    """
    # Derive Save button colours from the active palette — app.py has already
    # called styles.apply_styles() so ttk widgets are correctly styled.
    _SAVE_BTN_BG = styles.get_main()
    _SAVE_BTN_HOVER = styles.get_dark()

    outer = tk.Frame(parent, bg=styles.BG_APP)
    outer.pack(fill="both", expand=True)

    canvas = tk.Canvas(outer, bg=styles.BG_APP, highlightthickness=0)
    scrollbar = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas, bg=styles.BG_APP)

    scroll_frame.bind(
        "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=10)
    scrollbar.pack(side="right", fill="y", padx=(0, 5))

    # Stretch scroll_frame to fill the full canvas width
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

    # ── Collapsible cards ─────────────────────────────────────────────────────
    palette_card.build(scroll_frame, state)
    theme_card.build(scroll_frame, state)
    typography_card.build(scroll_frame, state)

    # ── Footer note + Save button ───────────────────────────────────────────
    footer_frame = tk.Frame(scroll_frame, bg=styles.BG_APP)
    footer_frame.pack(fill="x", pady=20, padx=2)

    footer = tk.Frame(
        footer_frame,
        bg=styles.BG_LIGHT,
        padx=20,
        pady=14,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    footer.pack(fill="x")

    tk.Label(
        footer,
        text="⚠  Changes take effect when each tool is next opened.",
        font=styles.FONT_BODY,
        fg=_NOTE_FG,
        bg=styles.BG_LIGHT,
    ).pack(side="left", anchor="w")

    save_btn: tk.Button = tk.Button(
        footer,
        text="  Save  ",
        font=styles.FONT_LABEL_B,
        bg=_SAVE_BTN_BG,
        fg="white",
        relief="flat",
        bd=0,
        padx=16,
        pady=6,
        cursor="hand2",
        command=lambda: _save_palette(state),
    )
    save_btn.pack(side="right")

    def _on_enter(_e: object) -> None:
        save_btn.config(bg=_SAVE_BTN_HOVER)

    def _on_leave(_e: object) -> None:
        save_btn.config(bg=_SAVE_BTN_BG)

    save_btn.bind("<Enter>", _on_enter)
    save_btn.bind("<Leave>", _on_leave)

    canvas.bind(
        "<MouseWheel>",
        lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
    )


def _save_palette(state: "AppState") -> None:
    """Persist the chosen palette and show confirmation."""
    import tkinter.messagebox as mb

    from audio_suite_shared import suite_config

    suite_config.save_app_state(state)

    mb.showinfo(
        "Settings Saved",
        f"Palette set to '{state.palette_var.get()}'.\n"
        f"Font set to '{state.font_family_var.get()}'.\n\n"
        "These changes will take effect when each tool is next opened.",
    )
