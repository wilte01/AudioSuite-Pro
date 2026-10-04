"""
trimmer.py
Silence detection, trimming, and optional fade application using pydub.

Pure function — no tkinter, no file I/O, no temp-file management.
Accepts a loaded AudioSegment and returns the result so the caller
controls all file operations.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydub import AudioSegment, silence


@dataclass(frozen=True)
class TrimResult:
    """Result of applying silence detection to one AudioSegment.

    Attributes:
        start_trim_ms: Milliseconds of leading silence detected.
        end_trim_ms: Milliseconds of trailing silence detected.
        total_trim_ms: Sum of start + end trim.
        has_silence: True if any silence was found.
        trimmed: The processed AudioSegment (with optional fades),
            or None if has_silence is False.
        status: 'TRIMMED' | 'DRY_RUN' | 'SKIP'
        apply_fade: Whether fades were applied to the returned audio.
            Callers that need to describe the outcome must read this rather
            than substring-match ``action`` - ``action`` is human-readable
            text and its wording is not a stable interface.
        action: Human-readable description of what was/would be done.
    """

    start_trim_ms: int
    end_trim_ms: int
    total_trim_ms: int
    has_silence: bool
    trimmed: AudioSegment | None
    status: str
    action: str
    apply_fade: bool = False


def trim_and_fade(
    audio: AudioSegment,
    threshold: int,
    is_dry_run: bool,
    apply_fade: bool = False,
    fade_in_ms: int = 500,
    fade_out_ms: int = 1000,
) -> TrimResult:
    """Detect leading/trailing silence, trim it, and optionally apply fades.

    Args:
        audio: Loaded AudioSegment to process.
        threshold: Silence threshold in dBFS (e.g. -50).
        is_dry_run: If True, calculate trim amounts but return no output audio.
        apply_fade: Whether to apply fade-in / fade-out after trimming.
        fade_in_ms: Fade-in duration in milliseconds.
        fade_out_ms: Fade-out duration in milliseconds.

    Returns:
        TrimResult describing what was (or would be) done.
    """
    start_trim: int = silence.detect_leading_silence(audio, silence_threshold=threshold)
    end_trim: int = silence.detect_leading_silence(
        audio.reverse(), silence_threshold=threshold
    )
    total_trim: int = start_trim + end_trim

    if total_trim == 0:
        return TrimResult(
            start_trim_ms=0,
            end_trim_ms=0,
            total_trim_ms=0,
            has_silence=False,
            trimmed=None,
            status="SKIP",
            action="No silence detected",
        )

    if is_dry_run:
        return TrimResult(
            start_trim_ms=start_trim,
            end_trim_ms=end_trim,
            total_trim_ms=total_trim,
            has_silence=True,
            trimmed=None,
            status="DRY_RUN",
            action=f"Would trim {total_trim}ms",
        )

    trimmed: AudioSegment = audio[start_trim : len(audio) - end_trim]  # noqa: E203
    if apply_fade and len(trimmed) > 0:
        # Clamp fade durations to the trimmed segment's own length. pydub's
        # fade() does not clip a fade that is longer than the segment — it
        # computes a negative internal start offset instead, which produces
        # extra (corrupted/duplicated) audio and silently lengthens the
        # output. Clamping avoids that without changing fade behaviour for
        # any fade duration that already fits within the trimmed audio.
        # A clamped value of exactly 0 (fully-silent trimmed segment) is
        # skipped outright: pydub's fade() treats duration=0 as falsy and
        # raises TypeError rather than being a no-op fade.
        clamped_fade_in_ms: int = min(fade_in_ms, len(trimmed))
        clamped_fade_out_ms: int = min(fade_out_ms, len(trimmed))
        if clamped_fade_in_ms > 0:
            trimmed = trimmed.fade_in(clamped_fade_in_ms)
        if clamped_fade_out_ms > 0:
            trimmed = trimmed.fade_out(clamped_fade_out_ms)

    action: str = f"-{start_trim}ms / -{end_trim}ms"
    if apply_fade:
        action += " + Fades"

    return TrimResult(
        start_trim_ms=start_trim,
        end_trim_ms=end_trim,
        total_trim_ms=total_trim,
        has_silence=True,
        trimmed=trimmed,
        status="TRIMMED",
        action=action,
        apply_fade=bool(apply_fade),
    )
