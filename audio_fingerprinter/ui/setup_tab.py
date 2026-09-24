"""
setup_tab.py — Setup tab for Audio Fingerprinter.

Opens with the shared DriverControlsPanel mirroring the Master Driver's
source bar and control strip, followed by AcoustID-specific options: the
API key (encrypted persistence), lookup toggle, tag-writing toggle, score
threshold, fpcalc max-length, and the fpcalc binary path.
"""

import tkinter as tk
from typing import Any, Callable, cast

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None,
    parallel_var: tk.BooleanVar | None,
    lookup_enabled: tk.BooleanVar,
    write_tags: tk.BooleanVar,
    album_mode: tk.BooleanVar,
    threshold: tk.StringVar,
    max_length: tk.StringVar,
    fpcalc_path: tk.StringVar,
    api_key: tk.StringVar,
    api_key_status: tk.StringVar,
    on_browse: Callable[[], None] | None,
    on_browse_fpcalc: Callable[[], None] | None,
    on_save_api_key: Callable[[], None] | None,
    on_clear_api_key: Callable[[], None] | None,
    on_start: Callable[..., Any],
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Returns:
        Dict with keys: start_btn, fpcalc_status_label, update_fpcalc_status,
        controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="Audio Fingerprinter",
        start_text="START FINGERPRINTING",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        pady=15,
        title_pady=(0, 10),
        start_side=None,
        lookup_enabled=lookup_enabled,
        write_tags=write_tags,
        album_mode=album_mode,
        threshold=threshold,
        max_length=max_length,
        fpcalc_path=fpcalc_path,
        api_key=api_key,
        api_key_status=api_key_status,
        on_browse_fpcalc=on_browse_fpcalc,
        on_save_api_key=on_save_api_key,
        on_clear_api_key=on_clear_api_key,
    )
    return {
        "start_btn": frame.start_btn,
        "fpcalc_status_label": frame.fpcalc_status_label,
        "update_fpcalc_status": frame.update_fpcalc_status,
        "controls_panel": frame.controls_panel,
    }


class _SetupFrame(BaseSetupFrame):
    """Audio Fingerprinter Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        lookup_enabled: tk.BooleanVar,
        write_tags: tk.BooleanVar,
        album_mode: tk.BooleanVar,
        threshold: tk.StringVar,
        max_length: tk.StringVar,
        fpcalc_path: tk.StringVar,
        api_key: tk.StringVar,
        api_key_status: tk.StringVar,
        on_browse_fpcalc: Callable[[], None] | None,
        on_save_api_key: Callable[[], None] | None,
        on_clear_api_key: Callable[[], None] | None,
        **kwargs: Any,
    ) -> None:
        self._lookup_enabled_var = lookup_enabled
        self._write_tags_var = write_tags
        self._album_mode_var = album_mode
        self._threshold_var = threshold
        self._max_length_var = max_length
        self._fpcalc_path_var = fpcalc_path
        self._api_key_var = api_key
        self._api_key_status_var = api_key_status
        self._on_browse_fpcalc = on_browse_fpcalc
        self._on_save_api_key = on_save_api_key
        self._on_clear_api_key = on_clear_api_key
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # ── fpcalc binary ─────────────────────────────────────────────────────
        tk.Label(
            self,
            text="fpcalc Binary (auto-detected if empty):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        bin_frame = tk.Frame(self, bg=styles.BG_WHITE)
        bin_frame.pack(fill="x", pady=3)
        tk.Entry(
            bin_frame,
            textvariable=self._fpcalc_path_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))
        tk.Button(
            bin_frame,
            text="Browse",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=cast("Callable[..., Any]", self._on_browse_fpcalc),
        ).pack(side=tk.RIGHT)

        self._fpcalc_status = tk.Label(
            self,
            text="",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=700,
        )
        self._fpcalc_status.pack(anchor="w")

        # ── AcoustID API key ──────────────────────────────────────────────────
        tk.Label(
            self,
            text="AcoustID API Key:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        key_frame = tk.Frame(self, bg=styles.BG_WHITE)
        key_frame.pack(fill="x", pady=3)
        tk.Entry(
            key_frame,
            textvariable=self._api_key_var,
            show="*",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))
        tk.Button(
            key_frame,
            text="Save Key",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=cast("Callable[..., Any]", self._on_save_api_key),
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(
            key_frame,
            text="Clear",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=cast("Callable[..., Any]", self._on_clear_api_key),
        ).pack(side=tk.RIGHT)

        tk.Label(
            self,
            textvariable=self._api_key_status_var,
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=700,
        ).pack(anchor="w")
        tk.Label(
            self,
            text=(
                "Get a free application key by registering an application at "
                "https://acoustid.org/my-applications (the key shown at "
                "acoustid.org/api-key is the per-user key, only for fingerprint "
                "submission). Keys are stored encrypted in the suite config; the "
                "ACOUSTID_API_KEY environment variable overrides the stored value."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=700,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 0))

        # ── Lookup + write options ────────────────────────────────────────────
        tk.Checkbutton(
            self,
            text="Look up tracks in the AcoustID database",
            variable=self._lookup_enabled_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        tk.Checkbutton(
            self,
            text="Write AcoustID tags to matched files (requires Live Update)",
            variable=self._write_tags_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=2)
        tk.Checkbutton(
            self,
            text=(
                "Album Match — cluster each folder's lookups by MusicBrainz "
                "release group; tag only when the album is decided "
                "(ambiguous albums are left untagged)"
            ),
            variable=self._album_mode_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
            wraplength=700,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=2)

        row = tk.Frame(self, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=(8, 0))

        tk.Label(
            row,
            text="Min Score:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Entry(
            row,
            textvariable=self._threshold_var,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(
            row,
            text="Max Length (sec):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Entry(
            row,
            textvariable=self._max_length_var,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)

        def update_fpcalc_status(text: str, ok: bool) -> None:
            self._fpcalc_status.config(
                text=text, fg=styles.get_main() if ok else "#cc0000"
            )

        self.update_fpcalc_status = update_fpcalc_status
        self.fpcalc_status_label = self._fpcalc_status
