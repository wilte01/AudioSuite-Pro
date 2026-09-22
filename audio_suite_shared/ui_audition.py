"""
ui_audition.py — Shared before/after audition button builder for DSP tools.

Adds a small "audition" row to a DSP tool's Results tab so the user can play
the original and processed versions of the last-processed file with a single
click.  It depends only on the shared playback layer
(``audio_suite_shared.audio_playback``) and the suite's standard styles, so
each DSP tool wires it identically rather than duplicating button styling.

Layout
------
    [ ▶ Play Original ]  [ ▶ Play Result ]

A short status caption underneath reflects the current state ("Ready",
"Playing…", or an error/absence message).  Both buttons pass through to
callbacks provided by the tool's app, which decide which file to play.

The :class:`AuditionMixin` bundles the per-app bookkeeping (which files are
the before/after pair) so the five DSP apps each add a handful of lines
instead of duplicating the same state machine.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from . import audio_playback, styles

_ICON_PLAY = "\u25b6"  # ►

_READY_MSG = "Ready — use the buttons above to audition."
_DRY_RUN_MSG = "Dry Run — nothing written. Play Result is unavailable."
_LOCKED_MSG = "Locked — press Start to capture the originals, then audition here."
_NO_SOURCE_MSG = "No supported audio file found — audition unavailable."
_NOT_AVAILABLE_MSG = " not available."


def add_audition_buttons(
    parent: tk.Misc,
    on_play_original: Callable[[], None],
    on_play_result: Callable[[], None],
    result_available: bool = False,
    caption_var: tk.StringVar | None = None,
) -> dict[str, Any]:
    """Add an audition row to a Results tab and return its widget references.

    Args:
        parent:        The frame (or container) to pack the row into.
        on_play_original: Callback for the "Play Original" button.
        on_play_result:   Callback for the "Play Result" button.
        result_available: Whether a processed result currently exists.  When
            False (e.g. after a Dry Run with no written output) the
            "Play Result" button is disabled.
        caption_var:   Optional StringVar for the status caption.  If None a
            fresh one is created and returned under key ``caption_var``.

    Returns:
        dict with keys:
            play_original_btn : tk.Button
            play_result_btn   : tk.Button
            caption_var       : tk.StringVar
    """
    if caption_var is None:
        caption_var = tk.StringVar(value=_READY_MSG)

    frame = tk.Frame(parent, bg=styles.BG_WHITE)
    frame.pack(pady=(4, 10))

    play_original_btn = tk.Button(
        frame,
        text=f"{_ICON_PLAY} Play Original",
        width=20,
        bg=styles.get_main(),
        fg="white",
        pady=6,
        command=on_play_original,
        font=styles.FONT_BUTTON,
    )
    play_original_btn.pack(side=tk.LEFT, padx=(0, 6))

    play_result_btn = tk.Button(
        frame,
        text=f"{_ICON_PLAY} Play Result",
        width=20,
        bg=styles.get_main(),
        fg="white",
        pady=6,
        command=on_play_result,
        font=styles.FONT_BUTTON,
    )
    play_result_btn.pack(side=tk.LEFT)
    play_result_btn.config(state=tk.NORMAL if result_available else tk.DISABLED)

    if caption_var is not None:
        caption_label = tk.Label(
            parent,
            textvariable=caption_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        )
        caption_label.pack(pady=(0, 8))

    return {
        "play_original_btn": play_original_btn,
        "play_result_btn": play_result_btn,
        "caption_var": caption_var,
    }


def set_result_available(play_result_btn: tk.Button, available: bool) -> None:
    """Enable or disable the Play Result button."""
    play_result_btn.config(state=tk.NORMAL if available else tk.DISABLED)


class AuditionMixin:
    """Wires the shared Results-tab audition row into a DSP app.

    The mixin owns the Play Original / Play Result buttons, the status
    caption, and the before/after path bookkeeping.  Subclasses call::

        res_widgets = results_tab.build(..., on_play_original=self._play_original,
                                        on_play_result=self._play_result)
        self.setup_audition(res_widgets)

    then, at the start of every run, either :meth:`prepare_in_place_audition`
    (tools that overwrite their source) or :meth:`clear_audition`, and finally
    :meth:`set_audition_state` when the run completes.

    Requires a ``self.root`` :class:`tk.Tk` window.  :meth:`set_audition_state`
    is safe to call from a worker thread — the widget mutations it triggers are
    marshalled onto the Tk main thread via ``root.after``.
    """

    root: tk.Tk
    _play_original_btn: tk.Button
    _play_result_btn: tk.Button
    _audition_caption_var: tk.StringVar
    _audition_original: Path | None
    _audition_result: Path | None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def setup_audition(self, res_widgets: dict[str, Any]) -> None:
        """Bind the audition widgets built by ``build_results_tab``.

        Also registers a window-close handler so in-flight playback is stopped
        and the snapshot folder is removed when the app exits.
        """
        self._play_original_btn = res_widgets["play_original_btn"]
        self._play_result_btn = res_widgets["play_result_btn"]
        self._audition_caption_var = res_widgets["audition_caption_var"]
        self._audition_original = None
        self._audition_result = None
        self.root.protocol("WM_DELETE_WINDOW", self._audition_close)

    def clear_audition(self) -> None:
        """Reset both audition slots (used at the start of a non-in-place run)."""
        audio_playback.clear_snapshots()
        self.set_audition_state(None, None, _LOCKED_MSG)

    def prepare_in_place_audition(
        self,
        source: str | Path,
        extensions: tuple[str, ...],
        result_path: str | Path | None = None,
    ) -> None:
        """Capture the before-half of the A/B pair before an in-place run.

        The first supported audio file under *source* is byte-copied into the
        session snapshot folder.  After processing, the original path holds the
        processed audio, so it becomes the "result" half automatically.

        Args:
            source:     The source file or folder being processed.
            extensions: Tuple of supported extensions.
            result_path: Optional explicit result path (used by tools that can
                write to a separate output directory).  Defaults to the
                original file path, which is correct for in-place tools.
        """
        audio_playback.clear_snapshots()
        original = audio_playback.peek_first_audio(source, extensions)
        if original is None:
            self.set_audition_state(None, None, _NO_SOURCE_MSG)
            return
        snapshot = audio_playback.create_original_snapshot(original, extensions)
        result = Path(result_path) if result_path is not None else original
        caption = (
            f"Original captured: {original.name} — press Play Original now, "
            "Play Result when the run finishes."
            if snapshot is not None
            else _NO_SOURCE_MSG
        )
        self.set_audition_state(snapshot, result, caption)

    # ── State ────────────────────────────────────────────────────────────────

    def set_audition_state(
        self,
        original: Path | None,
        result: Path | None,
        caption: str,
    ) -> None:
        """Record the before/after pair and schedule the caption & buttons.

        Safe to call from any thread; the widget updates run on the main thread.
        """
        self._audition_original = original
        self._audition_result = result
        self.root.after(0, self._apply_audition_state, caption)

    def _apply_audition_state(self, caption: str) -> None:
        """Main thread only: apply the state scheduled by set_audition_state."""
        self._play_original_btn.config(
            state=tk.NORMAL if self._audition_original is not None else tk.DISABLED
        )
        self._play_result_btn.config(
            state=tk.NORMAL if self._audition_result is not None else tk.DISABLED
        )
        self._audition_caption_var.set(caption)

    # ── Button callbacks (main thread) ───────────────────────────────────────

    def _play_original(self) -> None:
        path = self._audition_original
        if path is None or not path.is_file():
            self._audition_caption_var.set("Original" + _NOT_AVAILABLE_MSG)
            return
        if audio_playback.play_audio(path):
            self._audition_caption_var.set(f"Playing original — {path.name}")
        else:
            self._audition_caption_var.set(audio_playback.describe_failure(path))

    def _play_result(self) -> None:
        path = self._audition_result
        if path is None or not path.is_file():
            self._audition_caption_var.set("Result" + _NOT_AVAILABLE_MSG)
            return
        if audio_playback.play_audio(path):
            self._audition_caption_var.set(f"Playing result — {path.name}")
        else:
            self._audition_caption_var.set(audio_playback.describe_failure(path))

    # ── Window close ─────────────────────────────────────────────────────────

    def _audition_close(self) -> None:
        """Stop playback and remove snapshots before the window closes."""
        audio_playback.stop_playback()
        audio_playback.clear_snapshots()
        self.root.destroy()


__all__ = [
    "AuditionMixin",
    "add_audition_buttons",
    "set_result_available",
]
