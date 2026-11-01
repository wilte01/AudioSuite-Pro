"""Decide whether a CI change set needs the full-suite leg.

The suite runs once, on the 3.11 floor, and is almost the whole price of a push:
about 61 of its 69 billable minutes (``tests/test_ci_cost.py``). A change that
only edits plans, guides or documentation cannot change what that suite
executes, yet it paid the same bill - the 2.3.0 record commit ``d753c6e``, six
lines of Markdown, took 30.9 minutes of wall clock. This module answers the one
question the workflow's ``changes`` job asks: is every changed path a document?

The rule is narrow on purpose. A path is documentation when it is a Markdown
file anywhere in the tree (``PLAN_*.md``, ``CHANGELOG.md``, ``AGENTS.md``, the
README) or anything under ``documentation/`` - the one documentation tree -
except a Python file there, which is Sphinx's ``conf.py`` and is executed when
the suite builds the site. Everything else - tool code, tests, fixtures,
``pyproject.toml``, ``uv.lock``, the workflow itself - needs the suite.

It also fails open. An empty change set needs the suite, because "no paths" is
evidence that the diff failed rather than that the push was documentation, and
the workflow wraps this in a second guard: an unusable range or a crashed
classifier there also answers "run the suite". Skipping the leg is safe only
when the change is provably documentation, so every other answer runs it.

Usage, from the ``changes`` job::

    git diff --name-only "$base" "$head" |
        python utilities/ci_changed_paths.py --github-output "$GITHUB_OUTPUT"

Changed in 2.3.1: initial version, with the `changes` job that calls it.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

#: The one documentation tree (``AGENTS.md``, *Documentation Formats*).
DOCUMENTATION_PREFIX = "documentation/"

#: A rendered document: a plan, a changelog, a site page, a guide's source.
MARKDOWN_SUFFIX = ".md"

#: Code that lives inside the documentation tree (Sphinx's ``conf.py``).
PYTHON_SUFFIX = ".py"

#: The output key the ``changes`` job publishes and the ``test`` job reads.
GITHUB_OUTPUT_KEY = "suite"

#: How many paths the log names before summarising. A release-sized change set
#: would otherwise bury the verdict in its own evidence.
MAX_LISTED_PATHS = 40


def is_documentation(path: str) -> bool:
    """Return whether *path* is a document, i.e. nothing the suite executes.

    Args:
        path: A repository-relative path, as ``git diff --name-only`` prints it.

    Returns:
        True for Markdown and for the documentation tree's non-Python files.
    """
    normalised = path.strip().replace("\\", "/")
    if normalised.endswith(PYTHON_SUFFIX):
        return False
    if normalised.endswith(MARKDOWN_SUFFIX):
        return True
    return normalised.startswith(DOCUMENTATION_PREFIX)


@dataclass(frozen=True)
class Verdict:
    """The classifier's answer, and the reason a reviewer can check."""

    needs_suite: bool
    reason: str
    paths: tuple[str, ...]

    def output_line(self) -> str:
        """Return the ``suite=`` line the runner reads as the job output."""
        return f"{GITHUB_OUTPUT_KEY}={'true' if self.needs_suite else 'false'}"


def classify(paths: Iterable[str]) -> Verdict:
    """Classify a change set.

    Args:
        paths: The changed paths, one per line of ``git diff --name-only``.

    Returns:
        A verdict whose ``needs_suite`` is True unless every path is a document
        and the set is non-empty.
    """
    changed = tuple(path for path in (raw.strip() for raw in paths) if path)
    if not changed:
        return Verdict(True, "the diff named no paths, so nothing is proved", changed)
    code = tuple(path for path in changed if not is_documentation(path))
    if code:
        return Verdict(
            True,
            f"{len(code)} of {len(changed)} changed path(s) are not documentation "
            f"(first: {code[0]})",
            changed,
        )
    return Verdict(
        False,
        f"all {len(changed)} changed path(s) are documentation",
        changed,
    )


def _report(verdict: Verdict) -> None:
    """Print the change set and the verdict, so a skip is auditable."""
    for path in verdict.paths[:MAX_LISTED_PATHS]:
        kind = "document" if is_documentation(path) else "runs"
        print(f"  [{kind}] {path}")
    hidden = len(verdict.paths) - MAX_LISTED_PATHS
    if hidden > 0:
        print(f"  ... and {hidden} more")
    print(f"suite={'true' if verdict.needs_suite else 'false'} - {verdict.reason}")


def main(argv: list[str] | None = None) -> int:
    """Classify stdin's changed paths and publish the verdict."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--github-output",
        type=Path,
        default=None,
        metavar="FILE",
        help="append the suite= line to this file (the runner's $GITHUB_OUTPUT)",
    )
    args = parser.parse_args(argv)

    verdict = classify(sys.stdin.read().splitlines())
    _report(verdict)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(verdict.output_line() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
