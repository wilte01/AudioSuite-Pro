"""changed_in_budget.py - keep the per-file change notes from growing unchecked.

Every first-party change adds a ``Changed in <version>:`` line to the file it
touched (``tests/test_release_notes.py`` enforces that a changed file carries
one). The notes are the record a reviewer reads, and while the cleanup they
describe is deferred, that prose keeps growing one line per change with nothing
measuring it.

This script is the ceiling. It counts the note lines in the tree, compares the
counts against a committed baseline, and refuses growth until the baseline is
re-recorded deliberately. It is a gate, unlike the coverage table: an
over-budget tree fails, and a version that carries notes but has no recorded
ceiling fails too, so a new release window starts with a recorded number rather
than an implied infinity.

Usage::

    python utilities/changed_in_budget.py --check    # CI: refuse growth
    python utilities/changed_in_budget.py --record   # deliberate re-baseline

Changed in 2.4.3: initial version (WP-10 C-I2).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

#: The tree is inside its recorded ceiling.
EXIT_OK = 0

#: The tree carries more notes than the baseline records, or a version has none.
EXIT_OVER = 1

#: No verdict could be computed: a missing, unparsable or shaped-wrong baseline.
EXIT_UNUSABLE = 2

#: The marker ``tests/test_release_notes.py`` already requires of a changed file.
NOTE_PATTERN = re.compile(r"Changed in (\d+\.\d+\.\d+)")

#: Directories that are not first-party source for this count. ``documentation``
#: carries prose by the page, and a plugin or a packaging tree is not this
#: repository's change record.
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "documentation",
        "packaging",
        "plugins",
    }
)

#: The committed baseline, resolved from this script so a caller cannot point
#: the check at a different file by accident.
DEFAULT_BASELINE = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "data"
    / "changed_in_baseline.json"
)

#: The sentence the baseline file carries, so its purpose survives a reader who
#: finds the file before the script.
BASELINE_COMMENT = (
    "Note lines per version for utilities/changed_in_budget.py - do not edit by "
    "hand; run `python utilities/changed_in_budget.py --record` after deciding "
    "the new notes are wanted."
)


class BaselineError(ValueError):
    """The baseline is missing, unparsable or shaped unexpectedly."""


def note_counts(root: Path) -> dict[str, int]:
    """Count ``Changed in <version>`` lines per version under *root*.

    Args:
        root: The tree to scan; ``.venv``, ``documentation`` and the other
            :data:`EXCLUDED_DIRS` are skipped.

    Returns:
        One entry per version that carries at least one note. An unreadable
        file is skipped rather than aborting the count, because a tree that
        cannot be fully read must still produce a number a human can compare.
    """
    counts: dict[str, int] = {}
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if name not in EXCLUDED_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            try:
                text = (Path(current) / name).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for line in text.splitlines():
                match = NOTE_PATTERN.search(line)
                if match:
                    version = match.group(1)
                    counts[version] = counts.get(version, 0) + 1
    return counts


def load_baseline(path: Path) -> dict[str, int]:
    """Read the committed baseline.

    Args:
        path: The JSON file :func:`write_baseline` produces.

    Returns:
        Version to recorded note count.

    Raises:
        BaselineError: the file is unreadable or not JSON, or its ``versions``
            is not an object of version to non-negative integer.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BaselineError(f"cannot read the baseline {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BaselineError(f"{path} is not JSON: {exc}") from exc
    versions = raw.get("versions") if isinstance(raw, dict) else None
    if not isinstance(versions, dict) or not versions:
        raise BaselineError(
            f"{path}: expected a non-empty 'versions' object - an empty "
            "baseline would let every note pass unchecked"
        )
    recorded: dict[str, int] = {}
    for version, value in versions.items():
        if not isinstance(version, str) or not NOTE_PATTERN.fullmatch(
            f"Changed in {version}"
        ):
            raise BaselineError(f"{path}: {version!r} is not a dotted version")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BaselineError(f"{path}: {version} has a non-integer count {value!r}")
        recorded[version] = value
    return recorded


def failures(measured: dict[str, int], baseline: dict[str, int]) -> list[str]:
    """Return the reasons the tree is over its recorded ceiling.

    Args:
        measured: The counts :func:`note_counts` just produced.
        baseline: The counts :func:`load_baseline` recorded.

    Returns:
        One sentence per problem, empty when the tree is within budget. A
        version with no recorded ceiling is a problem rather than a new
        allowance: silence there is how the prose grows by one release at a
        time.
    """
    problems: list[str] = []
    for version in sorted(set(measured) - set(baseline)):
        problems.append(
            f"{version} carries {measured[version]} note line(s) but the baseline "
            "records none - record a ceiling with --record"
        )
    for version in sorted(measured):
        allowed = baseline.get(version)
        if allowed is not None and measured[version] > allowed:
            problems.append(
                f"{version} grew from {allowed} to {measured[version]} note line(s)"
            )
    measured_total = sum(measured.values())
    recorded_total = sum(baseline.values())
    if measured_total > recorded_total:
        problems.append(
            f"the tree carries {measured_total} note lines against a recorded "
            f"{recorded_total}"
        )
    return problems


def write_baseline(path: Path, counts: dict[str, int]) -> None:
    """Write *counts* as the committed baseline.

    Args:
        path: The file to write.
        counts: The counts ``--record`` just measured, written exactly - a
            ceiling above the current tree would let growth pass unnoticed.
    """
    payload = {
        "_comment": BASELINE_COMMENT,
        "_recorded": date.today().isoformat(),
        "versions": {version: counts[version] for version in sorted(counts)},
        "total": sum(counts.values()),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Check the tree against the baseline, or record a new one.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        :data:`EXIT_OK`, :data:`EXIT_OVER` or :data:`EXIT_UNUSABLE`.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check",
        action="store_true",
        help="compare the tree against the baseline (the default)",
    )
    action.add_argument(
        "--record",
        action="store_true",
        help="rewrite the baseline from the tree, deliberately",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help=f"the committed baseline (default: {DEFAULT_BASELINE})",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="the tree to scan (default: the repository root)",
    )
    args = parser.parse_args(argv)

    measured = note_counts(args.root)

    if args.record:
        try:
            write_baseline(args.baseline, measured)
        except OSError as exc:
            print(f"[ERROR] cannot write {args.baseline}: {exc}", file=sys.stderr)
            return EXIT_UNUSABLE
        print(
            f"[OK] recorded {sum(measured.values())} note line(s) across "
            f"{len(measured)} version(s) in {args.baseline}"
        )
        return EXIT_OK

    try:
        baseline = load_baseline(args.baseline)
    except BaselineError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_UNUSABLE

    problems = failures(measured, baseline)
    if problems:
        for problem in problems:
            print(f"[ERROR] {problem}", file=sys.stderr)
        return EXIT_OVER

    print(
        f"[OK] changed-in budget: {sum(measured.values())} note line(s) across "
        f"{len(measured)} version(s), at or under the recorded ceiling"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
