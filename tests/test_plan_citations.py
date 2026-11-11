"""Lock the ``path:line`` citations in the current plan set.

A plan is the instruction a later session executes. It says the defect is at
``mood_analyzer/core/file_processor.py:147`` and the executor opens that file.
When the citation has drifted — the module moved package, the path was
abbreviated to an ambiguous ``core/processor.py``, or the line number no longer
exists — the plan confidently points at nothing, and the mistake surfaces as a
wrong fix rather than as a red test.

This lock reads every ``PLAN_*.md`` at the repository root and requires each
``path:line`` citation in a **current** plan to resolve: the file exists, the
path is repo-root-relative (a bare ``app.py`` is ambiguous in a tree holding
several), and the line number is inside the file.

Why only current plans
----------------------
The ``PLAN_*.md`` records are history. A citation in the 2.4.1 plan naming
``master_driver/utils/platform_utils.py:29`` was correct for the tree that plan
shipped against and is wrong today because a later release moved the module;
rewriting the record would destroy the evidence of what was decided and why. So
the lock follows the windowed shape of ``tests/test_release_notes.py``: it
starts at a declared date and locks every plan written from then on — including
plans that do not exist yet, because the date is read from the filename rather
than from a list someone has to remember to extend. A new plan therefore cannot
escape the scan by being newer than this constant.

The date is parsed from ``PLAN_<YYYY-MM-DD>_<slug>.md``. A record whose name
carries no date (``PLAN_audit_remediation.md``) is out of the window by
construction, and the locked set is asserted non-empty so a rename cannot turn
the scan vacuous.

Changed in 2.7.0: added, so a plan citation cannot rot silently.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Plans dated on or after this are locked. Move this forward only when the
#: older plans are accepted as history — never to silence a current plan.
LOCKED_FROM = date(2026, 11, 11)

#: The citation extensions worth resolving. A plan that cites a real file is
#: naming one of these; anything else (a directory, a flag) carries no line.
CITATION_EXTENSIONS: tuple[str, ...] = (
    "py",
    "pyw",
    "toml",
    "json",
    "jsonc",
    "yml",
    "yaml",
    "cfg",
    "ini",
    "txt",
    "md",
)

#: A ``path:line`` citation inside single backticks, e.g.
#: ``audio_suite_shared/constants.py:35``. A range (``:123-456``) is checked
#: from its first line, which is the anchor a reader jumps to.
_CITATION = re.compile(
    r"`([A-Za-z0-9_][A-Za-z0-9_./\\-]*\."
    r"(?:" + "|".join(CITATION_EXTENSIONS) + r")"
    r"):(\d+)`"
)

_PLAN_DATE = re.compile(r"^PLAN_(\d{4}-\d{2}-\d{2})_")

#: The current plan set carries dozens of citations; a scan that finds fewer
#: has a broken pattern, not a tidy corpus.
MIN_CITATIONS = 10


def plan_date(plan: Path) -> date | None:
    """Return the date in a plan's filename, or ``None`` when it carries none.

    Args:
        plan: A ``PLAN_*.md`` path.

    Returns:
        The parsed date, or ``None`` when the name is undated or the date is
        not a real calendar date.
    """
    match = _PLAN_DATE.match(plan.name)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def locked_plans(root: Path | None = None) -> tuple[Path, ...]:
    """Return the plan records this lock applies to, oldest first.

    Args:
        root: Repository root; defaults to this checkout.

    Returns:
        Every ``PLAN_*.md`` whose filename date is on or after
        :data:`LOCKED_FROM`.
    """
    base = REPO_ROOT if root is None else root
    dated = ((plan, plan_date(plan)) for plan in base.glob("PLAN_*.md"))
    return tuple(
        sorted(
            plan
            for plan, parsed in dated
            if parsed is not None and parsed >= LOCKED_FROM
        )
    )


def citations(text: str) -> tuple[tuple[str, int], ...]:
    """Return every ``path:line`` citation in *text*, without duplicates.

    Args:
        text: A plan document's contents.

    Returns:
        ``(cited_path, line_number)`` pairs in document order.
    """
    found: list[tuple[str, int]] = []
    for cited, line in _CITATION.findall(text):
        pair = (cited, int(line))
        if pair not in found:
            found.append(pair)
    return tuple(found)


def violation(cited: str, line_no: int, root: Path | None = None) -> str | None:
    """Explain why *cited*:*line_no* does not resolve, or ``None`` when it does.

    Args:
        cited: The path exactly as the plan wrote it.
        line_no: The cited line number.
        root: Repository root; defaults to this checkout.

    Returns:
        A human-readable reason, or ``None`` when the citation is sound.
    """
    base = REPO_ROOT if root is None else root
    normalized = cited.replace("\\", "/")
    if "/" not in normalized:
        return f"`{cited}:{line_no}` is not repo-root-relative; name the package"

    resolved = (base / normalized).resolve()
    if not resolved.is_relative_to(base.resolve()):
        return f"`{cited}:{line_no}` resolves outside the repository"
    if not resolved.is_file():
        return f"`{cited}:{line_no}` names no file (moved or renamed?)"

    try:
        text = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"`{cited}:{line_no}` cannot be read: {exc}"

    total = len(text.splitlines())
    if not 1 <= line_no <= total:
        return f"`{cited}:{line_no}` is outside the file ({total} lines)"
    return None


class TestTheLockedPlanSet:
    """The window itself, so a rename or a bad date cannot empty the scan."""

    def test_at_least_one_plan_is_locked(self) -> None:
        plans = locked_plans()
        assert plans, (
            f"no PLAN_*.md is dated on or after {LOCKED_FROM}; the citation lock "
            "would pass vacuously. Check the filename convention."
        )

    def test_the_current_plan_is_in_the_locked_set(self) -> None:
        names = {plan.name for plan in locked_plans()}
        assert "PLAN_2026-11-11_3.2.0_recursive_scanning.md" in names


class TestCurrentPlansResolveTheirCitations:
    """Every citation in a current plan points at real code."""

    def test_every_citation_resolves(self) -> None:
        plans = locked_plans()
        assert plans, "the locked plan set is empty"

        problems: list[str] = []
        seen = 0
        for plan in plans:
            text = plan.read_text(encoding="utf-8")
            for cited, line_no in citations(text):
                seen += 1
                reason = violation(cited, line_no)
                if reason is not None:
                    problems.append(f"{plan.name}: {reason}")

        assert seen >= MIN_CITATIONS, (
            f"only {seen} citations found across {len(plans)} locked plan(s); "
            "the citation pattern has stopped matching"
        )
        assert not problems, (
            "plan citations no longer resolve — a reader following one would "
            "land on the wrong code:\n  " + "\n  ".join(problems)
        )


class TestTheCheckerCanFail:
    """A lock that cannot fail is worse than none: prove each rule trips."""

    @pytest.mark.parametrize(
        ("cited", "line_no", "expected"),
        [
            ("audio_suite_shared/constants.py", 1, None),
            ("audio_suite_shared/no_such_module.py", 1, "names no file"),
            ("audio_suite_shared/constants.py", 999_999, "is outside the file"),
            ("constants.py", 1, "is not repo-root-relative"),
            ("../outside_the_repo.py", 1, "resolves outside the repository"),
        ],
    )
    def test_each_rule_trips(
        self, cited: str, line_no: int, expected: str | None
    ) -> None:
        reason = violation(cited, line_no)
        if expected is None:
            assert reason is None, reason
        else:
            assert reason is not None, f"{cited}:{line_no} resolved but should not"
            assert expected in reason

    def test_the_pattern_finds_a_citation(self) -> None:
        found = citations("see `audio_suite_shared/constants.py:35` for the value")
        assert found == (("audio_suite_shared/constants.py", 35),)
