"""
library_stats.py — Backward-compatible re-export of core scanning logic.

All public API was moved to ``core/file_processor.py`` for consistency
with the rest of the suite.  This stub re-exports from there so that
existing imports (``from library_stats.library_stats import ...``) continue
to work without changes.

Changed in 2.2.0: also re-exports the playlist/HTML export surface and the
Camelot mapping from ``library_stats.core.playlist_export`` (F-05/F-06).
"""

from __future__ import annotations

from library_stats.core.completeness import (  # noqa: F401
    TAG_FIELDS,
    TAG_LABELS,
    CompletenessReport,
    TagCompleteness,
    analyse_completeness,
    export_completeness_csv,
    export_completeness_json,
)
from library_stats.core.file_processor import (  # noqa: F401
    StatsReport,
    _bpm_bin,
    _classify_key_mode,
    _decade_bin,
    export_csv,
    export_json,
    scan_directory,
)
from library_stats.core.playlist_export import (  # noqa: F401
    DEFAULT_EXPORT_COLUMNS,
    EXPORT_COLUMNS,
    ExportRow,
    camelot_for_key,
    collect_export_rows,
    export_html,
    export_m3u,
    resolve_columns,
)

__all__ = [
    "DEFAULT_EXPORT_COLUMNS",
    "EXPORT_COLUMNS",
    "CompletenessReport",
    "ExportRow",
    "StatsReport",
    "TagCompleteness",
    "analyse_completeness",
    "camelot_for_key",
    "collect_export_rows",
    "export_completeness_csv",
    "export_completeness_json",
    "export_csv",
    "export_html",
    "export_json",
    "export_m3u",
    "resolve_columns",
    "scan_directory",
]
