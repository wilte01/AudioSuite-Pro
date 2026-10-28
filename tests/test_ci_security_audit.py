"""Lock the dependency-audit CI step and the fix it found (PLAN D96).

The security job is the only place the *shipped* graph is audited: it exports
``uv.lock`` and runs ``pip-audit`` against the exported requirements, so a
published advisory cannot reach a release unnoticed.  Four things can quietly
undo that:

* the step is deleted (or renamed out of the job) and nothing notices;
* the audit is pointed at ``.venv``, whose environment-only packages (``pip``)
  are not the project's to fix and drown the findings that are;
* the step is made ignorable again, or its verdict is taken from pip-audit's
  exit status instead of the checker's - pip-audit exits 1 for any finding, so
  that would fail every finding regardless of the allowlist;
* the weekly workflow is deleted, and an advisory published between commits (or
  an entry passing its expiry date on a week nobody commits) waits for a push;
* ``--ignore-vuln`` reappears, creating a second place an advisory can be
  silenced;
* the ``urllib3`` floor it exists for slides back below 2.8.0.

Each claim is asserted on the committed files, with every slice checked
non-empty first: a text extraction that finds nothing must fail loudly rather
than pass vacuously.

Changed in 1.4.1: initial version (PLAN D96).
Changed in 2.1.6: the import block is re-sorted against the corrected ruff
target py311 — ``tomllib`` is 3.11 standard library
(R-15, PLAN_audit_2026-10-24_deferred_p2p3.md).
Changed in 2.1.6: the probation ended (R-11). The step is blocking, its verdict
is ``utilities/check_dependency_audit.py``, the weekly workflow exists, and the
allowlist is the only suppression - so ``test_the_step_is_on_probation`` is
replaced by the contract that succeeded it, which is the deliberate edit that
assertion was written to force.
"""

from __future__ import annotations

import re
import tomllib
from datetime import date
from pathlib import Path

import pytest

from tests.ci_workflow import job, step

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"
WEEKLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependency-audit.yml"
ALLOWLIST = REPO_ROOT / "security" / "pip_audit_allowlist.toml"
CHECKER = REPO_ROOT / "utilities" / "check_dependency_audit.py"

#: Keys an allowlist entry must carry; mirrors the checker's own tuple.
ENTRY_KEYS = ("id", "package", "reason", "expires")

#: The step name the workflow uses; the parser keys on it, so a rename is a
#: deliberate edit here too.
AUDIT_STEP = "Dependency audit (exported lock)"

#: The advisory fix the audit produced; the floor and the lock must agree.
URLLIB3_FLOOR = (2, 8, 0)


def _executed(block: str) -> str:
    """Return *block* without its comment lines.

    Every job and step here explains its decisions in comments, and those
    comments quote the command they replaced - so a raw-text match would be
    satisfied by the explanation rather than by the wiring (D14).
    """
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def _version(text: str) -> tuple[int, ...]:
    """Parse a dotted package version into a comparable tuple."""
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    assert match is not None, f"unparsable version {text!r}"
    return tuple(int(part) for part in match.group(1).split("."))


@pytest.fixture(scope="module")
def audit_step() -> str:
    """The workflow's dependency-audit step, sliced out of the security job."""
    return step(job("security"), AUDIT_STEP)


class TestTheWorkflowRunsTheAudit:
    """The step exists, audits the exported lock, and is on probation."""

    def test_the_security_job_installs_uv(self) -> None:
        security = job("security")

        assert "pip install uv" in security, "the audit needs uv to export the lock"

    def test_the_step_exports_the_locked_graph(self, audit_step: str) -> None:
        assert "uv export --frozen --all-extras --no-emit-project" in audit_step
        assert "--format requirements-txt" in audit_step
        assert "--no-hashes" in audit_step
        assert "-o requirements-audit.txt" in audit_step

    def test_the_step_audits_that_export_without_resolving(
        self, audit_step: str
    ) -> None:
        executed = _executed(audit_step)

        assert "uvx pip-audit -r requirements-audit.txt --no-deps" in executed
        assert "-f json" in executed, "the verdict needs a structured payload"

    def test_the_step_never_audits_the_virtualenv(self, audit_step: str) -> None:
        """.venv carries environment-only packages that do not ship.

        The step's own comment explains why, so only executed lines count: a
        comment cannot point the audit at a directory.
        """
        executed = "\n".join(
            line for line in audit_step.splitlines() if not line.strip().startswith("#")
        )

        assert ".venv" not in executed

    def test_the_step_cannot_be_ignored(self, audit_step: str) -> None:
        """The probation ended; a finding now fails the job (R-11)."""
        executed = _executed(audit_step)

        assert "continue-on-error" not in executed
        assert "probation" not in executed

    def test_the_step_asks_the_checker_for_the_verdict(self, audit_step: str) -> None:
        """pip-audit's exit status cannot express a dated acceptance."""
        executed = _executed(audit_step)

        assert "utilities/check_dependency_audit.py" in executed
        assert "--payload pip-audit.json" in executed

    def test_a_pip_audit_tool_error_is_not_a_verdict(self, audit_step: str) -> None:
        """Exit >= 2 is the tool failing, not a finding to weigh."""
        executed = _executed(audit_step)

        assert 'if [ "$audit" -ge 2 ]' in executed
        assert "pip-audit could not run" in executed

    def test_no_workflow_ignores_a_finding(self) -> None:
        """The allowlist is the only suppression, in both workflows."""
        for path in (WEEKLY_WORKFLOW, REPO_ROOT / ".github" / "workflows" / "ci.yml"):
            text = path.read_text(encoding="utf-8")

            assert "--ignore-vuln" not in _executed(text), path


class TestTheWeeklyWorkflow:
    """An advisory published between commits surfaces without one."""

    def test_the_workflow_exists_with_a_schedule_and_dispatch(self) -> None:
        assert WEEKLY_WORKFLOW.is_file(), f"{WEEKLY_WORKFLOW} is missing"
        text = WEEKLY_WORKFLOW.read_text(encoding="utf-8")

        assert "schedule:" in text
        assert "cron:" in text
        assert "workflow_dispatch:" in text

    def test_it_runs_the_same_export_and_checker(self) -> None:
        """The two files must ask the same question of the same graph."""
        block = _executed(job("audit", WEEKLY_WORKFLOW))

        assert "uv export --frozen --all-extras --no-emit-project" in block
        assert "uvx pip-audit -r requirements-audit.txt --no-deps" in block
        assert "-f json" in block
        assert "utilities/check_dependency_audit.py" in block

    def test_it_cannot_be_ignored(self) -> None:
        block = step(job("audit", WEEKLY_WORKFLOW), AUDIT_STEP)

        assert "continue-on-error" not in _executed(block)


class TestTheAllowlist:
    """The one place an acceptance can live, with its schema on the page."""

    def test_the_allowlist_exists_and_parses(self) -> None:
        assert ALLOWLIST.is_file(), f"{ALLOWLIST} is missing"
        data = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))

        assert isinstance(data.get("advisory", []), list)

    def test_every_entry_carries_its_reason_and_expiry(self) -> None:
        data = tomllib.loads(ALLOWLIST.read_text(encoding="utf-8"))
        for entry in data.get("advisory", []):
            for key in ENTRY_KEYS:
                assert isinstance(entry.get(key), str) and entry[key].strip(), (
                    f"allowlist entry {entry.get('id', '?')} needs a non-empty {key!r}"
                )
            date.fromisoformat(entry["expires"])

    def test_the_schema_is_documented_in_the_file(self) -> None:
        """The empty file still has to teach the next person the schema."""
        text = ALLOWLIST.read_text(encoding="utf-8")

        for key in ENTRY_KEYS:
            assert f"{key} =" in text, f"the allowlist header does not document {key!r}"
        assert "[[advisory]]" in text

    def test_the_checker_exists_and_is_stdlib_only(self) -> None:
        source = CHECKER.read_text(encoding="utf-8")

        assert CHECKER.is_file()
        assert "tomllib" in source, "the allowlist is TOML; 3.11 ships the parser"
        # The filename ``pip_audit_allowlist.toml`` contains the token, so the
        # assertion names an import rather than the bare name.
        assert "import pip_audit" not in source, (
            "the checker must read pip-audit's payload, not import it"
        )
        assert "from pip_audit" not in source


class TestTheFixItFound:
    """The advisory fix cannot slide back while the step cannot fail the build."""

    def test_the_dependency_floor_is_two_eight(self) -> None:
        project = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]
        requirement = next(
            (item for item in project["dependencies"] if item.startswith("urllib3")),
            None,
        )
        assert requirement is not None, "pyproject.toml lost its urllib3 dependency"
        assert requirement.startswith("urllib3>="), requirement
        assert _version(requirement.removeprefix("urllib3>=")) >= URLLIB3_FLOOR

    def test_the_lock_resolves_the_fixed_version(self) -> None:
        lock = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
        locked = [entry for entry in lock["package"] if entry["name"] == "urllib3"]
        assert locked, "uv.lock has no urllib3 entry"
        assert max(_version(entry["version"]) for entry in locked) >= URLLIB3_FLOOR

    def test_pip_audit_is_a_dev_dependency(self) -> None:
        extras = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"][
            "optional-dependencies"
        ]
        assert any(
            item.startswith("pip-audit>=")
            and _version(item.split(">=", 1)[1]) >= (2, 10)
            for item in extras["dev"]
        ), f"the dev extra does not require pip-audit>=2.10: {extras['dev']}"


class TestTheDocumentation:
    """Contributors can run the scan, and it stays out of the gate block."""

    def test_contributing_documents_the_scan(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")
        heading = "## Dependency security scanning"

        assert heading in text
        # After the Phase Gate heading means outside its pwsh block, which
        # tests/test_readme.py parses into the README's mandatory commands.
        assert text.index(heading) > text.index("## The mandatory Phase Gate")

    def test_the_scan_is_not_part_of_the_mandatory_gate_block(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")
        gate_start = text.index("## The mandatory Phase Gate")
        block_start = text.index("```pwsh", gate_start)
        block_end = text.index("```", block_start + len("```pwsh"))
        block = text[block_start:block_end]

        assert "pip-audit" not in block
        assert "requirements-audit" not in block

    def test_contributing_names_the_local_commands(self) -> None:
        """A contributor can reproduce the verdict, not just the scan."""
        text = CONTRIBUTING.read_text(encoding="utf-8")

        assert "uv export --frozen --all-extras --no-emit-project" in text
        assert "uvx pip-audit -r requirements-audit.txt --no-deps -f json" in text
        assert "utilities/check_dependency_audit.py" in text

    def test_contributing_states_the_blocking_contract(self) -> None:
        text = CONTRIBUTING.read_text(encoding="utf-8")

        assert "security/pip_audit_allowlist.toml" in text
        assert "dependency-audit.yml" in text
        assert "on probation" not in text, (
            "the probation ended in 2.1.6; the paragraph that described it must go"
        )
