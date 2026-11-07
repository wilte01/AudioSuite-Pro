"""The BLE001 baseline cannot pass vacuously.

Changed in 2.4.1: added by WP-7 of PLAN_2026-11-03_2.4.1_stop_the_drift.md.

Changed in 2.5.0: the scan includes the ``*.pyw`` launchers and the one
production exemption (``*.pyw``/E402, the launch order) is named, so a new
production exemption still fails.

WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md`` (D-31) enables Ruff's
``BLE`` rules with a baseline rather than a blanket suppression. Three things
have to stay true for that baseline to mean anything:

* the rule is actually selected (a removed ``select`` entry would make every
  production site pass by not being checked at all);
* the BLE001 per-file exemption covers test trees and nothing else, so it
  cannot be widened to a production package without this failing; and
* every annotated site names the boundary it is, instead of a bare ``# noqa``.
"""

from __future__ import annotations

import fnmatch
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Directories that hold no first-party source.
_NOT_SOURCE = (".venv", ".git", "documentation", "packaging")


def _lint_config() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["tool"]["ruff"]["lint"]


def _source_files() -> list[Path]:
    """Every first-party ``.py``/``.pyw`` file outside a test tree."""
    found: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")) + sorted(REPO_ROOT.rglob("*.pyw")):
        parts = path.relative_to(REPO_ROOT).parts
        if any(part in _NOT_SOURCE for part in parts):
            continue
        if "tests" in parts:
            continue
        found.append(path)
    return sorted(found)


def _relative(path: Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


class TestRuffBaseline:
    """The rule is on, and its exemption is narrow."""

    def test_ble_is_selected(self) -> None:
        select = _lint_config()["select"]
        assert isinstance(select, list)
        assert "BLE" in select

    def test_ble_exemption_covers_test_trees_only(self) -> None:
        ignores = _lint_config()["per-file-ignores"]
        assert isinstance(ignores, dict)
        ble = {
            pattern: rules for pattern, rules in ignores.items() if "BLE001" in rules
        }
        assert set(ble) == {"tests/*", "*/tests/*"}
        assert all(rules == ["BLE001"] for rules in ble.values())

    def test_the_only_production_exemption_is_the_launchers_e402(self) -> None:
        """Every other exemption is test-only (Changed in 2.5.0)."""
        ignores = _lint_config()["per-file-ignores"]
        assert isinstance(ignores, dict)
        # The one relaxation that reaches production code, and its rule.
        assert ignores.get("*.pyw") == ["E402"]
        source = _source_files()
        # An empty scan would pass vacuously, so the set itself is asserted.
        assert len(source) > 100, f"only scanned {len(source)} source files"

        offenders: list[str] = []
        for path in source:
            relative = _relative(path)
            rules = {
                rule
                for pattern, ignored in ignores.items()
                if fnmatch.fnmatch(relative, pattern)
                for rule in ignored
            }
            if not rules:
                continue
            if rules == {"E402"} and relative.endswith(".pyw"):
                continue
            offenders.append(f"{relative}: {sorted(rules)}")
        assert offenders == []


class TestAnnotationsNameTheirBoundary:
    """A kept broad catch says why it is one."""

    def test_every_annotation_carries_a_reason(self) -> None:
        bare: list[str] = []
        annotated = 0
        for path in _source_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                if "noqa: BLE001" not in line:
                    continue
                annotated += 1
                if "noqa: BLE001 -" in line:
                    continue
                # A bare noqa is only allowed when the line above names the
                # boundary the catch is (the reason does not fit inline).
                previous = lines[index - 1].strip() if index else ""
                if not previous.startswith("# BLE001 boundary:"):
                    bare.append(f"{_relative(path)}:{index + 1}")

        assert annotated > 0, "no annotation was scanned - the check is vacuous"
        assert bare == []

    def test_boundary_notes_are_not_orphaned(self) -> None:
        """A boundary note must annotate an ``except`` on the next line."""
        orphans: list[str] = []
        for path in _source_files():
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines[:-1]):
                if not line.strip().startswith("# BLE001 boundary:"):
                    continue
                following = lines[index + 1].strip()
                if not following.startswith("except"):
                    orphans.append(f"{_relative(path)}:{index + 1}")
        assert orphans == []
