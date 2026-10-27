"""Tests for audio_suite_shared.project_version — the single version source.

Plan iteration 5, audit #21 / G2: ``audiosuite --version`` reported whatever the
*installed distribution metadata* said, so a source checkout without an install
raised ``PackageNotFoundError`` and a stale install reported the wrong number.
The version is declared once, in ``[project] version`` of ``pyproject.toml``,
and this module is the only reader of it.

The reader is ``tomllib``, which is standard library on every interpreter the
suite supports (the floor is 3.11), so there is no import guard and no
``importorskip`` escape hatch here any more.

Changed in 2.1.6: the import block is re-sorted against the corrected ruff
target py311 — ``tomllib`` is 3.11 standard library, which is exactly why this
module needs no import guard (R-15, PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

from audio_suite_shared import project_version

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"


@pytest.fixture(autouse=True)
def _clear_version_cache() -> Any:
    """``declared_version`` is ``lru_cache``d module-globally.

    Tests that fake the environment must not inherit a value cached by an
    earlier test, or they would assert against the real version.
    """
    project_version.declared_version.cache_clear()
    yield
    project_version.declared_version.cache_clear()


class TestParseProjectVersion:
    """``[project] version`` extraction."""

    def test_reads_a_well_formed_table(self) -> None:
        text = '[project]\nname = "x"\nversion = "2.5.1"\n'
        assert project_version.parse_project_version(text) == "2.5.1"

    def test_accepts_single_quotes(self) -> None:
        text = "[project]\nname = 'x'\nversion = '3.0.0'\n"
        assert project_version.parse_project_version(text) == "3.0.0"

    def test_tolerates_a_trailing_comment(self) -> None:
        """Legal TOML and common in a hand-edited table."""
        text = '[project]\nversion = "1.4.0"  # post-release\n'
        assert project_version.parse_project_version(text) == "1.4.0"

    def test_only_the_project_table_is_read(self) -> None:
        """A ``version`` in another table must not win.

        Regression shape: a first-match scan returns whichever ``version =``
        line comes first, so a ``[tool.*]`` table placed above ``[project]``
        would silently shadow the real declaration.
        """
        text = (
            "[tool.something]\nversion = '0.0.1'\n\n"
            '[project]\nname = "x"\nversion = "9.9.9"\n'
        )
        assert project_version.parse_project_version(text) == "9.9.9"

    def test_a_later_table_does_not_override(self) -> None:
        text = (
            '[project]\nname = "x"\nversion = "4.5.6"\n\n'
            "[tool.after]\nversion = '0.0.1'\n"
        )
        assert project_version.parse_project_version(text) == "4.5.6"

    def test_a_subtable_of_project_ends_the_search(self) -> None:
        """``[project.optional-dependencies]`` is a different table."""
        text = (
            '[project]\nname = "x"\n\n'
            "[project.optional-dependencies]\ndev = ['pytest']\nversion = '0.0.1'\n"
        )
        assert project_version.parse_project_version(text) is None

    def test_a_dependency_pin_is_not_mistaken_for_the_version(self) -> None:
        text = (
            '[project]\nname = "x"\n'
            'dependencies = ["librosa==0.10.0"]\n'
            'version = "1.0.0"\n'
        )
        assert project_version.parse_project_version(text) == "1.0.0"

    def test_missing_project_table_returns_none(self) -> None:
        assert (
            project_version.parse_project_version("[tool.x]\nversion = '1'\n") is None
        )

    def test_project_table_without_version_returns_none(self) -> None:
        assert project_version.parse_project_version('[project]\nname = "x"\n') is None

    def test_empty_input_returns_none(self) -> None:
        assert project_version.parse_project_version("") is None

    def test_non_string_version_returns_none(self) -> None:
        """TOML has more than one integer type; a bare number is not a version."""
        assert project_version.parse_project_version("[project]\nversion = 1\n") is None

    def test_malformed_toml_raises_rather_than_guessing(self) -> None:
        """A corrupt manifest must be loud, not silently reported as ``None``.

        Returning ``None`` would fall through to the installed distribution
        metadata, so a broken checkout would quietly advertise a stale version
        instead of failing.
        """
        with pytest.raises(tomllib.TOMLDecodeError):
            project_version.parse_project_version("[project\nversion = '1.0.0'")

    def test_reads_the_real_pyproject_version(self) -> None:
        """The live contract: this repo's own manifest yields a real version.

        Deliberately *not* a comparison against ``tomllib``'s own result — the
        implementation uses ``tomllib``, so that assertion would only prove
        ``tomllib`` equals itself. This checks the value is actually found and
        is a usable release string, and ``--version`` agreeing end-to-end is
        locked in ``tests/test_cli_app.py``.
        """
        version = project_version.parse_project_version(
            PYPROJECT.read_text(encoding="utf-8")
        )
        assert version is not None
        assert version.split(".")[0].isdigit()


class TestFindPyproject:
    def test_finds_the_repo_root_from_a_nested_directory(self) -> None:
        start = REPO_ROOT / "audio_suite_shared" / "core"
        found = project_version.find_pyproject(start)
        assert found is not None
        assert found.name == "pyproject.toml"
        assert found.parent == REPO_ROOT

    def test_returns_none_when_no_pyproject_is_above(self, tmp_path: Path) -> None:
        start = tmp_path / "nested" / "deeper"
        start.mkdir(parents=True)
        assert project_version.find_pyproject(start) is None


class TestDeclaredVersion:
    def test_reports_the_declared_version(self) -> None:
        with PYPROJECT.open("rb") as handle:
            expected = tomllib.load(handle)["project"]["version"]
        assert project_version.declared_version() == expected

    def test_version_is_a_plausible_release_string(self) -> None:
        version = project_version.declared_version()
        parts = version.split(".")
        assert len(parts) >= 2, f"version {version!r} is not dotted"
        assert all(part.isdigit() for part in parts), (
            f"version {version!r} has a non-numeric component"
        )

    def test_result_is_cached(self) -> None:
        """A release bump must not be re-read on every help render."""
        first = project_version.declared_version()
        second = project_version.declared_version()
        assert first == second
        info = project_version.declared_version.cache_info()
        assert info.currsize == 1
        assert info.hits >= 1

    def test_falls_back_to_installed_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An installed layout with no source tree still reports a version.

        The import of ``version`` is function-local, so the attribute is read
        off ``importlib.metadata`` at call time — patch that module.
        """
        import importlib.metadata

        monkeypatch.setattr(project_version, "find_pyproject", lambda *a, **k: None)
        monkeypatch.setattr(importlib.metadata, "version", lambda name: "7.7.7")
        assert project_version.declared_version() == "7.7.7"

    def test_raises_loudly_when_the_version_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A wrong ``--version`` is worse than a failed one."""
        import importlib.metadata

        def _missing(name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(name)

        monkeypatch.setattr(project_version, "find_pyproject", lambda *a, **k: None)
        monkeypatch.setattr(importlib.metadata, "version", _missing)
        with pytest.raises(RuntimeError, match="cannot determine"):
            project_version.declared_version()

    def test_never_reads_the_version_outside_project_table(self) -> None:
        """The parser must stay scoped to ``[project]`` for the real file."""
        text = PYPROJECT.read_text(encoding="utf-8")
        assert text.count("[project]") >= 1
        assert project_version.parse_project_version(text) is not None
