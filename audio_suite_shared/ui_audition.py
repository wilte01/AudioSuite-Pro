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

Changed in 2.7.0: :meth:`AuditionMixin.prepare_matched_audition` renders a
level-matched pair (the louder side attenuated, never boosted) and an optional
blind A/B whose mapping is withheld until :meth:`AuditionMixin.reveal_blind`
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S9).
"""

from __future__ import annotations

import math
import random
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import audio_playback, styles
from .audio_probe import measure_loudness
from .exceptions import AudioSuiteError

_ICON_PLAY = "\u25b6"  # ►

_READY_MSG = "Ready — use the buttons above to audition."
_DRY_RUN_MSG = "Dry Run — nothing written. Play Result is unavailable."
_LOCKED_MSG = "Locked — press Start to capture the originals, then audition here."
_NO_SOURCE_MSG = "No supported audio file found — audition unavailable."
_NOT_AVAILABLE_MSG = " not available."
_MATCH_UNAVAILABLE = "Level match unavailable - "
_PLAY_ORIGINAL_TEXT = f"{_ICON_PLAY} Play Original"
_PLAY_RESULT_TEXT = f"{_ICON_PLAY} Play Result"
_PLAY_A_TEXT = f"{_ICON_PLAY} Play A"
_PLAY_B_TEXT = f"{_ICON_PLAY} Play B"


@dataclass(frozen=True)
class MatchedAudition:
    """A level-matched A/B pair, ready to play.

    The previews are separate files, so the user's own audio is never rewritten
    to make a fair comparison.

    Attributes:
        original: The original, rendered at its matched level.
        result: The processed result, rendered at its matched level.
        original_lufs: The original's measured integrated loudness.
        result_lufs: The result's measured integrated loudness.
        gain_original_db: Gain applied to the original (always <= 0).
        gain_result_db: Gain applied to the result (always <= 0).
        blind: Whether the pair was handed over as A/B.
    """

    original: Path
    result: Path
    original_lufs: float
    result_lufs: float
    gain_original_db: float
    gain_result_db: float
    blind: bool = False


def match_gains(original_lufs: float, result_lufs: float) -> tuple[float, float]:
    """Return the gains that put both files at the quieter one's level.

    The **loudest** file is attenuated and the quieter one is left alone, so the
    comparison never boosts anything and nothing can be pushed into clipping.
    That is why there is no "capped by the 0 dBFS rule" case to report: a rule
    that only ever attenuates cannot bind.

    Args:
        original_lufs: The original's integrated loudness.
        result_lufs: The result's integrated loudness.

    Returns:
        ``(gain_original_db, gain_result_db)``, both ``<= 0``.

    Raises:
        ValueError: If either figure is not a finite number, which would make
            the difference meaningless (a silent file measures ``-inf``).
    """
    if not (math.isfinite(original_lufs) and math.isfinite(result_lufs)):
        raise ValueError("loudness is not a finite figure")
    difference = original_lufs - result_lufs
    if difference > 0:
        return -difference, 0.0
    if difference < 0:
        return 0.0, difference
    return 0.0, 0.0


def _render_preview(source: Path, gain_db: float, destination: Path) -> Path:
    """Write *source* to *destination* at *gain_db*, leaving the source alone.

    Args:
        source: The file to render from.
        gain_db: Gain in dB; ``0.0`` copies the audio unchanged.
        destination: The ``.wav`` path to write.

    Returns:
        *destination*.
    """
    from pydub import AudioSegment

    audio = AudioSegment.from_file(str(source))
    if gain_db:
        audio = audio.apply_gain(gain_db)
    destination.parent.mkdir(parents=True, exist_ok=True)
    audio.export(str(destination), format="wav")
    return destination


def add_audition_buttons(
    parent: tk.Misc,
    on_play_original: Callable[[], None],
    on_play_result: Callable[[], None],
    result_available: bool = False,
    caption_var: tk.StringVar | None = None,
    with_match_options: bool = False,
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
        with_match_options: Add the "Level match" and "Blind A/B" switches.
            They only change what the Play buttons play once the mixin holds a
            before/after pair, so the row looks the same before a run.

    Returns:
        dict with keys:
            play_original_btn : tk.Button
            play_result_btn   : tk.Button
            caption_var       : tk.StringVar
            level_match_var   : tk.BooleanVar (always present)
            blind_var         : tk.BooleanVar (always present)
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

    level_match_var = tk.BooleanVar(value=False)
    blind_var = tk.BooleanVar(value=False)
    if with_match_options:
        options = tk.Frame(parent, bg=styles.BG_WHITE)
        options.pack(pady=(0, 4))
        tk.Checkbutton(
            options,
            text="Level match",
            variable=level_match_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_CAPTION,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        tk.Checkbutton(
            options,
            text="Blind A/B",
            variable=blind_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_CAPTION,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(12, 0))

    return {
        "play_original_btn": play_original_btn,
        "play_result_btn": play_result_btn,
        "caption_var": caption_var,
        "level_match_var": level_match_var,
        "blind_var": blind_var,
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
    _source_pair: tuple[Path, Path] | None
    _matched: MatchedAudition | None

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
        self._blind_mapping: dict[str, str] | None = None
        # The pair of *source* files, kept apart from the displayed paths: a
        # matched audition replaces the displayed pair with its previews, and
        # the next Play must still know what to match.
        self._source_pair: tuple[Path, Path] | None = None
        self._matched: MatchedAudition | None = None
        self._level_match_var = res_widgets.get("level_match_var")
        self._blind_var = res_widgets.get("blind_var")
        self.root.protocol("WM_DELETE_WINDOW", self._audition_close)

    def clear_audition(self) -> None:
        """Reset both audition slots (used at the start of a non-in-place run)."""
        audio_playback.clear_snapshots()
        self._source_pair = None
        self._matched = None
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
        self._source_pair = (snapshot, result) if snapshot is not None else None
        self._matched = None
        self.set_audition_state(snapshot, result, caption)

    def prepare_matched_audition(
        self,
        original: str | Path,
        result: str | Path,
        *,
        blind: bool = False,
    ) -> MatchedAudition | None:
        """Capture an A/B pair whose two halves are at the same loudness.

        Both files are measured, the louder one is attenuated to the quieter
        one, and each half is rendered to its own preview file - so an A/B
        between a quiet master and a hot one compares the *processing*, not the
        level.  Nothing is ever boosted, and no source file is modified.

        With *blind*, the two previews are handed over as A and B in a random
        order and the mapping is kept back until :meth:`reveal_blind`, so the
        listener cannot already know which button is the processed one.

        Args:
            original: The before file.
            result: The after file.
            blind: Whether to hide which preview is which.

        Returns:
            The matched pair, or ``None`` when the match was impossible; the
            caption then says why, because a silent A/B button is worse than a
            caption that explains the refusal.
        """
        audio_playback.clear_snapshots()
        self._blind_mapping = None
        self._source_pair = (Path(original), Path(result))
        source_original, source_result = Path(original), Path(result)
        try:
            original_lufs = measure_loudness(str(source_original)).integrated_lufs
            result_lufs = measure_loudness(str(source_result)).integrated_lufs
            gain_original, gain_result = match_gains(original_lufs, result_lufs)
            folder = audio_playback.audition_snapshot_dir()
            preview_original = _render_preview(
                source_original, gain_original, folder / "matched_original.wav"
            )
            preview_result = _render_preview(
                source_result, gain_result, folder / "matched_result.wav"
            )
        except (AudioSuiteError, ValueError, OSError) as exc:
            self.set_audition_state(None, None, _MATCH_UNAVAILABLE + str(exc))
            return None

        matched = MatchedAudition(
            original=preview_original,
            result=preview_result,
            original_lufs=original_lufs,
            result_lufs=result_lufs,
            gain_original_db=gain_original,
            gain_result_db=gain_result,
            blind=blind,
        )
        if not blind:
            self._play_original_btn.config(text=_PLAY_ORIGINAL_TEXT)
            self._play_result_btn.config(text=_PLAY_RESULT_TEXT)
            self.set_audition_state(
                preview_original,
                preview_result,
                f"Level matched ({gain_original:+.1f} dB original, "
                f"{gain_result:+.1f} dB result) - press Play to compare.",
            )
            return matched

        original_is_a = random.choice((True, False))
        self._blind_mapping = {
            "A": "original" if original_is_a else "result",
            "B": "result" if original_is_a else "original",
        }
        first = preview_original if original_is_a else preview_result
        second = preview_result if original_is_a else preview_original
        self._play_original_btn.config(text=_PLAY_A_TEXT)
        self._play_result_btn.config(text=_PLAY_B_TEXT)
        self.set_audition_state(
            first, second, "Blind A/B - level matched. Press Play A or B."
        )
        return matched

    def reveal_blind(self) -> dict[str, str] | None:
        """Return the hidden A/B mapping, or ``None`` when nothing is blind."""
        return dict(self._blind_mapping) if self._blind_mapping else None

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
        self._play_role("original")

    def _play_result(self) -> None:
        self._play_role("result")

    def _matched_requested(self) -> bool:
        """Whether the user ticked "Level match"."""
        variable = getattr(self, "_level_match_var", None)
        return bool(variable is not None and variable.get())

    def _blind_requested(self) -> bool:
        """Whether the user ticked "Blind A/B"."""
        variable = getattr(self, "_blind_var", None)
        return bool(variable is not None and variable.get())

    def _matched_pair(self) -> MatchedAudition | None:
        """Prepare the matched pair once per source pair, then reuse it.

        Re-preparing on every click would re-render the previews each time and
        re-randomise a blind A/B between two presses, which is the one thing a
        blind test cannot survive.
        """
        pair = getattr(self, "_source_pair", None)
        if pair is None:
            return None
        cached: MatchedAudition | None = (
            self._matched if hasattr(self, "_matched") else None
        )
        if cached is not None and cached.original.is_file() and cached.result.is_file():
            return cached
        self._matched = self.prepare_matched_audition(
            pair[0], pair[1], blind=self._blind_requested()
        )
        return self._matched

    def _play_role(self, role: str) -> None:
        """Play the original or the result, matched and blind when asked.

        Args:
            role: ``"original"`` or ``"result"``.
        """
        path = self._audition_original if role == "original" else self._audition_result
        spoken = "original" if role == "original" else "result"
        if path is None or not path.is_file():
            self._audition_caption_var.set(spoken.capitalize() + _NOT_AVAILABLE_MSG)
            return
        if self._matched_requested():
            matched = self._matched_pair()
            if matched is None:
                return  # prepare_matched_audition left a caption saying why
            if matched.blind:
                mapping = self.reveal_blind() or {}
                letter = next(
                    (key for key, value in mapping.items() if value == role), ""
                )
                path = matched.original if letter == "A" else matched.result
                spoken = letter or spoken
            else:
                path = matched.original if role == "original" else matched.result
                spoken = f"{spoken} (level matched)"
        if audio_playback.play_audio(path):
            self._audition_caption_var.set(f"Playing {spoken} — {path.name}")
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
