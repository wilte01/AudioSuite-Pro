"""
AST lock: prevent reintroduction of dead code removed in E4 (M15).

Scans every first-party production module for names that were confirmed
dead by AST scan and deleted. Each parametrised test asserts the name
has zero definitions (FunctionDef/ClassDef/Assign-target) and zero
import references across the production tree.

A positive-control assertion (a known-live name IS found by the same
scanner) prevents the scan from passing vacuously.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directory parts the walk never reads. ``build``/``dist`` are the installer's
#: output (``packaging/build``, ``packaging/dist``, both gitignored): the staged
#: payload carries a bundled interpreter, and a bundled interpreter carries
#: CPython's own ``Lib/test/encoded_modules/*`` corpus, whose files are
#: deliberately not UTF-8. Reading one raised ``UnicodeDecodeError`` in this
#: fixture, so `bare pytest` reported 34 errors in this module for any developer
#: who had built the installer - a file they never touched, in a tree the lock
#: has no business judging. CI never sees it, which is why it went unnoticed.
#: Note ``tests`` does not cover it: the corpus path is ``Lib/test``,
#: singular. Changed in 2.1.6 (R-15,
#: PLAN_audit_2026-10-24_deferred_p2p3.md): the two parts are added.
_SKIP_DIR_PARTS = frozenset(
    {".venv", ".git", "__pycache__", "tests", ".mypy_cache", "build", "dist"}
)

# Names confirmed dead and deleted in E4 M15.
_DEAD_NAMES = frozenset(
    {
        "_ENHANCE_PRESETS",
        "check_integrity_batch",
        "_SENTINEL_MAP",
        "_output_dir_final",
    }
)

# A known-live name the same scanner must find — proves the scan is not
# vacuous.
_POSITIVE_CONTROL = "UniversalCLIHandler"


def _production_modules() -> list[tuple[str, ast.Module]]:
    """Parse every first-party production module, tests excluded."""
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
    """Map every defined name to the modules defining it."""
    found: dict[str, list[str]] = {}
    for rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                found.setdefault(node.name, []).append(rel)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found.setdefault(target.id, []).append(rel)
    return found


def _imported_names(modules: list[tuple[str, ast.Module]]) -> dict[str, list[str]]:
    """Map every imported name to the modules importing it."""
    found: dict[str, list[str]] = {}
    for rel, tree in modules:
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    bound = alias.asname or alias.name
                    found.setdefault(bound, []).append(rel)
    return found


@pytest.fixture(scope="module")
def production_modules() -> list[tuple[str, ast.Module]]:
    return _production_modules()


@pytest.fixture(scope="module")
def definitions(
    production_modules: list[tuple[str, ast.Module]],
) -> dict[str, list[str]]:
    return _definitions(production_modules)


@pytest.fixture(scope="module")
def imported_names(
    production_modules: list[tuple[str, ast.Module]],
) -> dict[str, list[str]]:
    return _imported_names(production_modules)


class TestE4DeadCodeLock:
    """AST lock: prevent reintroduction of M15 dead code."""

    def test_lock_is_not_vacuous(
        self, production_modules: list[tuple[str, ast.Module]]
    ) -> None:
        assert len(production_modules) >= 100, (
            f"production scan found only {len(production_modules)} modules"
        )

    def test_positive_control_is_found(self, definitions: dict[str, list[str]]) -> None:
        assert definitions.get(_POSITIVE_CONTROL), (
            f"{_POSITIVE_CONTROL} not found — scanner may be broken"
        )

    @pytest.mark.parametrize("name", sorted(_DEAD_NAMES))
    def test_dead_name_has_no_definition(
        self, name: str, definitions: dict[str, list[str]]
    ) -> None:
        assert name not in definitions, f"{name} reintroduced in {definitions[name]}"

    @pytest.mark.parametrize("name", sorted(_DEAD_NAMES))
    def test_dead_name_is_never_imported(
        self, name: str, imported_names: dict[str, list[str]]
    ) -> None:
        assert name not in imported_names, (
            f"{name} imported again by {imported_names[name]}"
        )

    def test_fingerprint_job_has_no_processor_field(self) -> None:
        """The `_FingerprintJob.processor` field was dead (the worker
        re-derives the slot from the queue).  Deleting it prevents the
        constructor from accepting a stale kwarg."""
        import dataclasses

        from audio_fingerprinter.core.file_processor import _FingerprintJob

        field_names = {f.name for f in dataclasses.fields(_FingerprintJob)}
        assert "processor" not in field_names, (
            "_FingerprintJob.processor field reintroduced"
        )
