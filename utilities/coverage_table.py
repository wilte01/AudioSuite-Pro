"""coverage_table.py - coverage.py's JSON payload as a per-package table.

The suite's coverage verdict is one number (``[tool.coverage.report]
fail_under``), and a single number says nothing about *where* the cold code is.
This script reads the JSON report coverage.py already writes and groups it by
top-level package, so a release can see which modules are thinly tested before
they are refactored - the question WP-10 C-I9 exists to answer.

It is an artefact, not a gate. There is no threshold here and no verdict to
argue with: the exit status distinguishes "the table was produced" (``0``) from
"no table could be produced" (``2``), because a missing or malformed payload
must never publish an empty table that reads like a healthy one.

Usage::

    pytest --cov --cov-report=json:coverage.json
    python utilities/coverage_table.py --payload coverage.json \\
        --output coverage-table.md

Changed in 2.4.3: initial version (WP-10 C-I9).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

#: The table was produced.
EXIT_OK = 0

#: No table could be produced: a missing, unparsable or shaped-wrong payload.
EXIT_UNUSABLE = 2

#: Group name for a module that sits directly at the repository root.
ROOT_GROUP = "<root>"


class PayloadError(ValueError):
    """coverage.py's payload is missing, unparsable or shaped unexpectedly."""


@dataclass(frozen=True)
class PackageCoverage:
    """Statement coverage for one top-level package."""

    name: str
    statements: int
    covered: int

    @property
    def missed(self) -> int:
        """Return the number of statements with no executed line."""
        return max(self.statements - self.covered, 0)

    @property
    def percent(self) -> float:
        """Return the covered share of statements as a percentage.

        An empty package reports ``100.0`` because that is what coverage.py
        itself reports for a file with nothing to measure; the table never
        invents a different convention for the same artefact.
        """
        if self.statements <= 0:
            return 100.0
        return 100.0 * self.covered / self.statements


def package_of(filename: str) -> str:
    """Return the top-level package a coverage entry belongs to.

    Args:
        filename: A path as coverage.py reports it - relative and normally
            slash-separated, but a payload from a Windows host is accepted too.

    Returns:
        The first path component, or :data:`ROOT_GROUP` for a module directly
        at the repository root.
    """
    normalised = filename.replace("\\", "/")
    while normalised.startswith("./"):
        normalised = normalised[2:]
    if "/" not in normalised:
        return ROOT_GROUP
    return normalised.split("/", 1)[0]


def _count(summary: dict[str, Any], key: str, source: Path, filename: str) -> int:
    """Return an integer field of a file's coverage summary, or raise.

    Args:
        summary: The file entry's ``summary`` object.
        key: The field to read.
        source: The payload's path, named in the error.
        filename: The file the summary belongs to, named in the error.

    Returns:
        The field as an integer.

    Raises:
        PayloadError: the field is absent, or is not an integer (a bool is not
            an integer here, and a numeric string is a shape this script does
            not guess at).
    """
    value = summary.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PayloadError(
            f"{source}: {filename} has no integer {key!r} in its summary "
            f"(found {value!r})"
        )
    return value


def summarise(raw: object, source: Path) -> list[PackageCoverage]:
    """Group a parsed coverage payload by package, coldest first.

    Args:
        raw: The payload as :func:`json.loads` returned it.
        source: The path it came from, named in any error.

    Returns:
        One :class:`PackageCoverage` per top-level package, sorted by ascending
        coverage then name, so the packages a release should look at first are
        the ones a reader sees first.

    Raises:
        PayloadError: the payload is not an object with a non-empty ``files``
            mapping, an entry is not a filename-to-object pair, a file has no
            ``summary`` object, or a summary field is not an integer.
    """
    if not isinstance(raw, dict):
        raise PayloadError(
            f"{source}: expected a JSON object, got {type(raw).__name__}"
        )
    files = raw.get("files")
    if not isinstance(files, dict) or not files:
        raise PayloadError(
            f"{source}: no files were measured - an empty payload is not a "
            "coverage table"
        )

    totals: dict[str, list[int]] = {}
    for filename, entry in files.items():
        if not isinstance(filename, str) or not isinstance(entry, dict):
            raise PayloadError(
                f"{source}: a 'files' entry is not a filename-to-object pair"
            )
        summary = entry.get("summary")
        if not isinstance(summary, dict):
            raise PayloadError(f"{source}: {filename} has no 'summary' object")
        statements = _count(summary, "num_statements", source, filename)
        covered = _count(summary, "covered_lines", source, filename)
        bucket = totals.setdefault(package_of(filename), [0, 0])
        bucket[0] += statements
        bucket[1] += covered

    packages = [
        PackageCoverage(name=name, statements=values[0], covered=values[1])
        for name, values in totals.items()
    ]
    return sorted(packages, key=lambda package: (package.percent, package.name))


def render_table(packages: Sequence[PackageCoverage]) -> str:
    """Render grouped coverage as a Markdown table, with a total row.

    Args:
        packages: The groups to render, in the order they should appear.

    Returns:
        The table as Markdown, ending with a newline. The total row sums the
        groups rather than reading the payload's own ``totals``, so the table
        is internally consistent even if a payload was produced with a filter.
    """
    total = PackageCoverage(
        name="Total",
        statements=sum(package.statements for package in packages),
        covered=sum(package.covered for package in packages),
    )
    lines = [
        "## Per-package coverage",
        "",
        "| Package | Statements | Covered | Cover |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| `{package.name}` | {package.statements:,} | {package.covered:,} | "
        f"{package.percent:.1f}% |"
        for package in packages
    )
    lines.append(
        f"| **{total.name}** | **{total.statements:,}** | **{total.covered:,}** | "
        f"**{total.percent:.1f}%** |"
    )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Render one payload's per-package table.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        :data:`EXIT_OK` when a table was produced, :data:`EXIT_UNUSABLE` when
        the payload or the output could not be read or written.
    """
    parser = argparse.ArgumentParser(
        description="Render coverage.py's JSON report as a per-package table."
    )
    parser.add_argument(
        "--payload",
        type=Path,
        default=Path("coverage.json"),
        help="the file written by --cov-report=json (default: coverage.json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="write the table here instead of stdout",
    )
    args = parser.parse_args(argv)

    try:
        text = args.payload.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] cannot read {args.payload}: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    try:
        packages = summarise(json.loads(text), args.payload)
    except json.JSONDecodeError as exc:
        print(f"[ERROR] {args.payload} is not JSON: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    except PayloadError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_UNUSABLE

    table = render_table(packages)
    if args.output is None:
        print(table, end="")
        return EXIT_OK
    try:
        args.output.write_text(table, encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] cannot write {args.output}: {exc}", file=sys.stderr)
        return EXIT_UNUSABLE
    print(f"[OK] wrote {args.output} ({len(packages)} package(s))")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
