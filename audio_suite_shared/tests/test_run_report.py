"""Tests for audio_suite_shared.run_report — the run report's footer.

Changed in 2.9.0: new file.  The ``SUMMARY:`` footer was built twice, by the
analysis scaffold's completion and the shared shell's writer, so it lives in one
function and both writers are locked to it (D35).

Changed in 2.9.0: locks the skipped-label rules and every window that
writes the footer (D36).

Changed in 2.9.0: ``tool_app_base`` is deleted, so the writer list drops
the scaffold's file (D37).

Changed in 2.9.0: pins the total-label wording and lists the three reports
that word their first counter differently (D39).

Changed in 2.9.0: ``AnalysisAppBase`` is deleted with Mood Analyzer, so the
writer list drops it and the shell's writer is the analysis pair's only one
(C1 stage 3, D54).
"""

from __future__ import annotations

from pathlib import Path

from audio_suite_shared.run_report import RULE_WIDTH, summary_lines

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: The two characters a Python source literal spells a newline with.
_NL = chr(92) + "n"


def empty_summary() -> list[str]:
    """Return the footer of a run that visited nothing.

    Returns:
        The footer lines.
    """
    return summary_lines(
        total=0,
        tagged=0,
        tagged_label="Tagged",
        skipped=0,
        errors=0,
        duration_secs=0.0,
    )


class TestSummaryLines:
    """The footer's shape, which every report reader parses by hand."""

    def test_the_footer_is_the_shared_shape(self) -> None:
        lines = summary_lines(
            total=2,
            tagged=1,
            tagged_label="Tagged",
            skipped=1,
            errors=0,
            duration_secs=75.0,
        )

        assert lines == [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            "Total files: 2\n",
            "Tagged: 1\n",
            "Skipped: 1\n",
            "Errors: 0\n",
            "Time: 01:15\n",
        ]

    def test_the_rule_is_the_documented_sixty(self) -> None:
        assert RULE_WIDTH == 60
        assert empty_summary()[0] == "\n" + "=" * 60 + "\n"

    def test_the_tools_rows_sit_between_the_counters_and_the_time(self) -> None:
        lines = summary_lines(
            total=4,
            tagged=4,
            tagged_label="Files scanned",
            skipped=0,
            errors=0,
            duration_secs=0.0,
            rows=(("Duplicate groups", "2"), ("Files quarantined", "3")),
        )

        assert lines[4:9] == [
            "Skipped: 0\n",
            "Errors: 0\n",
            "Duplicate groups: 2\n",
            "Files quarantined: 3\n",
            "Time: 00:00\n",
        ]

    def test_the_label_is_printed_verbatim(self) -> None:
        lines = summary_lines(
            total=4,
            tagged=4,
            tagged_label="Files read",
            skipped=0,
            errors=0,
            duration_secs=0.0,
        )

        assert "Files read: 4\n" in lines
        assert "Tagged: 4\n" not in lines

    def test_the_total_label_is_printed_verbatim(self) -> None:
        lines = summary_lines(
            total=3,
            total_label="Files examined",
            tagged=2,
            tagged_label="Images updated",
            skipped=1,
            errors=0,
            duration_secs=0.0,
        )

        assert "Files examined: 3" + chr(10) in lines
        assert "Total files: 3" + chr(10) not in lines

    def test_the_default_total_label_is_total_files(self) -> None:
        assert "Total files: 0" + chr(10) in empty_summary()

    def test_the_skipped_label_is_printed_verbatim(self) -> None:
        lines = summary_lines(
            total=3,
            tagged=2,
            tagged_label="Tagged",
            skipped=1,
            skipped_label="Skipped (no BPM)",
            errors=0,
            duration_secs=0.0,
        )

        assert "Skipped (no BPM): 1" + chr(10) in lines
        assert "Skipped: 1" + chr(10) not in lines

    def test_a_missing_skipped_label_omits_the_line(self) -> None:
        lines = summary_lines(
            total=3,
            tagged=3,
            tagged_label="Successfully processed",
            skipped=1,
            skipped_label=None,
            errors=0,
            duration_secs=0.0,
        )

        assert not any(line.startswith("Skipped") for line in lines)
        assert "Successfully processed: 3" + chr(10) in lines

    def test_the_time_pads_each_field_to_two_digits(self) -> None:
        def time_line(seconds: float) -> str:
            return summary_lines(
                total=0,
                tagged=0,
                tagged_label="Tagged",
                skipped=0,
                errors=0,
                duration_secs=seconds,
            )[-1]

        assert time_line(9.0) == "Time: 00:09\n"
        assert time_line(3661.0) == "Time: 61:01\n"


class TestEveryWriterUsesIt:
    """Every report writer must call the helper, not rebuild the block."""

    WRITERS = (
        "audio_suite_shared/suite_app.py",
        "album_art_normalizer/app.py",
        "bpm_analyzer/app.py",
        "channel_tools/core/processor.py",
        "file_reorganizer/app.py",
        "lyrics_manager/app.py",
        "metadata_scrubber/app.py",
        "music_format_converter/app.py",
        "pitch_time/core/engine.py",
        "replaygain_analyzer/app.py",
        "tempo_analyzer/app.py",
    )

    def test_each_writer_calls_the_helper(self) -> None:
        for relative in self.WRITERS:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            assert "summary_lines(" in source, relative

    def test_no_writer_builds_the_footer_by_hand(self) -> None:
        for relative in self.WRITERS:
            source = (REPO_ROOT / relative).read_text(encoding="utf-8")
            assert f'"SUMMARY:{_NL}"' not in source, relative
            assert f'f"Total files: {{total}}{_NL}"' not in source, relative
            assert f'f"Time: {{minutes:02d}}:{{seconds:02d}}{_NL}"' not in source, (
                relative
            )
