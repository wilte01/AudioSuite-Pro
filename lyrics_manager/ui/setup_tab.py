"""
setup_tab.py
Builds the Setup tab widgets for Lyrics Manager.
Receives parent frame and tk variables; returns a dict of widgets.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame, load_preset_names

from ..core.providers import get_provider_names


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    provider: tk.StringVar,
    request_timeout: tk.StringVar,
    skip_existing: tk.BooleanVar,
    plain_fallback: tk.BooleanVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    driver_locked: bool = False,
    parallel_mode: tk.BooleanVar | None = None,
    max_workers: tk.IntVar | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Args:
        parent:            The tab Frame to populate.
        folder_path:       StringVar bound to folder entry.
        run_mode:          StringVar for Dry Run / Live Update combobox.
        provider:          StringVar holding the selected lyric provider.
        request_timeout:   StringVar holding the per-request timeout seconds.
        skip_existing:     BooleanVar for the skip-already-tagged toggle.
        plain_fallback:    BooleanVar for the store-unsynced-lyrics toggle.
        auto_start_var:    BooleanVar bound to the Auto Start checkbox.
        auto_end_var:      BooleanVar bound to the Auto End checkbox.
        clear_logs_var:    Tk variable mirroring the driver's Clear Logs
                           state (checkbox stays inert).
        parallel_var:      Tk variable mirroring the driver's Parallel
                           state (checkbox stays inert).
        on_browse:         Callback for Browse button.
        on_start:          Callback for Begin button.
        driver_locked:     True when launched via the Master Driver; locks
                           the Run Controls panel to inherited values.
        parallel_mode:     BooleanVar for the tool-specific parallel
                           processing toggle (functional worker setting).
        max_workers:       IntVar for worker count.
        on_preset_selected: Name-taking callback for preset selection.
        on_save_preset:    Name-taking callback for Save Preset button.
        on_delete_preset:  Name-taking callback for Delete Preset button.

    Returns:
        Dict with keys: start_btn (tk.Button), preset_combo (ttk.Combobox),
        refresh_preset_list (Callable[[], None]), controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="Lyrics Manager",
        start_text="BEGIN LYRIC LOOKUP",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        preset_loader=lambda: load_preset_names("lyrics_presets_list"),
        on_preset_selected=on_preset_selected,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        provider=provider,
        request_timeout=request_timeout,
        skip_existing=skip_existing,
        plain_fallback=plain_fallback,
        parallel_mode=parallel_mode,
        max_workers=max_workers,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Lyrics Manager Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        provider: tk.StringVar,
        request_timeout: tk.StringVar,
        skip_existing: tk.BooleanVar,
        plain_fallback: tk.BooleanVar,
        parallel_mode: tk.BooleanVar | None = None,
        max_workers: tk.IntVar | None = None,
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._provider = provider
        self._request_timeout = request_timeout
        self._skip_existing = skip_existing
        self._plain_fallback = plain_fallback
        self._parallel_mode = parallel_mode
        self._max_workers = max_workers
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # --- Lyric source (provider) ---
        tk.Label(
            self,
            text="Lyric Source:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        provider_combo = ttk.Combobox(
            self,
            textvariable=self._provider,
            state="readonly",
            values=get_provider_names(),
            font=styles.FONT_BODY,
            width=25,
        )
        provider_combo.pack(anchor="w", pady=5)
        tk.Label(
            self,
            text="(Files are matched by their artist and title tags)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # --- Request timeout ---
        tk.Label(
            self,
            text="Request Timeout (seconds):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        tk.Entry(
            self,
            textvariable=self._request_timeout,
            width=10,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(anchor="w", pady=5)

        # --- Skip existing lyrics ---
        tk.Checkbutton(
            self,
            text="Skip files that already have lyrics",
            variable=self._skip_existing,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY_B,
        ).pack(anchor="w", pady=(15, 0))
        tk.Label(
            self,
            text="(Most tracks already contain lyrics; untick to overwrite)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # --- Plain-text fallback ---
        tk.Checkbutton(
            self,
            text="Store unsynced lyrics when no synced lyrics are available",
            variable=self._plain_fallback,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY_B,
        ).pack(anchor="w", pady=(15, 0))
        tk.Label(
            self,
            text=(
                "(Plain text is stored via USLT / LYRICS / \u00a9lyr; "
                "M4A/MP4 cannot hold synced LRC text)"
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # --- Parallel processing (tool-specific worker setting) ---
        if self._parallel_mode is not None and self._max_workers is not None:
            self.add_parallel_row(
                self._parallel_mode,
                self._max_workers,
                "(ThreadPoolExecutor for concurrent network lookups)",
            )
