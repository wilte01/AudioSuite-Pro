"""
ui/setup_tab.py
Setup tab for Audio Enhancer.

Changed in 1.0.1: fixed type annotation from tk.Event[ttk.Combobox] to
tk.Event for Python 3.11 compatibility (Event is not subscriptable in 3.11).

Matches the suite's established UI conventions:
  - tk.LabelFrame for configuration groups
  - ttk.Combobox (readonly) for enumerated choices
  - tk.Scale for numeric ranges (prevents invalid free-text entry)
  - Start button at the bottom, spanning full width
  - styles constants throughout (no hard-coded colours or fonts)

Changed in 1.1.0: added _SLIDER_SPECS/NUMERIC_DSP_FIELDS and
build_effect_controls; the Custom DSP panel now also renders the
Sprint 1 effect toggles.

Changed in 1.2.0: the Setup tab's two preset selectors ("Presets:" for saved
suite presets and "Enhancement Preset:" for the built-in DSP presets) became
one Preset control. They sat two rows apart, looked identical, and did
different things: one only changed DSP values, the other also restored paths
from suite storage. The single combobox lists the built-in presets first then
the saved ones behind a display-only divider, and a caption states which kind
is selected and, for a saved preset, which built-in preset it is running.

Changed in 1.2.0: the Custom DSP controls moved into a non-modal editor
window. The nineteen controls need 745 px on their own; stacked on the Setup
tab they pushed the tab to 1274 px against 887 px available at the shipped
880x980 window, so the lower half of the panel — and the BEGIN ENHANCEMENT
button, which BaseSetupFrame packs last — were clipped off-screen (the button
was not mapped at all, and maximising could not help: ~988 px of tab area on
a 1081 px-tall screen). The tab now keeps a one-line summary plus a
"Configure Custom DSP..." button, the editor owns the controls, and the start
button is packed before the options so it can never be clipped.
"""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Mapping
from tkinter import messagebox, ttk
from typing import Any, Callable, cast

from audio_suite_shared import styles, ui_common
from audio_suite_shared.dsp_models import PRESETS, EnhancementParams, PresetName
from audio_suite_shared.ui_common import BaseSetupFrame

#: Editor window sizing. The height is capped to the display so the dialog also
#: opens usably on a short screen, where its scroll region takes over.
_DIALOG_TITLE = "Custom DSP Parameters"
_DIALOG_WIDTH = 820
_DIALOG_HEIGHT = 900
_DIALOG_MIN_WIDTH = 640
_DIALOG_MIN_HEIGHT = 320

#: Built-in DSP presets, in selector order. These change DSP values only.
_BUILTIN_NAMES: tuple[str, ...] = tuple(p.value for p in PresetName)

#: Display-only divider between the built-in presets and the saved ones. The
#: selector handler restores the previous choice if it is picked, so it reads
#: as a heading rather than as a third kind of preset.
_SAVED_DIVIDER = "──────── saved presets ────────"

logger = logging.getLogger(__name__)


def build(
    parent: tk.Frame,
    source_path: tk.StringVar,
    output_path: tk.StringVar,
    preset_name: tk.StringVar,
    params: EnhancementParams,
    on_browse_src: Callable[..., Any],
    on_browse_out: Callable[..., Any],
    on_start: Callable[..., Any],
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
    preset_names: "list[str] | None" = None,
    on_save_preset: "Callable[[str], None] | None" = None,
    on_delete_preset: "Callable[[str], None] | None" = None,
    on_preset_selected: "Callable[[str], None] | None" = None,
) -> "tuple[tk.Button, Callable[..., Any] | None, dict[str, Any], CustomDspPanel]":
    """
    Populate the Setup tab.

    Returns (start_button, refresh_preset_list_fn, param_values, dsp_panel).

    The shared Run Controls panel (source bar, Mode, Auto Start/End, Clear
    Logs, Parallel) is rendered by BaseSetupFrame; the tool-specific Options
    section keeps only the output folder row plus the preset control and the
    Custom DSP summary row.
    All user-controllable values use constrained widgets (Scale, Combobox,
    Checkbutton) so that invalid values never reach the processing layer.

    ``param_values`` is the same dict the returned ``dsp_panel`` writes into:
    it is the single source of truth the worker builds ``EnhancementParams``
    from, so a run started before the editor has ever been opened still uses
    every field.
    """
    frame = _SetupFrame(
        parent,
        title="Audio Enhancer",
        start_text="BEGIN ENHANCEMENT",
        on_start=on_start,
        include_controls_panel=True,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        pady=20,
        folder_path=source_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse_src,
        driver_locked=driver_locked,
        source_path=source_path,
        output_path=output_path,
        preset_name=preset_name,
        params=params,
        on_browse_src=on_browse_src,
        on_browse_out=on_browse_out,
    )
    refresh = frame.refresh_preset_list if frame.preset_combo is not None else None
    return (
        cast(tk.Button, frame.start_btn),
        refresh,
        frame.param_values,
        frame.dsp_panel,
    )


def preset_values(preset: object) -> dict[str, Any]:
    """Return a preset's numeric DSP fields as a ``field -> value`` dict.

    The five effect toggles and ``karaoke_strength`` are deliberately excluded:
    a built-in preset supplies the 13 numeric fields and leaves the effects as
    the user set them (D13), so switching presets never silently drops a
    reverse/karaoke/phaser choice.

    Args:
        preset: Any object exposing the numeric DSP field names — the shared
            ``EnhancementParams``, the enhancer's or the refinery's copy.

    Returns:
        One entry per :data:`NUMERIC_DSP_FIELDS` field.
    """
    return {field: getattr(preset, field) for field in NUMERIC_DSP_FIELDS}


class CustomDspPanel:
    """The Custom DSP values plus the non-modal editor window that edits them.

    The 19 controls live in their own resizable window instead of on the Setup
    tab: at the shipped window size they overflowed the tab and pushed the
    primary action button out of the window entirely.

    ``values`` is the single source of truth shared with the application: the
    worker constructs ``EnhancementParams`` from it, and every control writes
    into it through its own trace. That is what lets the editor stay
    non-modal — you can drag a slider and press BEGIN ENHANCEMENT without a
    "commit" step, and nothing depends on the dialog being open when the run
    starts.

    Args:
        parent: Widget the summary row and the editor are parented to.
        params: Current parameters; every field seeds ``values``.
        preset_var: The tab's Enhancement Preset variable. The summary row is
            only shown while it reads ``Custom``.
        on_change: Optional callback invoked with a copy of ``values`` after
            every change, whether it came from a widget or from
            :meth:`apply_values`. Audio Refinery uses it to mirror the editor
            into its ``StageConfig``, which is what its pipeline runs on; the
            standalone enhancer passes nothing because ``values`` is already
            the dict its worker reads.
    """

    def __init__(
        self,
        parent: tk.Misc,
        params: EnhancementParams,
        preset_var: tk.StringVar,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._parent = parent
        self._preset_var = preset_var
        self._on_change = on_change
        #: Shared with the caller — never rebound, only updated in place.
        self._values: dict[str, Any] = {
            field: getattr(params, field)
            for field in EnhancementParams.__dataclass_fields__
        }
        self._widget_vars: dict[str, tk.Variable] = {}
        self._summary = tk.StringVar(master=parent, value=self._summary_text())
        self._row: tk.Frame | None = None
        self._row_visible = False
        self._dialog: tk.Toplevel | None = None
        self._canvas: tk.Canvas | None = None
        #: Slider rows by field name, in display order (empty while closed).
        self._row_frames: dict[str, tk.Frame] = {}
        #: Fields whose row is hidden — remembered while the editor is closed so
        #: a rebuild opens in the same state.
        self._hidden_fields: set[str] = set()

    # ── Public surface ────────────────────────────────────────────────────────

    @property
    def values(self) -> dict[str, Any]:
        """Live parameter values, keyed by ``EnhancementParams`` field name."""
        return self._values

    def build_row(self, parent: tk.Misc) -> tk.Frame:
        """Build the compact summary row shown on the Setup tab.

        The row itself is packed by :meth:`sync_preset`, which keeps it in step
        with the selected preset.

        Args:
            parent: Container the row is packed into.

        Returns:
            The packed-or-not row frame, for callers that need a handle.
        """
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        self._row = row
        tk.Label(
            row,
            textvariable=self._summary,
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
            justify="left",
        ).pack(fill="x")
        tk.Button(
            row,
            text="Configure Custom DSP\u2026",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            padx=12,
            pady=2,
            command=self.open,
        ).pack(anchor="w", pady=(6, 0))
        return row

    def open(self) -> tk.Toplevel:
        """Show the editor, building it on first use.

        The window is non-modal and there is never more than one: a second call
        raises the existing window instead of creating a duplicate.

        Returns:
            The live editor window.
        """
        if self._dialog is not None and self._dialog.winfo_exists():
            self._dialog.deiconify()
            self._dialog.lift()
            self._dialog.focus_set()
            return self._dialog
        self._dialog = self._build_dialog()
        # Raise the freshly built window too: a host window larger than the
        # editor (the Master Driver is 1040 px wide, the REFINE tab's stage a
        # part of it) can otherwise leave the first open behind it, which reads
        # as the pick having done nothing. Subsequent opens already lift.
        self._dialog.lift()
        return self._dialog

    def close(self) -> None:
        """Destroy the editor window; the values survive."""
        dialog, self._dialog = self._dialog, None
        self._widget_vars = {}
        self._row_frames = {}
        self._canvas = None
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()

    def is_open(self) -> bool:
        """Return True while the editor window exists."""
        return self._dialog is not None and bool(self._dialog.winfo_exists())

    def variable(self, field: str) -> tk.Variable | None:
        """Return the live control variable for *field*.

        Args:
            field: ``EnhancementParams`` field name.

        Returns:
            The ``DoubleVar``/``BooleanVar`` bound to that field, or ``None``
            when the editor is closed (no widgets exist to move).
        """
        return self._widget_vars.get(field)

    def set_field_visible(self, field: str, visible: bool) -> None:
        """Show or hide one numeric field's row.

        Audio Refinery hides Output Gain while its Normaliser stage owns the
        final level. The state is remembered even when the editor is closed, so
        the next open builds the row already hidden.

        Args:
            field: ``EnhancementParams`` field name.
            visible: False to remove the row from the layout.
        """
        if field not in _SLIDER_SPECS:
            return
        if visible:
            self._hidden_fields.discard(field)
        else:
            self._hidden_fields.add(field)
        self._apply_row_visibility()

    def _apply_row_visibility(self) -> None:
        """Re-pack the rows in display order, skipping the hidden ones."""
        for field, row in self._row_frames.items():
            if field in self._hidden_fields:
                row.pack_forget()
        for field, row in self._row_frames.items():
            if field not in self._hidden_fields:
                row.pack(fill="x", pady=1)

    def _notify_change(self, *_: object) -> None:
        """Hand the current values to the owner, if it asked for them.

        The values are re-read from the widgets instead of trusting
        ``self._values``: Tk runs a variable's write traces in reverse
        registration order, so this callback can fire before the builder's own
        trace has copied the new value into the dict.
        """
        if self._on_change is None:
            return
        for field, var in self._widget_vars.items():
            self._values[field] = var.get()
        self._on_change(dict(self._values))

    def apply_values(self, values: Mapping[str, Any]) -> None:
        """Adopt preset or saved-preset values in the dict and live controls.

        Args:
            values: Any mapping; keys that are not DSP fields (``source_path``,
                ``preset_name`` …) are ignored, so a saved preset can be passed
                straight through.
        """
        updated = {
            field: values[field]
            for field in EnhancementParams.__dataclass_fields__
            if field in values
        }
        if updated:
            self._values.update(updated)
            for field, var in self._widget_vars.items():
                if field in updated:
                    var.set(updated[field])
            self._summary.set(self._summary_text())
            self._notify_change()
        self.sync_preset()

    def sync_preset(self) -> None:
        """Show the summary row only while the Custom preset is selected.

        Closing the editor when another preset is picked keeps the window from
        outliving the state it edits; the values themselves are untouched, so
        switching back to Custom returns the user's settings.
        """
        if self._row is None:
            return
        visible = self._preset_var.get() == PresetName.CUSTOM.value
        if visible and not self._row_visible:
            self._row.pack(fill="x", pady=(6, 0))
        elif not visible and self._row_visible:
            self._row.pack_forget()
        if not visible:
            self.close()
        self._row_visible = visible

    # ── Internals ─────────────────────────────────────────────────────────────

    def _summary_text(self) -> str:
        return (
            f"{len(self._values)} parameters \u2014 edited in a separate window; "
            "changes apply immediately."
        )

    def _build_dialog(self) -> tk.Toplevel:
        dialog = tk.Toplevel(self._parent)
        dialog.title(_DIALOG_TITLE)
        dialog.configure(bg=styles.BG_WHITE)
        dialog.transient(self._parent.winfo_toplevel())
        dialog.protocol("WM_DELETE_WINDOW", self.close)
        dialog.minsize(_DIALOG_MIN_WIDTH, _DIALOG_MIN_HEIGHT)

        header = tk.Frame(dialog, bg=styles.BG_WHITE, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Custom DSP Parameters",
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            header,
            text=(
                "Changes apply immediately \u2014 press BEGIN ENHANCEMENT in the "
                "main window when you are happy with them."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        footer = tk.Frame(dialog, bg=styles.BG_WHITE, padx=16, pady=10)
        footer.pack(side=tk.BOTTOM, fill="x")
        tk.Button(
            footer,
            text="Close",
            command=self.close,
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            padx=20,
        ).pack(side=tk.RIGHT)

        # Scroll region: 745 px of controls fit the shipped display, but a
        # short screen or a large scaling factor must not hide any of them.
        holder = tk.Frame(dialog, bg=styles.BG_WHITE)
        holder.pack(fill="both", expand=True, padx=16, pady=(0, 4))
        canvas = tk.Canvas(holder, bg=styles.BG_WHITE, highlightthickness=0)
        scrollbar = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        body = tk.Frame(canvas, bg=styles.BG_WHITE)
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind(
            "<Configure>",
            lambda _event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfig(window_id, width=event.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")
        # A Toplevel binding receives events from every child (bindtags), so the
        # wheel stays scoped to this window — no bind_all to leak on close.
        dialog.bind("<MouseWheel>", self._on_mousewheel)

        # Build from the live values rather than the params object, so reopening
        # the editor never rewinds edits made in the previous session.
        snapshot = EnhancementParams(**self._values)
        # Slider rows live in their own frame so a hidden row can be restored
        # in the right place (all of that frame's children are slider rows, in
        # _SLIDER_SPECS order).
        sliders_frame = tk.Frame(body, bg=styles.BG_WHITE)
        sliders_frame.pack(fill="x")
        slider_vars, _ = build_dsp_sliders(sliders_frame, snapshot, values=self._values)
        effect_vars = build_effect_controls(body, snapshot, self._values)
        self._widget_vars = {**slider_vars, **effect_vars}
        rows = [
            child
            for child in sliders_frame.winfo_children()
            if isinstance(child, tk.Frame)
        ]
        self._row_frames = dict(zip(_SLIDER_SPECS, rows))
        for var in self._widget_vars.values():
            var.trace_add("write", self._notify_change)
        self._apply_row_visibility()
        self._canvas = canvas

        self._place_dialog(dialog)
        return dialog

    def _place_dialog(self, dialog: tk.Toplevel) -> None:
        dialog.update_idletasks()
        screen_w = dialog.winfo_screenwidth()
        screen_h = dialog.winfo_screenheight()
        width = min(_DIALOG_WIDTH, max(_DIALOG_MIN_WIDTH, screen_w - 80))
        height = min(_DIALOG_HEIGHT, max(_DIALOG_MIN_HEIGHT, screen_h - 120))
        anchor = self._parent.winfo_toplevel()
        x = anchor.winfo_rootx() + (anchor.winfo_width() - width) // 2
        y = anchor.winfo_rooty() + (anchor.winfo_height() - height) // 2
        x = max(0, min(x, screen_w - width))
        y = max(0, min(y, screen_h - height))
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    def _on_mousewheel(self, event: tk.Event) -> None:
        canvas = self._canvas
        if canvas is None or not canvas.winfo_exists():
            return
        region = canvas.bbox("all")
        if region is None or region[3] <= canvas.winfo_height():
            return  # everything fits — do not eat the wheel event
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


class _SetupFrame(BaseSetupFrame):
    """Audio Enhancer Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        source_path: tk.StringVar,
        output_path: tk.StringVar,
        preset_name: tk.StringVar,
        params: EnhancementParams,
        on_browse_src: Callable[..., Any],
        on_browse_out: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._source_path = source_path
        self._output_path = output_path
        self._preset_name = preset_name
        self._params = params
        self._on_browse_src = on_browse_src
        self._on_browse_out = on_browse_out
        self._param_values: dict[str, Any] = {}
        self._dsp_panel: CustomDspPanel | None = None
        # One combined preset selector: built-in DSP presets plus the saved
        # suite presets. ``_preset_name`` stays the built-in name (the CLI and
        # stored presets depend on that); this var is only what the combobox
        # displays, which may be a saved preset's name.
        self._preset_selection = tk.StringVar(master=parent)
        self._preset_hint = tk.StringVar(master=parent)
        self._saved_names: list[str] = []
        self._last_selection = ""
        self._delete_btn: tk.Button | None = None
        super().__init__(parent, **kwargs)

    # ── Accessors ─────────────────────────────────────────────────────────────

    @property
    def param_values(self) -> dict[str, Any]:
        """The shared parameter-values dict the worker reads."""
        return self._param_values

    @property
    def dsp_panel(self) -> CustomDspPanel:
        """The Custom DSP panel controller built by :meth:`_build_options`."""
        assert self._dsp_panel is not None, "DSP panel is built in _build_options"
        return self._dsp_panel

    # ── Layout ────────────────────────────────────────────────────────────────

    def _layout(self) -> None:
        """Standard skeleton order, with the start button's space booked first.

        BaseSetupFrame packs the start button last with ``side="bottom"``, so an
        over-tall options section claims the space first and pushes the button
        out of the window (measured: unmapped at the shipped 880x980 size in
        Custom mode). Packing it before the options reserves its strip up
        front, which keeps the primary action reachable however tall the
        options grow.
        """
        self._add_title()
        self._add_start_button()
        if self._include_controls_panel:
            self._add_controls_panel()
        self._add_preset_row()
        self._build_options()

    def _build_options(self) -> None:
        # ── Output path ───────────────────────────────────────────────────────
        # The shared Run Controls panel already renders the Source bar.
        ui_common.path_row(
            self,
            "Output folder (leave blank for auto):",
            self._output_path,
            self._on_browse_out,
        )

        # ── Preset control + Custom DSP entry point ───────────────────────────
        cfg = self.add_config_group("Configuration")
        self._build_preset_control(cfg)

        panel = CustomDspPanel(cfg, self._params, self._preset_name)
        self._dsp_panel = panel
        # The app's worker builds EnhancementParams from this exact dict.
        self._param_values = panel.values
        panel.build_row(cfg)

        # Initial state. A restored or CLI preset is displayed but never opens
        # the editor on its own (only a real click does).
        self._last_selection = self._preset_name.get()
        self._preset_selection.set(self._last_selection)
        self._sync_preset_hint()
        self._update_delete_state()
        panel.sync_preset()

    # ── The single preset control ─────────────────────────────────────────────

    def _add_preset_row(self) -> None:
        """Suppress BaseSetupFrame's saved-presets-only row.

        The shared row would be a second, near-identical combobox directly
        above the combined one — the duplication this control exists to remove.
        The combined control is built inside the Configuration group by
        :meth:`_build_preset_control`.
        """

    def _build_preset_control(self, parent: tk.Misc) -> None:
        """Build the one Preset selector: built-ins, then saved presets."""
        tk.Label(
            parent,
            text="Preset:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(fill="x", pady=(0, 3))

        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=3)

        combo = ttk.Combobox(
            row,
            textvariable=self._preset_selection,
            font=styles.FONT_BODY,
            state="readonly",
            width=28,
        )
        combo.pack(side=tk.LEFT)
        self.preset_combo = combo
        self.refresh_preset_list()

        tk.Button(
            row,
            text="Save",
            command=lambda: ui_common.save_preset_dialog(combo, self._save_preset),
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT, padx=(6, 3))

        self._delete_btn = tk.Button(
            row,
            text="Delete",
            command=self._delete_selected_preset,
            bg="#cc5555",
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        )
        self._delete_btn.pack(side=tk.LEFT)

        tk.Label(
            parent,
            textvariable=self._preset_hint,
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
            justify="left",
            wraplength=520,
        ).pack(fill="x")

        # NOTE: the handler is *_on_preset_pick* — BaseSetupFrame stores the
        # app's saved-preset loader as ``self._on_preset_selected`` on the
        # instance, so a method of that name would be shadowed.
        combo.bind("<<ComboboxSelected>>", self._on_preset_pick)
        self._preset_name.trace_add("write", self._on_preset_name_written)

    def _preset_values_list(self) -> list[str]:
        """Combobox values: built-in presets, then saved ones behind a divider."""
        values = list(_BUILTIN_NAMES)
        if self._saved_names:
            values.append(_SAVED_DIVIDER)
            values.extend(self._saved_names)
        return values

    def _is_saved(self, name: str) -> bool:
        return name in self._saved_names

    def _on_preset_name_written(self, *_: object) -> None:
        """Mirror a preset written in Python into the selector.

        ``preset_name`` is written by the CLI, by a restored saved preset and by
        the combobox itself. When a saved preset is what the user picked, the
        selector keeps showing its name while the caption reports the built-in
        preset it carries — so only mirror when no saved preset is displayed.
        """
        value = self._preset_name.get()
        if not self._is_saved(self._last_selection):
            if self._preset_selection.get() != value:
                self._preset_selection.set(value)
            self._last_selection = value
        self._sync_preset_hint()
        self._update_delete_state()

    def _on_preset_pick(self, _event: tk.Event | None = None) -> None:
        """Resolve a pick: built-in preset, saved preset, or the divider."""
        panel = self._dsp_panel
        value = self._preset_selection.get()

        if value == _SAVED_DIVIDER:
            # Display-only heading: put the real choice back.
            self._preset_selection.set(self._last_selection)
            return

        if value in _BUILTIN_NAMES:
            selected = PresetName(value)
            self._last_selection = value
            self._preset_name.set(value)  # trace syncs the caption
            if panel is not None:
                if selected == PresetName.CUSTOM:
                    panel.sync_preset()
                    # Only a real click opens the editor.
                    if _event is not None:
                        panel.open()
                else:
                    built_in = PRESETS.get(selected)
                    panel.apply_values(
                        {} if built_in is None else preset_values(built_in)
                    )
            self._sync_preset_hint()
            self._update_delete_state()
            return

        if self._is_saved(value):
            self._last_selection = value
            # A saved preset restores paths, preset_name and DSP values; the
            # app owns that storage, so hand it the name.
            if self._on_preset_selected is not None:
                self._on_preset_selected(value)
            self._sync_preset_hint()
            self._update_delete_state()

    def _sync_preset_hint(self) -> None:
        """State which kind of preset is selected and what it does."""
        selection = self._last_selection or self._preset_name.get()
        if self._is_saved(selection):
            self._preset_hint.set(
                "Saved preset — restores the paths and DSP values stored with "
                f"it (built-in preset: {self._preset_name.get()})."
            )
        elif selection == "":
            self._preset_hint.set("")
        elif selection == PresetName.CUSTOM.value:
            self._preset_hint.set(
                "Built-in preset — changes DSP values only; tune them in the "
                "Custom DSP window."
            )
        else:
            self._preset_hint.set("Built-in preset — changes DSP values only.")

    def _update_delete_state(self) -> None:
        """Delete applies to saved presets; a built-in has nothing to delete."""
        if self._delete_btn is None:
            return
        saved = self._is_saved(self._preset_selection.get())
        self._delete_btn.config(state="normal" if saved else "disabled")

    def _save_preset(self, name: str) -> None:
        """Persist the current settings under *name* and select it.

        The four built-in names are reserved: one selector cannot offer both a
        built-in preset and a saved preset of the same name, so accepting the
        name would create an entry that can never be picked.
        """
        if name in _BUILTIN_NAMES:
            messagebox.showwarning(
                "Preset Name Reserved",
                f'"{name}" is a built-in preset name.\n'
                "Choose a different name for this saved preset.",
            )
            return
        if self._on_save_preset is not None:
            self._on_save_preset(name)  # app saves, then refreshes the values
        self._last_selection = name
        self._preset_selection.set(name)
        self._sync_preset_hint()
        self._update_delete_state()

    def _delete_selected_preset(self) -> None:
        """Delete the selected saved preset, then fall back to its built-in."""
        name = self._preset_selection.get()
        if not self._is_saved(name) or self._on_delete_preset is None:
            return
        if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
            self._on_delete_preset(name)  # app deletes, then refreshes

    def refresh_preset_list(self, names: list[str] | None = None) -> None:
        """Reload the saved names into the combined selector.

        Args:
            names: Explicit replacement list; when None the preset_loader is
                tried first and the constructor preset_names last, matching
                :meth:`BaseSetupFrame.refresh_preset_list`.
        """
        if names is not None:
            self._saved_names = list(names)
        elif self._preset_loader is not None:
            self._saved_names = list(self._preset_loader())
        elif self._preset_names:
            self._saved_names = list(self._preset_names)

        # A preset saved under a built-in name (possible before this control
        # existed) can never be selected: the built-in owns that entry. Drop it
        # from the list rather than showing a choice that does nothing.
        shadowed = [name for name in self._saved_names if name in _BUILTIN_NAMES]
        if shadowed:
            logger.warning(
                "Ignoring saved preset(s) whose name is a built-in preset: %s",
                ", ".join(shadowed),
            )
            self._saved_names = [
                name for name in self._saved_names if name not in _BUILTIN_NAMES
            ]

        combo = self.preset_combo
        if combo is None:
            return
        combo["values"] = self._preset_values_list()
        current = self._preset_selection.get()
        if current and current not in combo["values"]:
            # A deleted preset: fall back to the built-in preset still in use
            # rather than leaving the selector blank.
            current = self._preset_name.get()
            self._preset_selection.set(current)
        if current != _SAVED_DIVIDER:
            self._last_selection = current
        self._sync_preset_hint()
        self._update_delete_state()


# ──────────────────────────────────────────────────────────────────────────────
# Public builders for reuse (e.g. in Audio Refinery)
# ──────────────────────────────────────────────────────────────────────────────


#: Numeric DSP fields rendered as ``tk.Scale`` widgets by
#: :func:`build_dsp_sliders`, keyed to ``(label, from, to, resolution)``.
#: This is the single source of truth for the slider set — the boolean effect
#: toggles (``reverse``/``karaoke``/``phaser``/``flanger``/``chorus``) are
#: rendered separately by :func:`build_effect_controls`.
_SLIDER_SPECS: dict[str, tuple[str, float, float, float]] = {
    "noise_gate_threshold_db": ("Noise Gate Threshold (dB)", -90.0, -40.0, 1.0),
    "compressor_threshold_db": ("Compressor Threshold (dB)", -40.0, -6.0, 0.5),
    "compressor_ratio": ("Compressor Ratio", 1.0, 10.0, 0.5),
    "compressor_attack_ms": ("Compressor Attack (ms)", 1.0, 50.0, 1.0),
    "compressor_release_ms": ("Compressor Release (ms)", 20.0, 500.0, 10.0),
    "low_shelf_gain_db": ("Low Shelf Gain (dB)", -6.0, 12.0, 0.5),
    "low_shelf_freq_hz": ("Low Shelf Freq (Hz)", 40.0, 400.0, 10.0),
    "presence_gain_db": ("Presence Gain (dB)", -6.0, 12.0, 0.5),
    "presence_freq_hz": ("Presence Freq (Hz)", 500.0, 8000.0, 100.0),
    "high_shelf_gain_db": ("High Shelf Gain (dB)", -6.0, 12.0, 0.5),
    "high_shelf_freq_hz": ("High Shelf Freq (Hz)", 2000.0, 16000.0, 500.0),
    "output_gain_db": ("Output Gain (dB)", -6.0, 18.0, 0.5),
    "limiter_threshold_db": ("Limiter Threshold (dB)", -12.0, -0.1, 0.1),
}

#: Field names (in display order) that :func:`build_dsp_sliders` renders as
#: numeric Scale widgets.
NUMERIC_DSP_FIELDS: tuple[str, ...] = tuple(_SLIDER_SPECS)

#: Boolean effect toggles rendered as ``tk.Checkbutton`` widgets by
#: :func:`build_effect_controls`, paired with their display label.
_EFFECT_TOGGLES: tuple[tuple[str, str], ...] = (
    ("reverse", "Reverse audio"),
    ("karaoke", "Karaoke (centre-vocal removal)"),
    ("phaser", "Phaser"),
    ("flanger", "Flanger"),
    ("chorus", "Chorus"),
)


def build_dsp_sliders(
    parent: tk.Frame,
    params: EnhancementParams,
    values: dict[str, Any] | None = None,
) -> tuple[dict[str, tk.DoubleVar], dict[str, Any]]:
    """
    Build Scale widgets for every numeric DSP parameter.

    Args:
        parent: Container frame to pack the rows into.
        params: Supplies each row's initial value unless *values* already
            holds one for that field.
        values: Optional existing dict to populate and share. Passing the
            caller's live values dict makes the widgets and the worker read the
            same object (the custom editor needs this to stay live while the
            window is open); omitted, a fresh dict is created and returned.

    Returns:
        ``(slider_vars, param_values)`` where *slider_vars* maps field names
        to ``tk.DoubleVar`` (for programmatic preset updates) and
        *param_values* is a mutable dict that stays in sync with slider
        movements so callers can construct a new ``EnhancementParams`` at any
        time via ``EnhancementParams(**param_values)``. Callers that also
        render effect controls should pass the same *param_values* dict to
        :func:`build_effect_controls` so a single ``EnhancementParams`` can be
        constructed from all 19 fields.
    """
    vars_: dict[str, tk.DoubleVar] = {}
    param_values: dict[str, Any] = values if values is not None else {}

    for field_name, (label, from_, to_, resolution) in _SLIDER_SPECS.items():
        initial = param_values.get(field_name, getattr(params, field_name))
        var = tk.DoubleVar(value=initial)
        vars_[field_name] = var
        param_values[field_name] = initial

        # Keep param_values dict in sync when slider moves
        def _make_trace(fn: str, v: tk.DoubleVar) -> Callable[..., None]:
            def _cb(*_: object) -> None:
                param_values[fn] = v.get()

            return _cb

        var.trace_add("write", _make_trace(field_name, var))

        ui_common.slider_row(parent, label, var, from_, to_, resolution)

    return vars_, param_values


def build_effect_controls(
    parent: tk.Frame,
    params: EnhancementParams,
    param_values: dict[str, Any],
) -> dict[str, tk.Variable]:
    """
    Build the Sprint 1 effect controls (D12/D17) inside a labelled sub-frame.

    Renders five boolean toggles (reverse, karaoke, phaser, flanger, chorus)
    plus the numeric ``karaoke_strength`` (0.0-1.0). Every widget writes into
    *param_values* (the same dict returned by :func:`build_dsp_sliders`) so a
    complete ``EnhancementParams(**param_values)`` can be constructed.

    Args:
        parent: Container frame to pack the effect sub-frame into.
        params: Current params — supplies each control's initial value unless
            *param_values* already holds one for that field.
        param_values: Mutable dict shared with :func:`build_dsp_sliders`;
            extended in place with the six effect field values.

    Returns:
        Mapping of effect field name -> Tk variable (BooleanVar for the
        toggles, DoubleVar for karaoke_strength).
    """
    frame = tk.LabelFrame(
        parent,
        text=" Effects ",
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        font=styles.FONT_CAPTION,
        padx=10,
        pady=8,
    )
    frame.pack(fill="x", pady=(6, 0))

    effect_vars: dict[str, tk.Variable] = {}

    for field_name, label in _EFFECT_TOGGLES:
        initial = bool(param_values.get(field_name, getattr(params, field_name)))
        bool_var = tk.BooleanVar(value=initial)
        param_values[field_name] = initial

        def _make_bool_trace(fn: str, v: tk.BooleanVar) -> Callable[..., None]:
            def _cb(*_: object) -> None:
                param_values[fn] = bool(v.get())

            return _cb

        bool_var.trace_add("write", _make_bool_trace(field_name, bool_var))
        tk.Checkbutton(
            frame,
            text=label,
            variable=bool_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            anchor="w",
        ).pack(fill="x", anchor="w")
        effect_vars[field_name] = bool_var

    strength = float(
        param_values.get("karaoke_strength", getattr(params, "karaoke_strength"))
    )
    strength_var = tk.DoubleVar(value=strength)
    param_values["karaoke_strength"] = strength

    def _strength_trace(*_: object) -> None:
        param_values["karaoke_strength"] = strength_var.get()

    strength_var.trace_add("write", _strength_trace)
    ui_common.slider_row(frame, "Karaoke Strength", strength_var, 0.0, 1.0, 0.05)
    effect_vars["karaoke_strength"] = strength_var

    return effect_vars
