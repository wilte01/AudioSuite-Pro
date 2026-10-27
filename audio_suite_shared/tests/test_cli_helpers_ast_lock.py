"""
AST lock: prevent reintroduction of the deleted legacy argparse subsystem.

Iteration-8 E1 removed the production-dead argparse layer from
``audio_suite_shared/cli_helpers.py`` (~300 lines, six public names). This
module pins the deletion so it cannot creep back.

The lock scans *every* first-party production module (``.py`` and ``.pyw``,
tests excluded) rather than the one file the code was deleted from: a
reintroduction in any other module is just as much a regression, and a
single-file scan is the vacuous-scan trap in miniature.

Names are grouped by what the tree should guarantee:

* ``_REMOVED_NAMES`` -- deleted outright; zero definitions and zero imports
  anywhere in production.
* ``parse_cli_args`` -- survives, but only as the launcher entry point; the
  name collision this item resolved was two modules defining it, so exactly
  one defining module must remain and nothing may import it from
  ``cli_helpers``.
* ``configure_logging`` -- survives, but only in ``logging_setup`` since
  iteration-9 G4.1.  It was moved out of ``app_bootstrap`` (which imports
  tkinter at module level, so the headless CLI could not reach it) and
  bootstrap now holds exactly one explicit import-alias.  Two modules
  defining it -- or bootstrap silently re-growing a ``def`` -- would strand
  the CLI back on stderr-only ``logging.basicConfig``, which is audit
  finding M1.  ``cli_helpers``/``cli_base`` must not define it either:
  ``cli_base`` *imports* it so its own test can patch
  ``audio_suite_shared.cli_base.configure_logging`` by attribute.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
#: Directory parts the walk never reads.  ``build``/``dist`` are the installer's
#: gitignored output (``packaging/build``): the staged payload carries a copy of
#: every first-party module *and* a bundled CPython whose ``Lib/test`` corpus is
#: not UTF-8, so this fixture raised ``UnicodeDecodeError`` and `bare pytest`
#: reported 24 errors in this module for any developer who had built the
#: installer - a tree the lock has no business judging.  CI never builds it,
#: which is why it went unnoticed.
#: Changed in 2.1.6 (R-15, PLAN_audit_2026-10-24_deferred_p2p3.md): added.
_SKIP_DIR_PARTS = frozenset(
    {".venv", ".git", "__pycache__", "tests", ".mypy_cache", "build", "dist"}
)

#: Deleted outright in E1: no definition and no import reference survives.
_REMOVED_NAMES = frozenset(
    {
        "SourceOutputCLIHandler",
        "StandardCLIHandler",
        "apply_stage_args",
        "build_arg_parser",
        "create_standard_parser",
        "dump_defaults",
        "get_default_values",
        "stage_flags_from_args",
        "validate_cli_args",
    }
)

#: The one surviving name whose *defining module* is the invariant.
#: The one surviving name whose *defining* and *importing-from* modules are
#: both invariants -- two modules used to define it with different semantics.
_LAUNCHER_MODULE = "audio_suite_shared.launcher"
_LAUNCHER_ENTRY_POINT = "parse_cli_args"
_LAUNCHER_OWNER = "audio_suite_shared/launcher.py"
_RELOCATED_OWNER = "configure_logging"
_RELOCATED_MODULE = "audio_suite_shared/logging_setup.py"
#: The module that must re-export it: exactly one import-alias, no ``def``.
_BOOTSTRAP_MODULE = "audio_suite_shared/app_bootstrap.py"

#: A live name the same scanner must find -- proves the scan is not vacuous.
_POSITIVE_CONTROL = "UniversalCLIHandler"


def _production_modules() -> list[tuple[str, ast.Module]]:
    """Parse every first-party production module, tests excluded.

    Returns:
        ``(posix_relative_path, parsed_tree)`` for each ``.py``/``.pyw``
        module outside the skip set.
    """
    modules: list[tuple[str, ast.Module]] = []
    for pattern in ("*.py", "*.pyw"):
        for path in sorted(_REPO_ROOT.rglob(pattern)):
            rel = path.relative_to(_REPO_ROOT)
            if _SKIP_DIR_PARTS & set(rel.parts):
                continue
            source = path.read_text(encoding="utf-8")
            modules.append((rel.as_posix(), ast.parse(source, filename=rel.as_posix())))
    return modules


def _definitions(modules: list[tuple[str, ast.Module]]) -> dict[str, list[str]]:
    """Map every defined function/class name to the modules defining it."""
    found: dict[str, list[str]] = {}
    for rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(node.name, []).append(rel)
    return found


def _imported_names(modules: list[tuple[str, ast.Module]]) -> dict[str, set[str]]:
    """Map every imported name to the set of modules importing it."""
    found: dict[str, set[str]] = {}
    for rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    found.setdefault(bound, set()).add(rel)
    return found


def _import_sources(modules: list[tuple[str, ast.Module]]) -> dict[str, set[str]]:
    """Map every imported name to the set of modules it is imported *from*.

    Distinct from `_imported_names`: the reintroduction this lock must catch is
    ``from audio_suite_shared.cli_helpers import parse_cli_args``, so the
    module being imported from is the evidence, not the importing file's path.
    """
    found: dict[str, set[str]] = {}
    for _rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                source = node.module or ""
                for alias in node.names:
                    found.setdefault(alias.asname or alias.name, set()).add(source)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.setdefault(alias.asname or alias.name, set()).add(alias.name)
    return found


@pytest.fixture(scope="module")
def production_modules() -> list[tuple[str, ast.Module]]:
    """Parse the production tree once for the whole module."""
    return _production_modules()


@pytest.fixture(scope="module")
def definitions(
    production_modules: list[tuple[str, ast.Module]],
) -> dict[str, list[str]]:
    """Function/class definitions across the production tree."""
    return _definitions(production_modules)


@pytest.fixture(scope="module")
def imported_names(
    production_modules: list[tuple[str, ast.Module]],
) -> dict[str, set[str]]:
    """Imported names across the production tree, keyed by importing module."""
    return _imported_names(production_modules)


@pytest.fixture(scope="module")
def import_sources(
    production_modules: list[tuple[str, ast.Module]],
) -> dict[str, set[str]]:
    """Imported names across the production tree, keyed by imported-from module."""
    return _import_sources(production_modules)


class TestCliHelpersArgparseCleanup:
    """AST lock: prevent reintroduction of removed dead argparse names."""

    def test_lock_is_not_vacuous(
        self, production_modules: list[tuple[str, ast.Module]]
    ) -> None:
        """The scan must find the tree, and find a live name with it.

        Without this, an over-broad skip set or a wrong root would make every
        absence assertion below pass by scanning nothing.
        """
        assert len(production_modules) >= 100, (
            f"production scan found only {len(production_modules)} modules; "
            "a skip set that wide makes every absence assertion vacuous"
        )
        assert "audio_suite_shared/cli_helpers.py" in {
            rel for rel, _ in production_modules
        }
        assert "audio_suite_shared/launcher.py" in {
            rel for rel, _ in production_modules
        }

    def test_positive_control_name_is_found(
        self,
        definitions: dict[str, list[str]],
        imported_names: dict[str, set[str]],
    ) -> None:
        """A known-live name is located by the same scanners the lock uses."""
        assert definitions.get(_POSITIVE_CONTROL), (
            f"{_POSITIVE_CONTROL} is live in cli_helpers but the scanner found no "
            "definition, so the absence assertions cannot be trusted"
        )
        importers = imported_names.get(_POSITIVE_CONTROL, set())
        assert len(importers) >= 10, (
            f"{_POSITIVE_CONTROL} has ~17 production importers; the scanner found "
            f"{len(importers)}"
        )

    @pytest.mark.parametrize("name", sorted(_REMOVED_NAMES))
    def test_removed_name_has_no_definition(
        self, name: str, definitions: dict[str, list[str]]
    ) -> None:
        """No production module defines a name E1 deleted."""
        assert name not in definitions, (
            f"{name} is defined again in {definitions[name]}"
        )

    @pytest.mark.parametrize("name", sorted(_REMOVED_NAMES))
    def test_removed_name_is_never_imported(
        self, name: str, imported_names: dict[str, set[str]]
    ) -> None:
        """No production module imports a name E1 deleted."""
        assert name not in imported_names, (
            f"{name} is imported again by {sorted(imported_names[name])}"
        )

    def test_launcher_entry_point_is_defined_once(
        self, definitions: dict[str, list[str]]
    ) -> None:
        """`parse_cli_args` survives in exactly one module, resolving the collision."""
        assert definitions.get(_LAUNCHER_ENTRY_POINT) == [_LAUNCHER_OWNER], (
            f"{_LAUNCHER_ENTRY_POINT} must be defined only by {_LAUNCHER_OWNER}; "
            f"found {definitions.get(_LAUNCHER_ENTRY_POINT)}"
        )

    def test_launcher_entry_point_is_imported_only_from_the_launcher(
        self, import_sources: dict[str, set[str]]
    ) -> None:
        """The 19 `.pyw` launchers import the launcher, never `cli_helpers`."""
        sources = import_sources.get(_LAUNCHER_ENTRY_POINT, set())
        assert sources == {_LAUNCHER_MODULE}, (
            f"{_LAUNCHER_ENTRY_POINT} must be imported only from {_LAUNCHER_MODULE}; "
            f"found {sorted(sources)}"
        )

    def test_configure_logging_is_defined_only_in_logging_setup(
        self, definitions: dict[str, list[str]]
    ) -> None:
        """The single definition lives in the Tk-free module (G4.1).

        ``app_bootstrap`` imports tkinter at module level, so a ``def`` there
        would put the headless CLI — and any other Tk-free caller — back on
        stderr-only ``logging.basicConfig`` (audit M1).  The same assertion
        also proves ``cli_helpers`` and ``cli_base`` do not *define* it:
        ``cli_base`` imports it precisely so its test can patch the
        attribute on that module.
        """
        assert definitions.get(_RELOCATED_OWNER) == [_RELOCATED_MODULE], (
            f"{_RELOCATED_OWNER} must be defined only by {_RELOCATED_MODULE}; "
            f"found {definitions.get(_RELOCATED_OWNER)}"
        )

    def test_app_bootstrap_reexports_configure_logging_without_redefining(
        self,
        production_modules: list[tuple[str, ast.Module]],
        definitions: dict[str, list[str]],
    ) -> None:
        """Bootstrap holds exactly one import-alias and no ``def``.

        The redundant-alias form (``import configure_logging as
        configure_logging``) is what ``mypy --strict`` accepts as an
        explicit re-export; a bare import would fail ``attr-defined`` at
        every ``app_bootstrap.configure_logging`` call site.  Exactly one
        binding keeps the monkeypatch seam in
        ``tests/test_package_entry_stubs.py`` pointing at one object.
        """
        assert _BOOTSTRAP_MODULE not in definitions.get(_RELOCATED_OWNER, []), (
            f"{_BOOTSTRAP_MODULE} must not define {_RELOCATED_OWNER}"
        )

        bindings: list[str | None] = []
        for rel, tree in production_modules:
            if rel != _BOOTSTRAP_MODULE:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                for alias in node.names:
                    if alias.name == _RELOCATED_OWNER:
                        bindings.append(alias.asname)
        assert bindings == [_RELOCATED_OWNER], (
            f"{_BOOTSTRAP_MODULE} must hold exactly one "
            f"`{_RELOCATED_OWNER} as {_RELOCATED_OWNER}` import-alias "
            f"(mypy --strict explicit re-export); found bindings {bindings}"
        )
