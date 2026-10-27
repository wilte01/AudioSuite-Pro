"""Tests for ``audio_suite_shared.optional_deps``.

The install runs on the user's machine and into the interpreter that is running
the tool, so the properties worth locking down are: pip is never invoked when
the package already imports, a failed download is reported with its own output
rather than as a generic dialog, "pip succeeded" is not accepted as proof, and
the declared version floor cannot drift away from ``pyproject.toml``.

Changed in 2.1.0: initial version.
Changed in 2.1.6: the import block is re-sorted against the corrected ruff
target py311 — ``tomllib`` is 3.11 standard library
(R-15, PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import ast
import subprocess
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.optional_deps import (
    DEMUCS,
    RNNOISE,
    TOOL_REQUIREMENTS,
    InstallOutcome,
    ensure,
    import_failure,
    installed_version,
    meets_floor,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Constant name -> requirement, for reading the tools' own call sites.
_REQUIREMENTS = {"DEMUCS": DEMUCS, "RNNOISE": RNNOISE}


def _completed(
    code: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Return a CompletedProcess shaped like the pip call's result."""
    return subprocess.CompletedProcess(
        args=[], returncode=code, stdout=stdout, stderr=stderr
    )


class TestDeclaredRequirements:
    def test_packages_are_bare_names_the_validator_accepts(self) -> None:
        """``>=`` is a subprocess security pattern, so pip gets names only.

        The floor is enforced after the install instead; a spec carrying ``>``
        would be rejected by ``validate_arguments`` before pip ever ran.
        """
        for requirement in (DEMUCS, RNNOISE):
            for package in requirement.packages:
                assert not set(package) & set("><|&;`$"), package

    def test_each_label_names_its_distribution(self) -> None:
        assert DEMUCS.packages[0] == "demucs"
        assert RNNOISE.packages[0] == "pyrnnoise"

    def test_the_version_floors_match_the_ml_extra(self) -> None:
        """The floor verified here is the one ``pyproject.toml`` declares."""
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        declared = {
            spec.partition(">=")[0]: spec.partition(">=")[2]
            for spec in data["project"]["optional-dependencies"]["ml"]
        }

        assert declared[DEMUCS.packages[0]] == DEMUCS.minimum_version
        assert declared[RNNOISE.packages[0]] == RNNOISE.minimum_version


class TestProbe:
    """The availability check is a real import in a fresh process."""

    def test_an_importable_module_reports_no_failure(self) -> None:
        assert import_failure("json") is None

    def test_a_missing_module_reports_the_import_error(self) -> None:
        reason = import_failure("audio_suite_definitely_missing_module")

        assert reason is not None
        assert "ModuleNotFoundError" in reason

    def test_an_unknown_distribution_has_no_version(self) -> None:
        assert installed_version("audio_suite_definitely_missing_dist") is None


class TestVersionFloor:
    @pytest.mark.parametrize(
        ("version", "floor", "expected"),
        [
            ("4.1.0", "4.1.0", True),
            ("4.2.1", "4.1.0", True),
            ("4.0.9", "4.1.0", False),
            ("4.1", "4.1.0", True),
            ("5.0.0rc1", "4.1.0", True),
            (None, "4.1.0", False),
            ("1.0", None, True),
        ],
    )
    def test_meets_floor(
        self, version: str | None, floor: str | None, expected: bool
    ) -> None:
        assert meets_floor(version, floor) is expected


class TestEnsure:
    """``ensure`` installs only what is missing and verifies the result."""

    @staticmethod
    def _ensure(
        probe: MagicMock,
        *,
        pip: MagicMock | None = None,
        version: str | None = "4.1.0",
    ) -> InstallOutcome:
        runner = pip or MagicMock(return_value=_completed())
        return ensure(
            DEMUCS,
            pip_runner=runner,
            probe=probe,
            version_of=lambda _dist: version,
        )

    def test_an_importable_requirement_never_runs_pip(self) -> None:
        pip = MagicMock()
        probe = MagicMock(return_value=None)

        outcome = self._ensure(probe, pip=pip)

        assert outcome.ok is True
        assert "ready" in outcome.message
        pip.assert_not_called()

    def test_a_successful_install_reports_the_version(self) -> None:
        probe = MagicMock(side_effect=["no demucs", None])
        pip = MagicMock(return_value=_completed(stdout="Successfully installed demucs"))

        outcome = self._ensure(probe, pip=pip)

        assert outcome.ok is True
        assert "4.1.0" in outcome.message
        assert "Successfully installed" in outcome.detail
        pip.assert_called_once_with(DEMUCS.packages)

    def test_a_failed_pip_run_reports_its_own_output(self) -> None:
        probe = MagicMock(return_value="no demucs")
        pip = MagicMock(
            return_value=_completed(
                code=1, stderr="ERROR: Could not find a version that satisfies"
            )
        )

        outcome = self._ensure(probe, pip=pip)

        assert outcome.ok is False
        assert "could not be installed" in outcome.message
        assert "pip exited with code 1" in outcome.message
        assert "Could not find a version" in outcome.detail

    def test_an_install_that_still_does_not_import_is_a_failure(self) -> None:
        """pip's exit code is not proof: the import has to work afterwards."""
        probe = MagicMock(return_value="DLL load failed")
        pip = MagicMock(return_value=_completed(stdout="Successfully installed demucs"))

        outcome = self._ensure(probe, pip=pip)

        assert outcome.ok is False
        assert "still cannot be loaded" in outcome.message
        assert "DLL load failed" in outcome.message

    def test_a_version_below_the_floor_is_a_failure(self) -> None:
        probe = MagicMock(return_value=None)

        outcome = self._ensure(probe, version="4.0.0")

        assert outcome.ok is False
        assert "4.1.0 or newer is required" in outcome.message

    def test_a_pip_crash_is_reported_not_raised(self) -> None:
        probe = MagicMock(return_value="no demucs")
        pip = MagicMock(side_effect=OSError("no pip module"))

        outcome = self._ensure(probe, pip=pip)

        assert outcome.ok is False
        assert "no pip module" in outcome.message


class TestToolRequirementDeclaration:
    """``doctor`` reads the table; the tools must be the ones that fill it.

    ``TOOL_REQUIREMENTS`` is what ``audiosuite doctor`` reports, so a tool that
    starts installing an extra without being declared (or a stale entry for a
    tool that stopped) would make the report answer a question nobody asked.
    The scan derives the expected set from the call sites themselves.
    """

    @staticmethod
    def _references() -> dict[str, set[str]]:
        """Map each first-party package to the requirement constants it uses."""
        found: dict[str, set[str]] = {}
        for package in sorted(REPO_ROOT.iterdir()):
            if not (package / "__init__.py").is_file():
                continue
            for path in package.rglob("*.py"):
                if "tests" in path.relative_to(package).parts:
                    continue
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.Attribute)
                        and isinstance(node.value, ast.Name)
                        and node.value.id == "optional_deps"
                        and node.attr in _REQUIREMENTS
                    ):
                        found.setdefault(package.name, set()).add(node.attr)
        return found

    def test_every_tool_that_installs_an_extra_is_declared(self) -> None:
        found = self._references()
        # Non-vacuity: a scan that matched nothing would pass silently.
        assert found, "no tool references optional_deps.*; the scan is broken"

        declared = {
            tool: {
                name
                for name, requirement in _REQUIREMENTS.items()
                if requirement is wanted
            }
            for tool, wanted in TOOL_REQUIREMENTS.items()
        }

        assert found == declared, (
            "TOOL_REQUIREMENTS disagrees with the tools' own call sites: "
            f"declared {declared}, found {found}"
        )

    def test_the_declared_tool_ids_are_manifest_ids(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        known = {manifest.id for manifest in get_registry().all}

        assert set(TOOL_REQUIREMENTS) <= known, (
            "TOOL_REQUIREMENTS names tools that are not in the manifest: "
            f"{sorted(set(TOOL_REQUIREMENTS) - known)}"
        )
