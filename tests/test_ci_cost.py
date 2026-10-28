"""Price one push: every CI job against a billable-minute budget (scan R-17).

The workflow used to run the full suite three times — 3.11, 3.12 and 3.14 — and
that is what exhausted the account's Actions minutes mid-session (X9). At
GitHub's billing multipliers (Linux 1x, Windows 2x) those three legs were
**160.9 of a 168.0-minute run**, while the other seven jobs cost 7.1 together,
so a private repository's 2 000-3 000 minute allowance bought about a dozen
pushes a month.

The fix is structural — one full-suite leg, on the floor — so the lock is
structural too. It cannot know what tomorrow's suite costs; it can know *what
the workflow has been priced at* and refuse a change that adds cost silently:

* every job in `ci.yml` must appear in `MEASURED_BILLABLE`, and every entry
  must name a job that exists — so a new job (or a renamed one) is a deliberate
  edit with a number beside it, not a surprise on the bill;
* the `test` job must declare exactly one interpreter, must name it in its
  `name:` and must not read a matrix — a widened matrix is the change this
  exists to catch, and it is caught here rather than in a bank statement;
* that interpreter must be the floor `requires-python` declares, because the
  floor is the leg the plan forbids cutting (X9): it is the only one that runs
  the dependency graph `uv.lock` resolves below 3.12 (numpy 1.26.4 /
  scipy 1.17.1 / sphinx 9.0.4 against 2.5.4 / 1.18.1 / 9.x);
* the projected total must stay under `BILLABLE_BUDGET`, and the arithmetic
  must be shown able to reject the shape it replaced.

Every figure is measured, not guessed. GitHub exposes each job's
`started_at`/`completed_at` and each step's, so the numbers come from two real
green runs — `40668603600` (`8229b05`, the last green run before the block) and
`40579580275` — with the *higher* figure kept where the two disagree, because a
budget is a ceiling. The `test` entry is the 3.11 leg's 56.5-60.4 plus the
artifact and documentation steps it inherits from the retired 3.14 leg (0.1-0.2
minutes each, measured on that leg), rounded up.

The ledger is a ceiling on *structure*, not a stopwatch: the suite growing by a
minute does not trip it (68.7 projected, 100 allowed). When a leg genuinely
moves, the remedy is to record the new measurement here with a sentence in
`PLAN_audit_2026-10-24_deferred_p2p3.md` — never to raise the budget to fit a
second leg.

Changed in 2.1.6: initial version (R-17,
PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import re

from tests.ci_workflow import REPO_ROOT, job, job_names
from tests.test_tooling_targets import EXPECTED_FLOOR

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

#: The most a push may bill. The measured projection is 68.7, so this is a
#: ceiling with room for the suite to grow, not a number fitted to today.
BILLABLE_BUDGET = 100.0

#: GitHub's documented multipliers for standard runners, per minute.
RUNNER_MULTIPLIERS: dict[str, float] = {"ubuntu-latest": 1.0, "windows-latest": 2.0}

#: Measured billable minutes per job for one push, all of that job's legs
#: included. See the module docstring for the runs these come from.
MEASURED_BILLABLE: dict[str, float] = {
    "compile": 0.2,
    "docs-locks": 2.7,
    "lint": 0.3,
    "posix-smoke": 1.2,
    "schema-conformance": 0.2,
    "security": 0.6,
    "test": 61.4,
    "typecheck": 2.1,
}

#: The step that runs the suite, and the coverage floor that identifies it: a
#: second full leg would carry both, so the pair is a cheap, precise count.
SUITE_STEP = "Run test suite"
COVERAGE_FLOOR = "--cov-fail-under=75"


def _executed(block: str) -> str:
    """Return *block*'s executed lines.

    A YAML comment cannot start a job or install an interpreter, and these jobs
    explain the decisions they embody — including *why* the matrix has one leg —
    so a raw-text match would be satisfied by the explanation (D14).
    """
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def _runners() -> dict[str, str]:
    """Return each job's declared runner, keyed by job id."""
    return {
        name: match.group(1)
        for name in job_names()
        if (match := re.search(r"runs-on:\s*(\S+)", _executed(job(name))))
    }


def _job_with_the_suite() -> str:
    """Return the id of the one job that runs the full suite with coverage."""
    names = [name for name in job_names() if COVERAGE_FLOOR in _executed(job(name))]
    assert len(names) == 1, (
        "exactly one job must run the full suite with a coverage floor; found "
        f"{names or 'none'}"
    )
    return names[0]


class TestTheLedgerCoversTheWorkflow:
    """Every job is priced, and the ledger names nothing that is gone."""

    def test_every_job_is_in_the_ledger(self) -> None:
        declared = set(job_names())
        priced = set(MEASURED_BILLABLE)

        assert declared - priced == set(), (
            "these jobs have no measured cost, so the projection would miss "
            f"them: {sorted(declared - priced)}"
        )

    def test_the_ledger_has_no_stale_entry(self) -> None:
        stale = set(MEASURED_BILLABLE) - set(job_names())

        assert not stale, (
            f"the ledger prices jobs that no longer exist: {sorted(stale)} - a "
            "stale entry overstates the projection and hides a real increase"
        )

    def test_the_ledger_is_not_vacuous(self) -> None:
        assert len(MEASURED_BILLABLE) >= 8, (
            f"only {len(MEASURED_BILLABLE)} jobs priced - the workflow has "
            f"{len(job_names())}, so the ledger is not being read"
        )
        assert all(minutes > 0 for minutes in MEASURED_BILLABLE.values()), (
            f"a job is priced at zero: {MEASURED_BILLABLE}"
        )

    def test_every_runner_has_a_multiplier(self) -> None:
        runners = _runners()

        assert len(runners) == len(job_names()), (
            "a job has no runs-on line, so its runner cannot be priced: "
            f"{sorted(set(job_names()) - set(runners))}"
        )
        unpriced = {
            name: runner
            for name, runner in runners.items()
            if runner not in RUNNER_MULTIPLIERS
        }
        assert not unpriced, (
            "these jobs run on a runner whose billing multiplier is not "
            f"declared: {unpriced} - macOS bills at 10x, so an assumed 1x is a "
            "projection that cannot be trusted"
        )


class TestTheSuiteRunsOnce:
    """The full suite is one leg, on the floor, and it is not a matrix."""

    def test_exactly_one_job_runs_the_full_suite(self) -> None:
        assert _job_with_the_suite() == "test", (
            "the full suite moved out of the `test` job; the artifact and "
            "documentation steps publish from it and are ordered after it"
        )

    def test_the_suite_leg_runs_on_one_interpreter(self) -> None:
        block = _executed(job("test"))
        versions = re.findall(r'python-version:\s*"?(\d+\.\d+)"?', block)

        assert len(versions) == 1, (
            "the suite leg installs more than one interpreter, which means it "
            f"is a matrix again: {versions} - price each leg in "
            "MEASURED_BILLABLE before widening it"
        )

    def test_the_suite_leg_installs_the_floor(self) -> None:
        block = _executed(job("test"))
        versions = re.findall(r'python-version:\s*"?(\d+\.\d+)"?', block)
        expected = f"{EXPECTED_FLOOR[0]}.{EXPECTED_FLOOR[1]}"

        assert versions == [expected], (
            "the full suite must run on the floor `requires-python` declares "
            f"({expected}); it installs {versions}. The floor is the only leg "
            "that executes the dependency graph uv.lock resolves below 3.12"
        )
        assert expected in job("test"), (
            f"the job's name no longer states its interpreter ({expected}), so "
            "the run list cannot be read without the YAML"
        )

    def test_the_suite_leg_reads_no_matrix(self) -> None:
        assert "matrix." not in _executed(job("test")), (
            "the suite leg reads a matrix again; one leg publishes, and "
            "tests/test_cli_schema_conformance.py asserts the publishing steps "
            "carry no condition"
        )

    def test_the_suite_step_is_still_the_suite(self) -> None:
        """Non-vacuity: the slices above would pass on an empty job."""
        block = job("test")

        assert SUITE_STEP in block, f"the job has no {SUITE_STEP!r} step"
        assert "uv run python -m pytest" in _executed(block)


class TestTheBudgetHolds:
    """The projection is under budget, and the budget can reject a second leg."""

    def test_the_projection_is_under_budget(self) -> None:
        total = sum(MEASURED_BILLABLE.values())

        assert total <= BILLABLE_BUDGET, (
            f"one push projects {total:.1f} billable minutes against a budget "
            f"of {BILLABLE_BUDGET:.0f}: {MEASURED_BILLABLE}"
        )

    def test_the_budget_keeps_headroom(self) -> None:
        """A ceiling that leaves nothing is a measurement, not a budget."""
        total = sum(MEASURED_BILLABLE.values())

        assert BILLABLE_BUDGET - total >= 20.0, (
            f"the projection is {total:.1f} of {BILLABLE_BUDGET:.0f}, leaving "
            f"less than 20 minutes - ordinary growth would red this lock and "
            "invite raising the budget instead of pricing the change"
        )

    def test_a_second_full_leg_would_exceed_the_budget(self) -> None:
        """The shape this lock exists to reject must actually be rejected."""
        doubled = {**MEASURED_BILLABLE, "test": 2 * MEASURED_BILLABLE["test"]}

        assert sum(doubled.values()) > BILLABLE_BUDGET, (
            "a second full-suite leg projects "
            f"{sum(doubled.values()):.1f} minutes and would pass the budget - "
            "the arithmetic cannot catch the change R-17 removed, so this lock "
            "proves nothing"
        )
