"""Lock the dependency-audit CI step and the fix it found (PLAN D96).

The security job is the only place the *shipped* graph is audited: it exports
``uv.lock`` and runs ``pip-audit`` against the exported requirements, so a
published advisory cannot reach a release unnoticed.  Four things can quietly
undo that:

* the step is deleted (or renamed out of the job) and nothing notices;
* the audit is pointed at ``.venv``, whose environment-only packages (``pip``)
  are not the project's to fix and drown the findings that are;
* the probation flag is dropped in a way that makes the job fail for a reason
  nobody planned for, or kept forever without a recorded decision;
* the ``urllib3`` floor it exists for slides back below 2.8.0 while the audit
  step is on probation and therefore cannot fail the build.

Each claim is asserted on the committed files, with every slice checked
non-empty first: a text extraction that finds nothing must fail loudly rather
than pass vacuously.

Changed in 1.4.1: initial version (PLAN D96).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"
UV_LOCK = REPO_ROOT / "uv.lock"

#: The step name the workflow uses; the parser keys on it, so a rename is a
#: deliberate edit here too.
AUDIT_STEP = "Dependency audit (exported lock)"

#: The advisory fix the audit produced; the floor and the lock must agree.
URLLIB3_FLOOR = (2, 8, 0)


def _workflow() -> str:
    """Return the workflow text."""
    return WORKFLOW.read_text(encoding="utf-8")


def _job(text: str, name: str) -> str:
    """Return the YAML block for job *name* (a 2-space-indented key).

    Raises:
        AssertionError: if the job is missing or the slice is empty - a lock
            reading ``""`` would pass every assertion below.
    """
    match = re.search(rf"^  {re.escape(name)}:\s*$", text, re.MULTILINE)
    assert match is not None, f"ci.yml has no {name!r} job"
    start = match.start()
    following = re.search(r"^  [A-Za-z0-9_-]+:\s*$", text[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(text)
    block = text[start:end]
    assert block.strip(), f"ci.yml's {name!r} job parsed as empty"
    return block


def _step(job: str, name: str) -> str:
    """Return the YAML block for the step called *name* inside *job*."""
    match = re.search(rf"^      - name: {re.escape(name)}\s*$", job, re.MULTILINE)
    assert match is not None, f"the job has no step named {name!r}"
    start = match.start()
    following = re.search(r"^      - ", job[match.end() :], re.MULTILINE)
    end = match.end() + following.start() if following else len(job)
    block = job[start:end]
    assert block.strip(), f"step {name!r} parsed as empty"
    return block


def _version(text: str) -> tuple[int, ...]:
    """Parse a dotted package version into a comparable tuple."""
    match = re.match(r"(\d+(?:\.\d+)*)", text)
    assert match is not None, f"unparsable version {text!r}"
    return tuple(int(part) for part in match.group(1).split("."))


@pytest.fixture(scope="module")
def audit_step() -> str:
    """The workflow's dependency-audit step, sliced out of the security job."""
    return _step(_job(_workflow(), "security"), AUDIT_STEP)


class TestTheWorkflowRunsTheAudit:
    """The step exists, audits the exported lock, and is on probation."""

    def test_the_security_job_installs_uv(self) -> None:
        job = _job(_workflow(), "security")

        assert "pip install uv" in job, "the audit needs uv to export the lock"

    def test_the_step_exports_the_locked_graph(self, audit_step: str) -> None:
        assert "uv export --frozen --all-extras --no-emit-project" in audit_step
        assert "--format requirements-txt" in audit_step
        assert "--no-hashes" in audit_step
        assert "-o requirements-audit.txt" in audit_step

    def test_the_step_audits_that_export_without_resolving(
        self, audit_step: str
    ) -> None:
        assert "uvx pip-audit -r requirements-audit.txt --no-deps --desc" in audit_step

    def test_the_step_never_audits_the_virtualenv(self, audit_step: str) -> None:
        """.venv carries environment-only packages that do not ship.

        The step's own comment explains why, so only executed lines count: a
        comment cannot point the audit at a directory.
        """
        executed = "\n".join(
            line for line in audit_step.splitlines() if not line.strip().startswith("#")
        )

        assert ".venv" not in executed

    def test_the_step_is_on_probation(self, audit_step: str) -> None:
        """Two sprints of reporting before the step can fail the job (D2)."""
        assert "continue-on-error: true" in audit_step
        assert "probation" in audit_step


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
        text = CONTRIBUTING.read_text(encoding="utf-8")

        assert "uv export --frozen --all-extras --no-emit-project" in text
        assert "uvx pip-audit -r requirements-audit.txt --no-deps --desc" in text
