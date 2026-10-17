"""Every module that records a run note must record under a real manifest id.

Changed in 1.2.0: initial version, the cross-tool lock for the run-note channel.

The Master Driver keys a batch step by the tool's **manifest id**
(``audio_suite_shared.tool_plugin``) and reads that tool's note back by the same
key, so a note recorded under any other string is silently never shown: the tool
looks like it reports nothing, and no test of the tool's own package can see it.
Tool apps already carry a ``TOOL_ID`` that is a *window/logger* key and is not
always the manifest id (``audio_fingerprinter`` against ``fingerprinter``), which
is exactly the trap.

This lock derives the rule from the tree instead of trusting a table:

* it scans every first-party package for a call to ``record_outcome`` or
  ``record_caveats``, and requires that same module to declare a module-level
  ``DRIVER_TOOL_ID`` — the constant and the call live together, so a new caller
  cannot borrow another module's id;
* every declared id must be a registered manifest id;
* the id must also be recognisable from the package it is declared in
  (substring, either way), so copying ``cd_ripper``'s ``"cd_ripper"`` into
  another tool fails here rather than losing that tool's notes in production.
  ``_ID_ALIASES`` is the explicit, non-empty-checked escape hatch for a future
  tool whose manifest id shares no text with its package name;
* the scan asserts it found callers at all, so a broken walk cannot pass
  vacuously (project AGENTS: an empty scan must fail loudly).

The files are parsed, never imported: the apps' modules build Tk widgets at
import time and this is a static contract.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audio_suite_shared.tool_plugin import get_registry

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The module-level constant a note-recording module must declare.
ID_CONSTANT = "DRIVER_TOOL_ID"

#: Functions from :mod:`audio_suite_shared.run_outcome` that write a note.
RECORDERS = frozenset({"record_outcome", "record_caveats"})

#: Package name to manifest id, for a tool whose two names share no text.
#: Empty today: every tool that records a note is recognisable from its package.
_ID_ALIASES: dict[str, str] = {}


def _first_party_packages() -> list[Path]:
    """Return the suite's tool packages, as directories at the repo root.

    A package is a root directory holding ``__init__.py``; ``tests`` is the
    suite's own top-level test package rather than a tool, and root modules
    (``conftest.py``) are not packages at all.

    Returns:
        Package directories, sorted.
    """
    return sorted(
        entry
        for entry in REPO_ROOT.iterdir()
        if entry.is_dir()
        and entry.name != "tests"
        and (entry / "__init__.py").is_file()
    )


def _records_a_note(tree: ast.Module) -> bool:
    """Return whether ``tree`` calls one of the note recorders.

    Matches both the imported form (``record_caveats(...)``) and an attribute
    call (``run_outcome.record_caveats(...)``), so neither import style slips
    past the scan.

    Args:
        tree: A parsed module.

    Returns:
        True when the module writes a note.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in RECORDERS:
            return True
        if isinstance(func, ast.Attribute) and func.attr in RECORDERS:
            return True
    return False


def _defines_a_recorder(tree: ast.Module) -> bool:
    """Return whether ``tree`` *defines* one of the note recorders.

    The channel's own module defines them (and ``record_caveats`` calls
    ``record_outcome``), so without this it would be scanned as a caller and
    asked for an id of its own.

    Args:
        tree: A parsed module.

    Returns:
        True when the module implements the channel rather than using it.
    """
    return any(
        isinstance(node, ast.FunctionDef) and node.name in RECORDERS
        for node in tree.body
    )


def _declared_id(tree: ast.Module) -> str | None:
    """Return the module-level ``DRIVER_TOOL_ID`` string, or None.

    Args:
        tree: A parsed module.

    Returns:
        The literal value, or None when the constant is absent or not a plain
        string literal (a computed id cannot be checked, so it is refused).
    """
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        if not any(
            isinstance(target, ast.Name) and target.id == ID_CONSTANT
            for target in targets
        ):
            continue
        try:
            value = ast.literal_eval(node.value) if node.value is not None else None
        except ValueError:
            return None
        return value if isinstance(value, str) else None
    return None


def _recording_modules() -> list[tuple[Path, ast.Module]]:
    """Return ``(path, tree)`` for every first-party module that records a note.

    Returns:
        The recording modules, sorted by path.  Test modules are skipped: a
        tool's tests may record a note to exercise the channel, and they do not
        own the id.
    """
    found: list[tuple[Path, ast.Module]] = []
    for package in _first_party_packages():
        for path in sorted(package.rglob("*.py")):
            if "tests" in path.relative_to(package).parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if _records_a_note(tree) and not _defines_a_recorder(tree):
                found.append((path, tree))
    return found


@pytest.fixture(scope="module")
def recording_modules() -> list[tuple[Path, ast.Module]]:
    """The scan, shared across this module's tests."""
    return _recording_modules()


@pytest.fixture(scope="module")
def manifest_ids() -> set[str]:
    """Every registered manifest id."""
    return {manifest.id for manifest in get_registry().all}


class TestTheScanIsReal:
    def test_the_channel_is_used_by_tool_modules(
        self, recording_modules: list[tuple[Path, ast.Module]]
    ) -> None:
        """An empty scan would make every rule below pass vacuously."""
        assert len(recording_modules) >= 8, [str(path) for path, _ in recording_modules]


class TestDeclaredIds:
    def test_every_recording_module_declares_an_id(
        self, recording_modules: list[tuple[Path, ast.Module]]
    ) -> None:
        missing = [
            str(path.relative_to(REPO_ROOT))
            for path, tree in recording_modules
            if _declared_id(tree) is None
        ]

        assert not missing, (
            f"these modules record a run note without a {ID_CONSTANT} string "
            "constant, so the Master Driver cannot read their note:\n  "
            + "\n  ".join(missing)
        )

    def test_every_declared_id_is_a_manifest_id(
        self,
        recording_modules: list[tuple[Path, ast.Module]],
        manifest_ids: set[str],
    ) -> None:
        unknown = [
            f"{path.relative_to(REPO_ROOT)}: {_declared_id(tree)!r}"
            for path, tree in recording_modules
            if _declared_id(tree) not in manifest_ids
        ]

        assert not unknown, (
            "these modules record a note under an id no manifest declares, so "
            "the note would never reach the batch report:\n  " + "\n  ".join(unknown)
        )

    def test_every_declared_id_matches_its_own_package(
        self,
        recording_modules: list[tuple[Path, ast.Module]],
    ) -> None:
        """A copy-pasted id from another tool must fail here, not in production."""

        def package_of(path: Path) -> str:
            return path.relative_to(REPO_ROOT).parts[0]

        wrong = []
        for path, tree in recording_modules:
            tool_id = _declared_id(tree)
            package = package_of(path)
            if tool_id is None or _ID_ALIASES.get(package) == tool_id:
                continue
            if tool_id in package or package in tool_id:
                continue
            wrong.append(f"{path.relative_to(REPO_ROOT)}: {tool_id!r}")

        assert not wrong, (
            "these modules record a note under an id that does not belong to the "
            "package it is written in (add the pair to _ID_ALIASES if the names "
            "genuinely share no text):\n  " + "\n  ".join(wrong)
        )
