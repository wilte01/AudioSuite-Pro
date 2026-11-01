"""Lock the CI change classifier: only a documentation-only push skips the suite.

The floor leg is ~61 of a push's ~69 billable minutes, so a plan-or-guide commit
that paid it was spending the whole budget on prose (the 2.3.0 record commit
`d753c6e` cost 30 m 56 s). `.github/workflows/ci.yml` now classifies the change
set and gates the `test` job on the answer; these tests hold both halves:

* the rule itself, as a pure function over the changed paths - a Markdown file
  or anything under the one documentation tree is a document, an empty change
  set is not provably documentation, and everything else runs the suite;
* the workflow's use of it, so the gate cannot be dropped from the YAML (which
  would silently restore the cost) or widened to another job (which would skip
  the docs locks a guide commit most needs).

The gate checks are written as functions over a block and then fed a mutated
copy, so the lock is proved able to fail rather than assumed to be.

Changed in 2.3.1: initial version, with the `changes` job it locks.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from tests.ci_workflow import REPO_ROOT, job, job_names, workflow_text
from utilities.ci_changed_paths import classify, is_documentation, main

#: The module the workflow calls, and the condition the suite leg carries.
CLASSIFIER = "utilities/ci_changed_paths.py"
GATE = "needs.changes.outputs.suite == 'true'"

#: Paths that cannot change what the suite executes.
DOCUMENTS = (
    "PLAN_functional_backlog.md",
    "PLAN_audit_2026-10-24_deferred_p2p3.md",
    "CHANGELOG.md",
    "TECHNICAL_CHANGELOG.md",
    "AGENTS.md",
    "README.md",
    "documentation/docs/index.md",
    "documentation/docs/user/messages.md",
    "documentation/user_guides/individual_programs/restoration/guide.md",
    "documentation/user_guides/individual_programs/restoration/guide.docx",
)

#: Paths the suite reads, runs or installs, so a change to any of them may
#: change its verdict.
CODE = (
    "duplicate_finder/core/models.py",
    "restoration/tests/test_declipper.py",
    "audio_suite_shared/tool_plugin.py",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
    "tests/data/cli_payloads.json",
    "Pop_Click_Remover.pyw",
    "documentation/docs/conf.py",
)


def _executed(block: str) -> str:
    """Return *block*'s executed lines (a YAML comment runs nothing)."""
    return "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )


def _gate_problem(block: str) -> str | None:
    """Return why *block* fails to gate the suite on the classifier, if it does."""
    executed = _executed(block)
    if "needs: changes" not in executed:
        return "the suite leg no longer depends on the classifier"
    if GATE not in executed:
        return "the suite leg is no longer gated on the verdict"
    return None


class TestOnlyDocumentationSkipsTheSuite:
    """The rule, as the pure function the workflow calls."""

    @pytest.mark.parametrize("path", DOCUMENTS)
    def test_a_document_needs_no_suite(self, path: str) -> None:
        verdict = classify(["documentation/docs/index.md", path])

        assert not verdict.needs_suite, f"{path} would skip the suite"
        assert verdict.output_line() == "suite=false"

    @pytest.mark.parametrize("path", CODE)
    def test_anything_the_suite_executes_needs_the_suite(self, path: str) -> None:
        verdict = classify(["PLAN_functional_backlog.md", path])

        assert verdict.needs_suite, f"{path} was classified as documentation"
        assert verdict.output_line() == "suite=true"

    def test_a_python_file_inside_the_documentation_tree_is_code(self) -> None:
        """Sphinx's ``conf.py`` is executed when the site is built."""
        assert is_documentation("documentation/docs/conf.py") is False
        assert is_documentation("documentation/docs/index.md") is True

    def test_an_empty_change_set_needs_the_suite(self) -> None:
        """ "No paths" is evidence the diff failed, not that prose changed."""
        for paths in ([], ["", "   "]):
            verdict = classify(paths)

            assert verdict.needs_suite, f"{paths!r} skipped the suite"
            assert "nothing is proved" in verdict.reason

    def test_windows_separators_are_read(self) -> None:
        assert is_documentation("documentation\\docs\\index.md") is True

    def test_the_samples_are_not_vacuous(self) -> None:
        assert len(DOCUMENTS) >= 8 and len(CODE) >= 8
        assert all(not classify([path]).needs_suite for path in DOCUMENTS)
        assert all(classify([path]).needs_suite for path in CODE)


class TestTheCommandPublishesTheVerdict:
    """The runner reads a file, so the command must really write it."""

    @pytest.mark.parametrize(
        ("stdin_text", "expected"),
        [
            ("PLAN_functional_backlog.md\n", "suite=false\n"),
            ("pyproject.toml\n", "suite=true\n"),
        ],
    )
    def test_the_output_file_carries_the_line(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        stdin_text: str,
        expected: str,
    ) -> None:
        output = tmp_path / "github_output"
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_text))

        assert main(["--github-output", str(output)]) == 0
        assert output.read_text(encoding="utf-8") == expected


class TestTheWorkflowUsesTheClassifier:
    """The YAML half: the gate exists, and nothing else depends on the verdict."""

    def test_the_classification_job_exists(self) -> None:
        assert (REPO_ROOT / CLASSIFIER).is_file()
        block = _executed(job("changes"))

        assert "id: classify" in block
        assert "suite: ${{ steps.classify.outputs.suite }}" in block
        assert CLASSIFIER in block
        assert "--github-output" in block

    def test_the_job_diffs_the_pushed_range(self) -> None:
        block = _executed(job("changes"))

        assert "git diff --name-only" in block
        assert "fetch-depth: 0" in block, (
            "a shallow checkout cannot diff the pushed range, so every push "
            "would fall back to running the suite"
        )

    def test_the_suite_leg_is_gated(self) -> None:
        assert _gate_problem(job("test")) is None

    def test_no_other_job_is_gated_on_the_verdict(self) -> None:
        """Docs locks are what a guide commit most needs; it must still run."""
        gated = [
            name
            for name in job_names()
            if "needs.changes.outputs.suite" in _executed(job(name))
        ]

        assert gated == ["test"], (
            "the classifier gates more than the suite leg, so a documentation "
            f"commit skips the jobs it needs: {gated}"
        )

    def test_the_trigger_ignores_no_paths(self) -> None:
        """A ``paths-ignore`` would skip the workflow, docs locks included."""
        assert "paths-ignore" not in _executed(workflow_text())

    def test_every_unusable_case_runs_the_suite(self) -> None:
        """Fail-open: the guards, not just the classifier, must say so."""
        block = _executed(job("changes"))

        assert block.count('echo "suite=true"') >= 3, (
            "a guard that cannot classify no longer falls back to the suite: "
            "an unusable range, a failed diff and a crashed classifier must all "
            "answer 'run the suite'"
        )

    def test_the_gate_lock_can_fail(self) -> None:
        """A lock that cannot fail is worse than none."""
        ungated = _executed(job("test")).replace(GATE, "'true'")
        undependent = _executed(job("test")).replace("needs: changes", "needs: lint")

        assert _gate_problem(ungated) is not None
        assert _gate_problem(undependent) is not None
