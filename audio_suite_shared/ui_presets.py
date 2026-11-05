"""ui_presets.py - the shared preset list, save and delete helpers.

Split out of :mod:`audio_suite_shared.ui_common` in 2.4.3 (WP-9); the facade
re-exports each name, so existing importers are unchanged.

Changed in 2.4.3: split out of ``audio_suite_shared.ui_common``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

import json
import tkinter as tk
from tkinter import ttk
from typing import Callable

from . import styles


def load_preset_names(list_key: str) -> list[str]:
    """Load stored preset names from the shared config.

    Args:
    list_key: The ``suite_config`` key holding the JSON-serialised
    list of preset names (e.g. ``"bpm_presets_list"``).

    Returns:
    The deserialised name list, or an empty list when no entry exists.
    """
    from audio_suite_shared import suite_config

    raw = suite_config.load_value(list_key, None)
    names_json: str | None = raw if isinstance(raw, str) else None
    return json.loads(names_json) if names_json else []


def save_preset_dialog(
    combo: ttk.Combobox,
    on_save: Callable[[str], None] | None,
) -> None:
    """Open the shared "Save Preset" modal dialog.

    Args:
        combo:   The preset combobox the saved name is written back to.
        on_save: Callback invoked with the typed name when the user confirms;
            None turns the dialog into a no-op confirmation.
    """
    dialog = tk.Toplevel(combo.winfo_toplevel())
    dialog.title("Save Preset")
    dialog.geometry("350x150+400+300")
    dialog.transient(combo.winfo_toplevel())
    dialog.grab_set()
    tk.Label(dialog, text="Preset Name:", font=styles.FONT_BODY).pack(pady=(15, 5))
    name_var = tk.StringVar(dialog)
    entry = tk.Entry(dialog, textvariable=name_var, font=styles.FONT_BODY, width=40)
    entry.pack(padx=20, pady=5)
    entry.focus_set()

    def _do_save() -> None:
        name = name_var.get().strip()
        if name and on_save is not None:
            on_save(name)
            combo.set(name)
        dialog.destroy()

    entry.bind("<Return>", lambda _event: _do_save())
    tk.Button(
        dialog,
        text="Save",
        command=_do_save,
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
    ).pack(pady=10)


def delete_preset_action(
    combo: ttk.Combobox,
    on_delete: Callable[[str], None] | None,
) -> None:
    """Confirm then delete the preset currently selected in the combobox.

    Args:
        combo:     The preset combobox holding the selection.
        on_delete: Callback invoked with the preset name once the user
                   confirms the delete prompt.
    """
    name = combo.get()
    if not name:
        return

    from tkinter import messagebox

    if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
        if on_delete is not None:
            on_delete(name)
        combo.set("")
