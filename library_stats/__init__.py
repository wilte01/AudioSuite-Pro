"""Library Statistics Dashboard — analyse and visualise your music library."""

from __future__ import annotations

from .app import LibraryStatsApp
from .core.file_processor import StatsReport, scan_directory

__all__ = ["LibraryStatsApp", "StatsReport", "scan_directory"]
