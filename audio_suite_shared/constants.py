"""
constants.py — Shared named constants for AudioSuite-Pro.

Centralises magic numbers that were previously scattered across worker code,
processors, and config modules. Each constant carries a single, self-documenting
name instead of a bare numeric literal.
"""

from __future__ import annotations

# ── File processor defaults ──────────────────────────────────────────────────
DEFAULT_MAX_WORKERS: int = 4
"""Default thread-pool worker count for parallel file processing."""

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
