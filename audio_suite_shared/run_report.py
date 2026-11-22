"""run_report.py — the SUMMARY footer every run report ends with.

A run report is the file a window's View Log opens: a header, one line per
processed file, then a ``SUMMARY:`` footer that repeats the counts and the
wall-clock time (AGENTS.md, *Run Reports vs Program Logs*).  Two writers owned
that footer — the analysis scaffold's completion and the shared shell's
``_write_run_report_standard`` — so its shape lives here once.

Changed in 2.9.0: new module, extracted from the two writers (D35).
"""

from __future__ import annotations

from collections.abc import Iterable

__all__ = ["RULE_WIDTH", "summary_lines"]

#: The width of the rule that separates the per-file lines from the footer.
RULE_WIDTH = 60


def summary_lines(
    *,
    total: int,
    tagged: int,
    tagged_label: str,
    skipped: int,
    errors: int,
    duration_secs: float,
    rows: Iterable[tuple[str, str]] = (),
) -> list[str]:
    """Return the ``SUMMARY:`` footer lines for one run report.

    Args:
        total: Files the run visited.
        tagged: Files handled without being skipped or erroring.
        tagged_label: The tool's own word for that count ("Tagged",
            "Repaired", "Files read"); the footer prints it verbatim.
        skipped: Files left alone.
        errors: Files that failed.
        duration_secs: Wall-clock run time.
        rows: The run's extra ``(label, value)`` summary rows, in display
            order.

    Returns:
        The footer as writable lines, starting with the blank line and the
        rule that separate it from the per-file lines.
    """
    minutes = int(duration_secs // 60)
    seconds = int(duration_secs % 60)
    lines: list[str] = [
        "\n" + "=" * RULE_WIDTH + "\n",
        "SUMMARY:\n",
        f"Total files: {total}\n",
        f"{tagged_label}: {tagged}\n",
        f"Skipped: {skipped}\n",
        f"Errors: {errors}\n",
    ]
    lines.extend(f"{label}: {value}\n" for label, value in rows)
    lines.append(f"Time: {minutes:02d}:{seconds:02d}\n")
    return lines
