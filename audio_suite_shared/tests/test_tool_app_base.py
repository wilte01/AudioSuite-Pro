"""Tests for audio_suite_shared.tool_app_base — the analysis/tag scaffold.

The scaffold is thin by design: a subclass supplies the header, the per-file
lines and its extra rows, and the base writes the report.  That written report
is the piece a tool cannot see, so it is what is locked here — the three
subclasses (``bpm_analyzer``, ``lyrics_manager``, ``album_genre_tagger``) all
reach the footer through this one completion.

Changed in 2.9.0: new file, after the footer moved to
``audio_suite_shared.run_report`` (D35).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from audio_suite_shared.tool_app_base import AnalysisTagToolApp


def shell(tmp_path: Path) -> AnalysisTagToolApp:
    """Return the scaffold without building any widgets.

    Args:
        tmp_path: The folder the report is written into.

    Returns:
        The shell, ready for a completion call.
    """
    app = object.__new__(AnalysisTagToolApp)
    app.root = MagicMock()
    app.TAGGED_LABEL = "Tagged"
    app._log_path = str(tmp_path / "analysis_dry_run_log.txt")
    app._summary_extras = MagicMock(return_value=[])
    return app


class TestCompletionReport:
    """The report the base writes from a finished run."""

    def test_the_report_ends_with_the_shared_footer(self, tmp_path: Path) -> None:
        app = shell(tmp_path)
        app._summary_extras = MagicMock(return_value=[("Outside range", "1")])

        app._on_complete(
            header=["BPM ANALYSIS REPORT\n"],
            total=2,
            processed=2,
            skipped=1,
            errors=0,
            duration_secs=75.0,
            log_entries=["[OK] a.mp3\n"],
        )

        lines = (
            (tmp_path / "analysis_dry_run_log.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert lines == [
            "BPM ANALYSIS REPORT",
            "[OK] a.mp3",
            "",
            "=" * 60,
            "SUMMARY:",
            "Total files: 2",
            "Tagged: 1",
            "Skipped: 1",
            "Errors: 0",
            "Outside range: 1",
            "Time: 01:15",
        ]
        assert app.root.after.call_count == 1

    def test_a_tool_with_no_extra_rows_writes_only_the_counters(
        self, tmp_path: Path
    ) -> None:
        app = shell(tmp_path)

        app._on_complete(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
        )

        lines = (
            (tmp_path / "analysis_dry_run_log.txt")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert lines == [
            "",
            "=" * 60,
            "SUMMARY:",
            "Total files: 1",
            "Tagged: 1",
            "Skipped: 0",
            "Errors: 0",
            "Time: 00:00",
        ]
