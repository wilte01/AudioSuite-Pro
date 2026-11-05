"""Tests for ``utilities/coverage_table.py`` (WP-10 C-I9).

The script is an artefact generator, not a gate, so the tests are about the two
things a published table must get right: the grouping (a package's files add up
under the package, in an order that puts the cold code first) and the refusal
(a payload that cannot produce a table must exit non-zero rather than print an
empty one that reads like a healthy report).

The last class holds the CI wiring to those claims: the JSON report is written
by the suite step, the table is rendered from it, and the table is uploaded. A
utility nobody runs in CI is a utility that rots.

Changed in 2.4.3: initial version (WP-10 C-I9).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.ci_workflow import job  # noqa: E402
from utilities import coverage_table as table  # noqa: E402


def _payload(tmp_path: Path, files: dict[str, tuple[int, int]]) -> Path:
    """Write a coverage.py-shaped payload; each value is (statements, covered)."""
    data = {
        "meta": {"version": "7.0.0"},
        "files": {
            name: {
                "executed_lines": [],
                "missing_lines": [],
                "summary": {
                    "covered_lines": covered,
                    "num_statements": statements,
                    "percent_covered": 0.0,
                },
            }
            for name, (statements, covered) in files.items()
        },
        "totals": {"num_statements": 0, "covered_lines": 0},
    }
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestGrouping:
    """Files add up under their top-level package."""

    def test_a_packages_files_add_up_under_the_package(self, tmp_path: Path) -> None:
        payload = _payload(
            tmp_path,
            {
                "pkg_a/mod.py": (10, 5),
                "pkg_a/sub/deep.py": (10, 5),
                "pkg_b/mod.py": (10, 10),
            },
        )
        packages = table.summarise(
            json.loads(payload.read_text(encoding="utf-8")), payload
        )

        by_name = {package.name: package for package in packages}
        assert set(by_name) == {"pkg_a", "pkg_b"}
        assert by_name["pkg_a"].statements == 20
        assert by_name["pkg_a"].covered == 10
        assert by_name["pkg_a"].percent == pytest.approx(50.0)

    def test_a_root_module_gets_its_own_group(self) -> None:
        assert table.package_of("tool.py") == table.ROOT_GROUP

    def test_a_windows_separator_is_understood(self) -> None:
        assert table.package_of("pkg_a\\mod.py") == "pkg_a"
        assert table.package_of("./pkg_a/mod.py") == "pkg_a"

    def test_an_empty_payload_cannot_make_a_table(self, tmp_path: Path) -> None:
        path = tmp_path / "coverage.json"
        path.write_text(json.dumps({"files": {}}), encoding="utf-8")

        assert table.main(["--payload", str(path)]) == table.EXIT_UNUSABLE

    def test_a_summary_without_integers_cannot_make_a_table(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "coverage.json"
        path.write_text(
            json.dumps(
                {"files": {"pkg/mod.py": {"summary": {"num_statements": "10"}}}}
            ),
            encoding="utf-8",
        )

        assert table.main(["--payload", str(path)]) == table.EXIT_UNUSABLE

    def test_a_missing_payload_cannot_make_a_table(self, tmp_path: Path) -> None:
        assert (
            table.main(["--payload", str(tmp_path / "absent.json")])
            == table.EXIT_UNUSABLE
        )

    def test_a_non_json_payload_cannot_make_a_table(self, tmp_path: Path) -> None:
        path = tmp_path / "coverage.json"
        path.write_text("not json", encoding="utf-8")

        assert table.main(["--payload", str(path)]) == table.EXIT_UNUSABLE


class TestTheTable:
    """The rendered table is Markdown, cold code first, with one total row."""

    def _packages(self) -> list[table.PackageCoverage]:
        return [
            table.PackageCoverage(name="cold", statements=100, covered=10),
            table.PackageCoverage(name="warm", statements=100, covered=60),
            table.PackageCoverage(name="hot", statements=100, covered=95),
        ]

    def test_the_total_row_sums_the_groups(self) -> None:
        rendered = table.render_table(self._packages())

        assert "| **Total** | **300** | **165** | **55.0%** |" in rendered

    def test_one_row_per_package_plus_the_total(self) -> None:
        rendered = table.render_table(self._packages())
        rows = [line for line in rendered.splitlines() if line.startswith("| `")]

        assert len(rows) == 3, rows

    def test_percentages_carry_one_decimal(self) -> None:
        rendered = table.render_table(self._packages())

        assert "| `cold` | 100 | 10 | 10.0% |" in rendered

    def test_the_coldest_group_is_rendered_first(self, tmp_path: Path) -> None:
        payload = _payload(
            tmp_path,
            {"hot/mod.py": (10, 10), "cold/mod.py": (10, 1), "warm/mod.py": (10, 5)},
        )
        packages = table.summarise(
            json.loads(payload.read_text(encoding="utf-8")), payload
        )

        assert [package.name for package in packages] == ["cold", "warm", "hot"]


class TestTheCommand:
    """The command writes a file when asked and prints otherwise."""

    def test_writes_the_table_to_an_output_file(self, tmp_path: Path) -> None:
        payload = _payload(tmp_path, {"pkg/mod.py": (10, 5)})
        output = tmp_path / "coverage-table.md"

        assert (
            table.main(["--payload", str(payload), "--output", str(output)])
            == table.EXIT_OK
        )
        written = output.read_text(encoding="utf-8")
        assert written.startswith("## Per-package coverage")
        assert "| `pkg` |" in written

    def test_prints_the_table_when_no_output_is_given(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        payload = _payload(tmp_path, {"pkg/mod.py": (10, 5)})

        assert table.main(["--payload", str(payload)]) == table.EXIT_OK
        assert "| `pkg` | 10 | 5 | 50.0% |" in capsys.readouterr().out


class TestCiPublishesIt:
    """The suite writes the payload, the job renders it, the run keeps it."""

    def test_the_suite_step_writes_the_json_report(self) -> None:
        assert "--cov-report=json:coverage.json" in job("test"), (
            "the suite step no longer writes coverage.json, so the table step "
            "below has nothing to render"
        )

    def test_the_job_renders_the_table_from_that_payload(self) -> None:
        block = job("test")

        assert "utilities/coverage_table.py" in block
        assert "--payload coverage.json" in block
        assert "--output coverage-table.md" in block

    def test_the_table_is_uploaded_and_an_empty_one_fails_the_job(self) -> None:
        block = job("test")

        assert "name: coverage-table" in block
        assert "path: coverage-table.md" in block
        assert block.count("if-no-files-found: error") >= 3, (
            "every artifact upload must fail on an empty path; the table is "
            "worthless if a green job can publish nothing"
        )
