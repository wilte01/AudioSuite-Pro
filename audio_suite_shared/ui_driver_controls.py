"""
ui_driver_controls.py — Reusable "Run Controls" strip for tool GUIs.

Mirrors the Master Driver's control strip (master_driver.ui_panels.
build_control_strip) so every program launched by the driver displays
the inherited source directory and control options in exactly the
same way, regardless of which tool is running.

Two launch modes are supported:

* **Driven** (launched via the Master Driver): the caller populates the
  bound variables from the parsed CLI arguments and locks the panel via
  :meth:`DriverControlsPanel.set_driven(True)` — values remain visible
  but cannot be changed inside the child.

* **Standalone** (launched directly): Source/Browse, Mode and Auto End
  stay editable; Auto Start is greyed out because auto-start can only
  be requested by the driver; Clear Logs / Parallel are driver-only
  orchestration options and are permanently inert.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from . import styles

_MODES = ("Dry Run", "Live Update")


class DriverControlsPanel(tk.Frame):
    """Source + control-options strip that mirrors the Master Driver UI.

    Args:
        parent: Parent widget to pack/grid this frame into.
        source_var: ``StringVar`` holding the source directory path.
        mode_var: ``StringVar`` holding ``"Dry Run"`` or ``"Live Update"``.
        auto_start_var: ``BooleanVar`` mirroring the driver's Auto Start.
        auto_end_var:      ``BooleanVar`` mirroring the driver's Auto End.
        on_browse: Optional callback for the Browse button (e.g. the
            app's browse-and-scan handler). Omitted → button hidden.
        bg: Background colour; defaults to the suite's white content
            background used inside tool setup tabs.
        clear_logs_var: Optional ``BooleanVar`` so the inert Clear Logs
            checkbox can mirror the state the driver passed via CLI.
        parallel_var: Optional ``BooleanVar`` so the inert Parallel
            checkbox can mirror the state the driver passed via CLI.
        modes: The two mode labels offered by the Mode dropdown. Tools
            with domain-specific wording (e.g. ``"Dry Run (Simulated)"``)
            pass their exact CLI ``--mode`` choices here so the panel
            displays and binds the same strings the driver emits.
    """

    def __init__(
        self,
        parent: tk.Widget,
        source_var: tk.StringVar,
        mode_var: tk.StringVar,
        auto_start_var: tk.BooleanVar,
        auto_end_var: tk.BooleanVar,
        on_browse: Callable[[], None] | None = None,
        browse_text: str = "Browse...",
        bg: str | None = None,
        clear_logs_var: tk.BooleanVar | None = None,
        parallel_var: tk.BooleanVar | None = None,
        modes: tuple[str, str] = _MODES,
    ) -> None:
        super().__init__(
            parent, bg=styles.BG_WHITE if bg is None else bg, padx=10, pady=8
        )
        self._bg = styles.BG_WHITE if bg is None else bg

        # ── Source directory bar (same construction as Master Driver) ────
        tk.Label(
            self,
            text="Source Music Directory:",
            font=styles.FONT_BODY_B,
            fg=styles.FG_MAIN,
            bg=self._bg,
        ).pack(anchor="w")

        dir_row = tk.Frame(self, bg=self._bg)
        dir_row.pack(fill="x", pady=(2, 0))

        self.source_entry = tk.Entry(
            dir_row,
            textvariable=source_var,
            font=styles.FONT_LABEL,
            bg=self._bg,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            disabledforeground=styles.FG_SUB,
        )
        self.source_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))

        self.browse_btn: tk.Button | None = None
        if on_browse is not None:
            self.browse_btn = tk.Button(
                dir_row,
                text=browse_text,
                bg=styles.get_main(),
                fg="white",
                font=styles.FONT_BUTTON,
                command=on_browse,
            )
            self.browse_btn.pack(side=tk.RIGHT)

        # ── Control options strip (driver order and spacings) ────────────
        strip = tk.Frame(self, bg=self._bg)
        strip.pack(fill="x", pady=(8, 0))
        # Public handle so callers can merge extra options (e.g. the Master
        # Driver's SELECT ALL) into the same single strip row.
        self.control_strip = strip

        tk.Label(
            strip,
            text="Mode:",
            font=styles.FONT_BODY_B,
            fg=styles.FG_MAIN,
            bg=self._bg,
        ).grid(row=0, column=0, sticky="e", padx=(0, 5))

        self.mode_combo = ttk.Combobox(
            strip,
            textvariable=mode_var,
            values=list(modes),
            state="readonly",
            font=styles.FONT_BODY,
            width=max(12, max(len(m) for m in modes)),
        )
        self.mode_combo.grid(row=0, column=1)

        self.auto_start_btn = self._make_checkbutton(
            strip, "Auto Start", auto_start_var
        )
        self.auto_start_btn.grid(row=0, column=2, padx=(20, 10))

        self.auto_end_btn = self._make_checkbutton(strip, "Auto End", auto_end_var)
        self.auto_end_btn.grid(row=0, column=3, padx=(0, 10))

        self.clear_logs_btn = self._make_checkbutton(
            strip, "Clear Logs", clear_logs_var
        )
        self.clear_logs_btn.grid(row=0, column=4, padx=(0, 10))
        self.clear_logs_btn.config(state="disabled")

        self.parallel_btn = self._make_checkbutton(strip, "Parallel", parallel_var)
        self.parallel_btn.grid(row=0, column=5, padx=(0, 10))
        self.parallel_btn.config(state="disabled")

        tk.Label(
            strip,
            text="(driver only)",
            font=styles.FONT_CAPTION_I,
            fg=styles.FG_SUB,
            bg=self._bg,
        ).grid(row=0, column=6, sticky="w", padx=(4, 0))

    # ── Internal helpers ─────────────────────────────────────────────────

    def _make_checkbutton(
        self, parent: tk.Widget, text: str, var: tk.BooleanVar | None
    ) -> tk.Checkbutton:
        """Create a Checkbutton styled to match the Master Driver strip."""
        options: dict[str, object] = {
            "font": styles.FONT_BODY,
            "bg": self._bg,
            "fg": styles.FG_MAIN,
            "activeforeground": styles.FG_MAIN,
            "activebackground": self._bg,
            "selectcolor": self._bg,
            "disabledforeground": styles.FG_SUB,
        }
        if var is not None:
            options["variable"] = var
        return tk.Checkbutton(parent, text=text, **options)  # type: ignore[arg-type]

    # ── Public API ───────────────────────────────────────────────────────

    def set_driven(self, driven: bool) -> None:
        """Switch the panel between driver-launched and standalone states.

        Args:
            driven: ``True`` after a Master Driver launch — every widget
                is locked so the inherited arguments stay read-only.
                ``False`` for a standalone launch — Source/Browse, Mode
                and Auto End become editable while Auto Start stays
                greyed out (it can only be issued by the driver).
        """
        if driven:
            self.source_entry.config(state="disabled")
            if self.browse_btn is not None:
                self.browse_btn.config(state="disabled")
            self.mode_combo.config(state="disabled")
            self.auto_end_btn.config(state="disabled")
        else:
            self.source_entry.config(state="normal")
            if self.browse_btn is not None:
                self.browse_btn.config(state="normal")
            self.mode_combo.config(state="readonly")
            self.auto_end_btn.config(state="normal")
        # Auto Start is driver-owned in both modes; Clear Logs and
        # Parallel are permanently inert orchestration options.
        self.auto_start_btn.config(state="disabled")
        self.clear_logs_btn.config(state="disabled")
        self.parallel_btn.config(state="disabled")
