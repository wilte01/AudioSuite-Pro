"""
constants.py — Shared named constants for AudioSuite-Pro.

Centralises magic numbers that were previously scattered across worker code,
processors, and config modules. Each constant carries a single, self-documenting
name instead of a bare numeric literal.

Changed in 1.4.0: the worker default is derived from the host's logical CPU
count (``default_max_workers()``, capped at ``MAX_WORKERS_CEILING``) instead of
a fixed 4, so parallel batches use the machine they run on.  Also adds
``cap_workers_to_slot_grid``, the one place a requested worker count is capped
at the GUI's slot grid (D66).

Changed in 2.6.0: adds ``DEFAULT_BPM_ANALYSIS_SECONDS``, the one analysis
window BPM Analyzer's core, CLI, GUI and Master Driver read, so a file is no
longer refused by one entry point and tagged by another (D139).  Adds
``DEFAULT_ANALYSIS_SECONDS``, the window Key Detector and Mood Analyzer read at
every entry point (D140).
"""

from __future__ import annotations

import os
from collections.abc import Sized

# ── File processor defaults ──────────────────────────────────────────────────
MAX_WORKERS_CEILING: int = 8
"""Upper bound on the default parallel worker count.

The cap bounds peak memory for concurrent librosa/pedalboard jobs; a tool can
still be given a larger count explicitly.
"""

# ── Analysis defaults ────────────────────────────────────────────────────────
DEFAULT_BPM_ANALYSIS_SECONDS: int = 30
"""Seconds of audio BPM Analyzer analyses when a caller names no duration.

One value for every entry point — the core default, the CLI, the GUI and the
Master Driver — because two defaults meant the same file could be refused by
one and tagged by another.  The number is not arbitrary: the onset-periodicity
floor is calibrated on windows of this length.  With the shipped detrended
noise generator, seeded white/pink/brown noise peaks at 0.067 over 30 s (0.061
through a 44.1 kHz MP3 128 kbps round-trip) against the 0.10 floor, while real
music at 30 s stays clear of it: the corpus's weakest clip scores 0.124 and, on
a 120-track sample of a 44.1/48 kHz MP3 library, the beatless files top out at
0.072 and the weakest genuine groove scores 0.120.  At 90 s the same harmonic
comb dilutes on real music (two library tracks fell from 0.159/0.222 at 20 s to
0.094/0.071 at 90 s) and refused 10% of that sample, which is why the window,
not the floor, moved (PLAN D139).
"""


DEFAULT_ANALYSIS_SECONDS: int = 90
"""Seconds of audio Key Detector and Mood Analyzer analyse by default.

One value for every entry point - both ``--duration`` options and their help
text, both argument dataclasses, the shared GUI duration widget and the Master
Driver's ``key_duration``/``mood_duration`` - because the ``key`` command
analysed 30 s while the window, the parser and the driver analysed 90 s, so the
same folder ran three times less audio from the command line (D140).

This is deliberately not the BPM value (``DEFAULT_BPM_ANALYSIS_SECONDS``): BPM
Analyzer's 30 s is the length its onset-periodicity floor was calibrated at and
it refuses a track the comb cannot confirm there.  Key and mood have no
window-calibrated refusal gate - their skips are the duration/silence guard and
an existing tag - while chroma correlation for key and the beat/timbre
statistics for mood gain context from more of the track, and 90 s is what four
of Key's five entry points, every Mood entry point and the shared decode cap
already used.
"""


def default_max_workers() -> int:
    """Return the suite default thread/process-pool worker count.

    One worker per logical CPU, capped at :data:`MAX_WORKERS_CEILING`, with a
    fallback of 4 when the platform reports no CPU count.

    Returns:
        The worker count to use when a caller does not specify one.
    """
    return min(os.cpu_count() or 4, MAX_WORKERS_CEILING)


DEFAULT_MAX_WORKERS: int = default_max_workers()
"""Import-time snapshot of :func:`default_max_workers()`.

Kept as a value for call sites that size a pool once at widget construction
(GUI slot grids). Function and constructor defaults use ``None`` and resolve
through the function, so they are never frozen at an earlier import.
"""


def cap_workers_to_slot_grid(workers: int, slot_vars: object | None) -> int:
    """Cap *workers* at the number of GUI worker-slot displays.

    A slot grid is built once, when the window is constructed, from
    :data:`DEFAULT_MAX_WORKERS`.  The analysis tools' Workers field is free
    text, so a caller can still ask for more workers than there are slots;
    every slot index is then drawn from ``range(effective_workers)`` or from a
    queue pre-loaded that way, indexes past the end of ``slot_vars``, and the
    per-file progress write raises ``IndexError`` — which the recovery layer
    reports as an unexplained per-file error for every file past the grid.

    Capping is the safe resolution for both drift directions of D56: a pool
    larger than the grid cannot overflow it, and the batch still completes.

    Args:
        workers: The requested worker count.
        slot_vars: The slot display list, or ``None``/anything without a
            length when the caller has no display grid (CLI, tests).

    Returns:
        *workers* unchanged when no grid is known or the grid is large
        enough, otherwise the grid's length.  A non-positive *workers* is
        returned as-is so the caller's own validation still reports it.
    """
    if not isinstance(slot_vars, Sized):
        return workers
    capacity = len(slot_vars)
    if capacity <= 0 or workers <= capacity:
        return workers
    return capacity


WORKER_TIMEOUT_SECS: int = 300
"""Per-future timeout (seconds) for ThreadPoolExecutor futures."""

CPU_WORKER_TIMEOUT_SECS: int = 600
"""Per-future timeout (seconds) for ProcessPoolExecutor futures."""

# ── Image / artwork ─────────────────────────────────────────────────────────
JPEG_QUALITY: int = 92
"""JPEG encoding quality used when embedding album artwork."""

# ── Config / history ────────────────────────────────────────────────────────
MAX_DURATION_HISTORY: int = 10
"""Maximum number of per-tool run durations retained in config history."""

DEFAULT_WINDOW_GEOMETRY: str = "800x600+100+100"
"""Fallback window geometry string used when no saved geometry exists."""

# ── Tag / reorganiser ───────────────────────────────────────────────────────
VARIOUS_ARTISTS_ALIASES: frozenset[str] = frozenset(
    {
        "various artists",
        "various",
    }
)
"""Lower-cased album-artist values that trigger the 'various' pattern."""
