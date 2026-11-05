"""Tests for ``utilities/changed_in_budget.py`` (WP-10 C-I2).

The script is a gate, so the tests are about the verdict rather than the printed
lines: a version over its recorded ceiling fails, a version carrying notes with
no recorded ceiling fails, a baseline nobody can read fails as unusable, and
``--record`` writes the counts exactly so that recording a ceiling at today's
number still refuses tomorrow's growth.

The last two classes are the ones that keep the gate honest: the committed
baseline must match the real tree (proved by ``--check`` passing here), and the
comparison must be able to reject the shape it exists to catch - a ceiling one
note below the tree.

Changed in 2.4.3: initial version (WP-10 C-I2).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.ci_workflow import REPO_ROOT, job  # noqa: E402
from utilities import changed_in_budget as budget  # noqa: E402

BASE = (
    Path(__file__).resolve().parents[2] / "tests" / "data" / "changed_in_baseline.json"
)

NOTE = "# Changed in {version}: synthetic note"


def _tree(tmp_path: Path, files: dict[str, list[str]]) -> Path:
    """Write a synthetic tree; each file's list is the versions it notes."""
    root = tmp_path / "tree"
    for name, versions in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        body = ["value = 1"] + [NOTE.format(version=version) for version in versions]
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
    root.mkdir(exist_ok=True)
    return root


def _baseline(tmp_path: Path, versions: dict[str, int]) -> Path:
    """Write a baseline file shaped like the committed one."""
    path = tmp_path / "baseline.json"
    path.write_text(
        json.dumps({"versions": versions, "total": sum(versions.values())}),
        encoding="utf-8",
    )
    return path


class TestCounting:
    """The scan finds note lines, and only in the tree it should read."""

    def test_counts_notes_per_version_across_files(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            {
                "pkg/mod.py": ["2.4.3", "2.4.3"],
                "pkg/sub/deep.py": ["2.4.3"],
                "other/mod.py": ["2.4.2"],
            },
        )

        assert budget.note_counts(root) == {"2.4.3": 3, "2.4.2": 1}

    def test_a_line_without_the_marker_is_not_a_note(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": []})
        (root / "pkg" / "other.py").write_text(
            "note = 'this line was changed in the last round'\n", encoding="utf-8"
        )

        assert budget.note_counts(root) == {}

    def test_the_documentation_tree_is_not_counted(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3"]})
        doc = root / "documentation" / "page.py"
        doc.parent.mkdir(parents=True)
        doc.write_text(NOTE.format(version="9.9.9") + "\n", encoding="utf-8")

        assert "9.9.9" not in budget.note_counts(root)


class TestTheVerdict:
    """Over budget fails, at budget passes, and an unrecorded version fails."""

    def test_a_tree_at_its_ceiling_passes(self) -> None:
        assert budget.failures({"2.4.3": 5}, {"2.4.3": 5}) == []

    def test_a_version_over_its_ceiling_fails(self) -> None:
        problems = budget.failures({"2.4.3": 6}, {"2.4.3": 5})

        assert problems and "grew from 5 to 6" in problems[0]

    def test_a_new_version_with_notes_and_no_ceiling_fails(self) -> None:
        problems = budget.failures({"2.4.3": 5, "2.5.0": 1}, {"2.4.3": 5})

        assert any("2.5.0 carries 1" in problem for problem in problems)

    def test_the_total_is_a_second_ceiling(self) -> None:
        problems = budget.failures({"2.4.3": 3, "2.4.2": 3}, {"2.4.3": 3, "2.4.2": 3})
        assert problems == []


class TestTheCommand:
    """The command's exit status is the verdict a CI step reads."""

    def test_check_passes_within_the_ceiling(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3"]})
        baseline = _baseline(tmp_path, {"2.4.3": 1})

        assert (
            budget.main(["--check", "--root", str(root), "--baseline", str(baseline)])
            == budget.EXIT_OK
        )

    def test_check_fails_over_the_ceiling(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3", "2.4.3"]})
        baseline = _baseline(tmp_path, {"2.4.3": 1})

        assert (
            budget.main(["--check", "--root", str(root), "--baseline", str(baseline)])
            == budget.EXIT_OVER
        )
        assert "[ERROR]" in capsys.readouterr().err

    def test_a_missing_baseline_is_unusable(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3"]})

        assert (
            budget.main(
                [
                    "--check",
                    "--root",
                    str(root),
                    "--baseline",
                    str(tmp_path / "no.json"),
                ]
            )
            == budget.EXIT_UNUSABLE
        )

    def test_a_baseline_without_versions_is_unusable(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3"]})
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"versions": {}}), encoding="utf-8")

        assert (
            budget.main(["--check", "--root", str(root), "--baseline", str(baseline)])
            == budget.EXIT_UNUSABLE
        )

    def test_record_writes_the_counts_exactly(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"pkg/mod.py": ["2.4.3", "2.4.3"]})
        baseline = tmp_path / "baseline.json"

        assert (
            budget.main(["--record", "--root", str(root), "--baseline", str(baseline)])
            == budget.EXIT_OK
        )
        recorded = json.loads(baseline.read_text(encoding="utf-8"))
        assert recorded["versions"] == {"2.4.3": 2}
        assert recorded["total"] == 2
        assert (
            budget.main(["--check", "--root", str(root), "--baseline", str(baseline)])
            == budget.EXIT_OK
        )


class TestTheCommittedBaselineIsCurrent:
    """The baseline in the tree matches the tree, so the gate is live."""

    def test_the_baseline_file_exists_and_is_shaped(self) -> None:
        assert BASE.is_file(), "tests/data/changed_in_baseline.json is missing"

        recorded = budget.load_baseline(BASE)

        assert recorded, "the baseline is empty"
        assert budget.DEFAULT_BASELINE == BASE

    def test_the_tree_is_within_the_baseline(self) -> None:
        measured = budget.note_counts(REPO_ROOT)
        recorded = budget.load_baseline(BASE)

        assert budget.failures(measured, recorded) == [], (
            "the note lines outgrew the recorded baseline; decide whether the "
            "new notes are wanted and run `python utilities/changed_in_budget.py "
            "--record`"
        )

    def test_the_comparison_can_reject_a_ceiling_one_note_low(self) -> None:
        """A ceiling recorded at today's count must still refuse growth."""
        measured = budget.note_counts(REPO_ROOT)
        recorded = budget.load_baseline(BASE)
        tightened = dict(recorded)
        version = sorted(recorded)[-1]
        tightened[version] = recorded[version] - 1

        assert budget.failures(measured, tightened), (
            "lowering a ceiling by one note did not fail, so the gate cannot "
            "detect growth at all"
        )


class TestTheWorkflowRunsIt:
    """The compile job is the cheap place for a stdlib-only check."""

    def test_the_compile_job_checks_the_budget(self) -> None:
        block = job("compile")

        assert "utilities/changed_in_budget.py" in block
        assert "--check" in block

    def test_the_baseline_file_is_the_one_the_script_names(self) -> None:
        assert "tests/data/changed_in_baseline.json" in job("compile")
        assert "python -X utf8 utilities/changed_in_budget.py" in job("compile")
