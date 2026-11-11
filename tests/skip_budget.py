"""
skip_budget.py — refuse an unrecorded skip, the way the note budget refuses growth.

``utilities/changed_in_budget.py`` holds the ``Changed in <version>`` prose to a
committed ceiling, so a new note is a decision rather than an accident.  A skip
needs the same treatment for a sharper reason: it is the one test outcome that
still reports green.  ``12431 passed, 11 skipped`` is a pass, so a test that
quietly stops verifying anything - because a package is missing on the runner,
an ffmpeg build lacks a resampler, a host cannot create symlinks - costs
coverage silently.  The 2.6.0 floor leg carried six such skips for exactly that
reason: ``tests/test_py_typed.py`` guarded its wheel checks with
``pytest.importorskip("setuptools")`` while nothing installed setuptools on a
runner, and a green CI certified a wheel nobody had inspected.

The budget is a committed list of the reasons a run may report, each with the
most skips allowed to carry it, plus a ceiling for the run as a whole.  A
reason outside the list fails the session; so does exceeding an entry, and so
does exceeding the total.  A skip that stops happening is not a failure: hosts
differ, and the budget is the union across them, so the CI-only libsoxr skips
sit beside the developer-host-only symlink skip.

Recording one is a deliberate hand edit with its reason beside it, exactly like
an allowlist entry - the failure message quotes the reason text to copy and
names the file it goes in.

The enforcement lives in ``conftest.py``'s ``pytest_sessionfinish``; this module
holds the rule, so the rule is tested against fixtures rather than against a
subprocess that runs the suite.

Changed in 2.6.0: initial version.  The 2.6.0 floor leg's eleven skips were
found by reading a log, and six of them were an environment gap nobody had
recorded; this is the gate that would have said so on the run that introduced
them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: The committed budget, resolved from this module so a caller cannot point the
#: gate at a different file by accident.
DEFAULT_BUDGET = Path(__file__).resolve().parent / "data" / "skip_budget.json"


@dataclass(frozen=True)
class Entry:
    """One permitted skip reason and the most skips that may carry it.

    Attributes:
        match: A substring of the skip reason, so a reason carrying a path or a
            measured value still matches without the budget pinning that detail.
        max_skips: The most skips this run may report with this reason.  A
            developer host may report fewer than a runner - the union is what
            is recorded, and a shortfall is not a failure.
        why: Why the skip is acceptable.  Required, because a budget entry
            without a reason is how a gap becomes a rule.
    """

    match: str
    max_skips: int
    why: str


@dataclass(frozen=True)
class Skip:
    """One skipped test, as the session observed it."""

    nodeid: str
    reason: str


class BudgetError(ValueError):
    """The budget file is missing, unparsable or shaped unexpectedly."""


def load_budget(path: Path) -> tuple[tuple[Entry, ...], int]:
    """Read the committed skip budget.

    Args:
        path: The JSON file this module's ``DEFAULT_BUDGET`` names.

    Returns:
        ``(entries, total)``: the permitted reasons, and the most skips the run
        as a whole may report.

    Raises:
        BudgetError: If the file cannot be read, is not JSON, or its ``reasons``
            is not a non-empty list of well-formed entries with an integer
            ``total``.  An empty entry list is refused because it would reject
            every skip rather than allow a deliberate one, and a missing total
            would let the run's overall count go unmeasured.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BudgetError(f"cannot read the skip budget {path}: {exc}") from exc
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BudgetError(f"{path} is not JSON: {exc}") from exc

    reasons = raw.get("reasons") if isinstance(raw, dict) else None
    if not isinstance(reasons, list) or not reasons:
        raise BudgetError(
            f"{path}: 'reasons' must be a non-empty list - an empty budget "
            "would reject every skip instead of recording the ones that are "
            "acceptable"
        )
    entries: list[Entry] = []
    for item in reasons:
        if not isinstance(item, dict):
            raise BudgetError(f"{path}: every 'reasons' entry must be an object")
        match = item.get("match")
        max_skips = item.get("max")
        why = item.get("why")
        if not isinstance(match, str) or not match.strip():
            raise BudgetError(f"{path}: an entry has no 'match' text")
        if isinstance(max_skips, bool) or not isinstance(max_skips, int):
            raise BudgetError(f"{path}: {match!r} has no integer 'max'")
        if max_skips < 1:
            raise BudgetError(f"{path}: {match!r} allows {max_skips} skips")
        if not isinstance(why, str) or not why.strip():
            raise BudgetError(f"{path}: {match!r} does not say why it is allowed")
        entries.append(Entry(match=match, max_skips=max_skips, why=why))

    total = raw.get("total") if isinstance(raw, dict) else None
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        raise BudgetError(f"{path}: 'total' must be a positive integer")
    return tuple(entries), total


def violations(skips: list[Skip], entries: tuple[Entry, ...], total: int) -> list[str]:
    """Return the reasons *skips* break the budget; empty when within it.

    Args:
        skips: Every skip the session reported, in any order.
        entries: The permitted reasons, from :func:`load_budget`.
        total: The most skips the run may report overall.

    Returns:
        One human-readable sentence per problem.  Each names the test, because
        the point of the gate is to make the offending skip findable without
        reading the whole log.
    """
    problems: list[str] = []
    counts = {entry.match: 0 for entry in entries}
    for skip in skips:
        matched = [entry for entry in entries if entry.match in skip.reason]
        if not matched:
            problems.append(
                f"{skip.nodeid}: {skip.reason!r} is not in the skip budget - "
                "add its text to tests/data/skip_budget.json with the count and "
                "why it is acceptable"
            )
            continue
        for entry in matched:
            counts[entry.match] += 1

    for entry in entries:
        counted = counts[entry.match]
        if counted > entry.max_skips:
            problems.append(
                f"{counted} skip(s) carry {entry.match!r}, over the budgeted "
                f"{entry.max_skips} - either a new test needs the same "
                "prerequisite or a declared one is missing on this host"
            )
    if len(skips) > total:
        problems.append(
            f"the run reported {len(skips)} skips against a budgeted total of {total}"
        )
    return problems
