"""
library_stats.py — Backward-compatible re-export of core scanning logic.

All public API was moved to ``core/file_processor.py`` for consistency
with the rest of the suite.  This stub re-exports from there so that
existing imports (``from library_stats.library_stats import ...``) continue
to work without changes.
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

__all__ = [
    "CompletenessReport",
    "StatsReport",
    "TagCompleteness",
    "analyse_completeness",
    "export_completeness_csv",
    "export_completeness_json",
    "export_csv",
    "export_json",
    "scan_directory",
]
