"""
_card_base.py — Shared declarative implementation for the simple tool cards.

A "simple card" is the near-verbatim shell the Master Driver renders for a
tool-toggle module: a highlight-bordered outer frame, a header with the
toggle Checkbutton and the title, a collapsible body, and the
``▶/▼  Settings`` expand button. The body content is described as data
(:class:`SimpleCardSpec`) instead of hand-built widget code, so the card
files are specs over one ``build_simple_card()`` implementation
(iteration-7 B2, audit A3 family 2).

Cards whose body content does not fit the declarative row types use
:func:`build_card_shell`, which renders the shared outer/header/expand
shell and delegates the body to a caller-supplied builder callback.

Changed in 2.0.0: both shells report their body's open/closed state to an
optional ``on_card_expand`` hook on the frame they are built into, so the
Utilities tab can give the open card the full two-column width; and
``build_card_shell`` can render without a module checkbox, which is what the
Undo Tag Edits card needs (PLAN_feature_expansion.md D119).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk
from typing import TYPE_CHECKING, Any

from audio_suite_shared import styles

if TYPE_CHECKING:
    from ...state.app_state import AppState

_COLLAPSE_LABEL = "\u25b6  Settings"
_EXPAND_LABEL = "\u25bc  Settings"

#: Attribute a host frame exposes to learn that a card's body opened or closed.
_EXPAND_HOOK_ATTR = "on_card_expand"


def _expansion_hook(parent: tk.Misc) -> "Callable[[bool], None] | None":
    """Return the host frame's expansion hook, or ``None`` when it has none.

    The Utilities tab lays its cards out in a two-column grid and gives the
    card whose Settings are open the full width, so it has to reflow when a
    body opens or closes.  The hook lives on the frame the card is built into
    rather than in a parameter, so all thirty card files keep the same
    ``build(parent, state)`` signature they are discovered by.

    Args:
        parent: The frame the card was told to build into.

    Returns:
        A callable taking the new open state, or ``None`` for a plain frame
        (the card then behaves exactly as before).
    """
    hook = getattr(parent, _EXPAND_HOOK_ATTR, None)
    return hook if callable(hook) else None


# ── Body-row spec records ─────────────────────────────────────────────────────
#
# Each record declarative one widget row inside a card's collapsible body.


@dataclass(frozen=True)
class CardCaption:
    """A standalone caption label (sub-grey or amber note)."""

    text: str
    amber: bool = False
    wraplength: int | None = None
    pady: tuple[int, int] = (0, 0)


@dataclass(frozen=True)
class CardEntryRow:
    """A labelled ``Entry`` bound to one state StringVar/IntVar."""

    label: str
    var_attr: str
    entry_width: int = 8
    label_width: int | None = None
    entry_padx: int | tuple[int, int] = 6
    row_pady: int | tuple[int, int] = 1


@dataclass(frozen=True)
class CardComboRow:
    """A labelled read-only ``Combobox`` bound to one state StringVar."""

    label: str
    var_attr: str
    values: tuple[str, ...]
    combo_width: int = 12
    label_width: int | None = None
    combo_padx: int | tuple[int, int] = 6
    row_pady: int | tuple[int, int] = (6, 1)


@dataclass(frozen=True)
class CardCheckEntryRow:
    """The Parallel Processing / Workers row: one Checkbutton + Entry."""

    check_text: str = "Parallel Processing"
    check_attr: str = ""
    label: str = "Workers:"
    var_attr: str = ""
    entry_width: int = 4
    row_pady: int | tuple[int, int] = 4


@dataclass(frozen=True)
class SimpleCardSpec:
    """Declarative state for one simple tool card.

    Attributes:
        toggle: Either ``"module_toggles:<key>"`` — the Master Driver's
            canonical per-module BooleanVar — or a plain attribute name on
            the state object (e.g. ``asx_extractor_toggle``).
        title:  Text of the header title Label.
        description: Optional first-body caption paragraph.
        description_justify: ``tk.LEFT`` when the caption must word-wrap
            multi-line, None for the plain one-line look.
        description_wraplength: Only used when *description* is set.
        rows:   The remaining body rows, in pack order.
    """

    toggle: str
    title: str
    description: str | None = None
    description_wraplength: int = 480
    rows: tuple[CardCaption | CardEntryRow | CardComboRow | CardCheckEntryRow, ...] = ()


def _state_var(state: "AppState", spec_attr: str) -> tk.Variable:
    """Resolve a spec attribute reference to the state variable it names."""
    if spec_attr.startswith("module_toggles:"):
        var = state.module_toggles[spec_attr.removeprefix("module_toggles:")]
    else:
        var = getattr(state, spec_attr)
    var_typed: tk.Variable = var  # bind past the AppState Any for mypy strict
    return var_typed


def build_simple_card(
    parent: tk.Frame, state: "AppState", spec: SimpleCardSpec
) -> None:
    """Render one :class:`SimpleCardSpec` into *parent*.

    The single implementation of the collapsible outer/header shell and the
    row-level body builders shared by the simple cards; each card file
    delegates its ``build(parent, state)`` to this function.

    Args:
        parent: Parent frame for the card's outer frame.
        state:  Master Driver AppState carrying the real Tk variables.
        spec:   The card's data description.
    """
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    header = tk.Frame(outer, bg=styles.BG_LIGHT)
    header.pack(fill="x", padx=8, pady=4)

    tk.Checkbutton(
        header,
        variable=_state_var(state, spec.toggle),
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text=spec.title,
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value=_COLLAPSE_LABEL)
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    if spec.description is not None:
        tk.Label(
            body,
            text=spec.description,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            wraplength=spec.description_wraplength,
            justify=tk.LEFT,
        ).pack(anchor="w")

    for row in spec.rows:
        if isinstance(row, CardCaption):
            caption_kwargs: dict[str, Any] = {
                "bg": styles.BG_WHITE,
                "fg": styles.AMBER if row.amber else styles.FG_SUB,
                "font": styles.FONT_CAPTION,
                "text": row.text,
            }
            if row.wraplength is not None:
                caption_kwargs["wraplength"] = row.wraplength
            tk.Label(body, **caption_kwargs).pack(anchor="w", pady=row.pady)
        elif isinstance(row, CardEntryRow):
            entry_frame = tk.Frame(body, bg=styles.BG_WHITE)
            entry_frame.pack(fill="x", pady=row.row_pady)
            if row.label_width is not None:
                _pack_caption_label(
                    entry_frame,
                    row.label,
                    width=row.label_width,
                )
            else:
                _pack_plain_label(entry_frame, row.label)
            tk.Entry(
                entry_frame,
                textvariable=getattr(state, row.var_attr),
                width=row.entry_width,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                insertbackground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=row.entry_padx)
        elif isinstance(row, CardComboRow):
            combo_frame = tk.Frame(body, bg=styles.BG_WHITE)
            combo_frame.pack(fill="x", pady=row.row_pady)
            if row.label_width is not None:
                _pack_caption_label(combo_frame, row.label, width=row.label_width)
            else:
                _pack_plain_label(combo_frame, row.label)
            ttk.Combobox(
                combo_frame,
                textvariable=getattr(state, row.var_attr),
                state="readonly",
                width=row.combo_width,
                font=styles.FONT_BODY,
                values=row.values,
            ).pack(side=tk.LEFT, padx=row.combo_padx)
        elif isinstance(row, CardCheckEntryRow):
            check_frame = tk.Frame(body, bg=styles.BG_WHITE)
            check_frame.pack(fill="x", pady=row.row_pady)
            tk.Checkbutton(
                check_frame,
                text=row.check_text,
                variable=getattr(state, row.check_attr),
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
            ).pack(side=tk.LEFT)
            tk.Label(
                check_frame,
                text=row.label,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=(12, 2))
            tk.Entry(
                check_frame,
                textvariable=getattr(state, row.var_attr),
                width=row.entry_width,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
            ).pack(side=tk.LEFT)

    def _toggle() -> None:
        is_open = not expanded[0]
        if is_open:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set(_EXPAND_LABEL)
        else:
            body.pack_forget()
            expand_var.set(_COLLAPSE_LABEL)
        expanded[0] = is_open
        hook = _expansion_hook(parent)
        if hook is not None:
            hook(is_open)

    tk.Button(
        header,
        textvariable=expand_var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_LIGHT,
        fg=styles.FG_SUB,
        relief=tk.FLAT,
        cursor="hand2",
        command=_toggle,
    ).pack(side=tk.RIGHT)


def _pack_caption_label(frame: tk.Frame, text: str, width: int) -> None:
    tk.Label(
        frame,
        text=text,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=width,
        anchor="w",
    ).pack(side=tk.LEFT)


def _pack_plain_label(frame: tk.Frame, text: str) -> None:
    tk.Label(
        frame,
        text=text,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT)


def build_card_shell(
    parent: tk.Frame,
    title: str,
    toggle_var: tk.BooleanVar | None,
    body_builder: "Callable[[tk.Frame], None]",
    *,
    toggle_command: "Callable[[], None] | None" = None,
) -> None:
    """Render the shared collapsible card shell and delegate body content.

    Every tool card shares an identical outer frame, header (Checkbutton +
    title Label), and ``▶/▼  Settings`` expand button.  The card-specific
    body content is supplied by *body_builder*, which receives the body
    frame and packs its widgets into it.

    Args:
        parent: Parent frame for the card's outer frame.
        title:  Header title text.
        toggle_var: The ``tk.BooleanVar`` bound to the header Checkbutton, or
            ``None`` for a card that is not part of a batch run (Undo Tag
            Edits is opened on demand, so it has no module toggle).
        body_builder: Callback that populates the collapsible body frame.
        toggle_command: Optional callback for the header Checkbutton, run after
            the variable has changed (the converter re-scans its folder).
    """
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    header = tk.Frame(outer, bg=styles.BG_LIGHT)
    header.pack(fill="x", padx=8, pady=4)

    if toggle_var is not None:
        toggle = tk.Checkbutton(
            header,
            variable=toggle_var,
            bg=styles.BG_LIGHT,
            activebackground=styles.BG_LIGHT,
        )
        if toggle_command is not None:
            toggle.configure(command=toggle_command)
        toggle.pack(side=tk.LEFT)

    tk.Label(
        header,
        text=title,
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value=_COLLAPSE_LABEL)
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    body_builder(body)

    def _toggle() -> None:
        is_open = not expanded[0]
        if is_open:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set(_EXPAND_LABEL)
        else:
            body.pack_forget()
            expand_var.set(_COLLAPSE_LABEL)
        expanded[0] = is_open
        hook = _expansion_hook(parent)
        if hook is not None:
            hook(is_open)

    tk.Button(
        header,
        textvariable=expand_var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_LIGHT,
        fg=styles.FG_SUB,
        relief=tk.FLAT,
        cursor="hand2",
        command=_toggle,
    ).pack(side=tk.RIGHT)
