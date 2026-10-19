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
