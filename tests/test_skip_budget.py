"""Locks for the skip budget: the committed file, and the rule applied to it.

``tests/skip_budget.py`` holds the rule, so it is tested here against fixtures
rather than through a subprocess that would have to run a suite to produce a
skip.  The committed file is checked too, and that half is the load-bearing one:
a budget that no longer names a reason the suite really produces would red the
next run on the host that produces it, and a budget with no total would let the
run's overall skip count go unmeasured.

Changed in 2.7.0: initial version.  The 2.6.0 floor leg's eleven skips included
six ``importorskip("setuptools")`` skips that nothing had recorded, and a green
run reported them as green.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests import skip_budget

BUDGET = Path(__file__).resolve().parent / "data" / "skip_budget.json"

#: Reasons the suite is known to produce on some host.  Each must stay in the
#: budget: dropping one turns the next run on that host red for no reason.
KNOWN_REASONS = (
    "broken Tcl/Tk environment",
    "Symlink creation unavailable",
    "Unix-only permission check",
    "built without libsoxr",
)


def _entry(match: str = "known reason", max_skips: int = 1) -> skip_budget.Entry:
    """Return one budget entry for a rule test."""
    return skip_budget.Entry(match=match, max_skips=max_skips, why="a test fixture")


class TestTheCommittedBudget:
    """The file the session reads is present, shaped right and complete."""

    def test_it_parses_and_is_not_empty(self) -> None:
        entries, total = skip_budget.load_budget(BUDGET)

        assert entries, "the skip budget holds no entries"
        assert total >= 1

    def test_every_entry_states_why_it_is_allowed(self) -> None:
        entries, _total = skip_budget.load_budget(BUDGET)

        assert all(entry.why.strip() for entry in entries)

    def test_it_names_every_reason_the_suite_produces(self) -> None:
        entries, _total = skip_budget.load_budget(BUDGET)
        recorded = " ".join(entry.match for entry in entries)

        for reason in KNOWN_REASONS:
            assert reason in recorded, (
                f"the budget no longer names {reason!r}, so the next run on the "
                "host that produces it fails with a skip it never recorded"
            )

    def test_the_total_admits_the_widest_host(self) -> None:
        """CI reports the Tk, Unix-only and three libsoxr skips together."""
        entries, total = skip_budget.load_budget(BUDGET)

        assert total >= 5, (
            f"a total of {total} cannot admit the five skips the floor leg "
            "reports, so CI would fail on arrival"
        )
        assert total >= max(entry.max_skips for entry in entries)


class TestTheRule:
    """A recorded skip passes; an unrecorded one, or growth, fails."""

    def test_a_budgeted_skip_passes(self) -> None:
        skips = [skip_budget.Skip("tests/x.py::test_y", "it needs the known reason")]

        assert skip_budget.violations(skips, (_entry(),), 5) == []

    def test_an_unrecorded_reason_fails_and_quotes_itself(self) -> None:
        skips = [skip_budget.Skip("tests/x.py::test_y", "a brand new excuse")]

        problems = skip_budget.violations(skips, (_entry(),), 5)

        assert problems, "an unrecorded skip passed the budget"
        assert "a brand new excuse" in problems[0]
        assert "tests/x.py::test_y" in problems[0], (
            "the failure must name the test, or the skip is not findable"
        )

    def test_exceeding_one_entry_fails(self) -> None:
        skips = [
            skip_budget.Skip(f"tests/x.py::test_{index}", "known reason")
            for index in range(3)
        ]

        problems = skip_budget.violations(skips, (_entry(max_skips=2),), 5)

        assert any("over the budgeted 2" in problem for problem in problems)

    def test_exceeding_the_total_fails(self) -> None:
        skips = [skip_budget.Skip("tests/x.py::test_y", "known reason")] * 2

        problems = skip_budget.violations(skips, (_entry(max_skips=5),), 1)

        assert any("budgeted total" in problem for problem in problems)

    def test_a_shortfall_is_not_a_failure(self) -> None:
        """Hosts differ: the budget is a union, so fewer skips is normal."""
        assert skip_budget.violations([], (_entry(),), 5) == []


class TestTheBudgetRefusesShapesThatCouldNotFail:
    """A malformed budget raises rather than silently permitting everything."""

    def test_an_empty_entry_list_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "budget.json"
        path.write_text('{"total": 3, "reasons": []}', encoding="utf-8")

        with pytest.raises(skip_budget.BudgetError, match="non-empty"):
            skip_budget.load_budget(path)

    def test_an_entry_without_a_reason_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "budget.json"
        path.write_text(
            '{"total": 3, "reasons": [{"match": "x", "max": 1}]}', encoding="utf-8"
        )

        with pytest.raises(skip_budget.BudgetError, match="why"):
            skip_budget.load_budget(path)

    def test_a_missing_total_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "budget.json"
        path.write_text(
            '{"reasons": [{"match": "x", "max": 1, "why": "ok"}]}', encoding="utf-8"
        )

        with pytest.raises(skip_budget.BudgetError, match="total"):
            skip_budget.load_budget(path)

    def test_a_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(skip_budget.BudgetError, match="cannot read"):
            skip_budget.load_budget(tmp_path / "absent.json")
