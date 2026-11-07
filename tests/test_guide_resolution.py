"""Lock: there is exactly one guide resolver, and the retired copy stays gone.

PLAN_docs_consolidation P1.5. ``master_driver/utils/platform_utils.py`` held a
second ``open_help`` that resolved a guide *next to the calling script*, so it
could not find any guide in the centralised ``documentation/user_guides/`` tree.
Nothing in the application called it - ``master_driver/app.py`` routes its Help
button through
``_open_help_standard`` to ``audio_suite_shared.platform_utils.open_help`` - yet
the module shipped and a test kept it alive, which is how a divergent second
resolver survives: the Help-button path is only exercised through one of them.

The module and its test are deleted. This file is the absence lock that stops
the name coming back by accident, in the form AGENTS.md requires for a removed
public API: an AST scan, not a grep, so a mention in a comment or a docstring
cannot satisfy it.

The scan covers production modules only - a test may legitimately build a stub
called ``open_help`` - and asserts the result set is non-empty, so a broken walk
fails loudly instead of passing vacuously.

Changed in 2.1.0: new file - the deletion lock for the duplicate guide resolver
(PLAN_docs_consolidation P1.5).

Changed in 2.1.7: the retired resolver's message names ``documentation/user_guides/``.

Changed in 2.5.0: the Help button's ``guide_to_program`` map is locked
against the tool manifest. Every first-party tool must have an entry whose
file exists, no entry may belong to no tool, no guide folder on disk may be
unregistered, and every ``HELP_GUIDE`` constant an app hands the button must
be a registered filename - so a tool cannot ship with a Help button that
opens nothing.

"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from typing import Any

from tests.test_user_guide_hygiene import _guide_registry

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The one module allowed to define the resolver and the guide registry.
SHARED_RESOLVER = REPO_ROOT / "audio_suite_shared" / "platform_utils.py"

#: The module deleted by P1.5; its return would restore a divergent resolver.
RETIRED_MODULE = REPO_ROOT / "master_driver" / "utils" / "platform_utils.py"

_EXCLUDED_DIRS = frozenset({".venv", ".git", "__pycache__", "build", "dist"})


def _production_modules() -> list[Path]:
    """Return every first-party module, excluding tests and vendored trees.

    Returns:
        Sorted module paths under the repository root.
    """
    modules: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if any(part in _EXCLUDED_DIRS for part in relative.parts):
            continue
        # ``tests`` anywhere in the path: package suites live at
        # ``<pkg>/tests/`` and the cross-cutting suite at ``tests/``.
        if "tests" in relative.parts:
            continue
        modules.append(path)
    return modules


def _definition_count(path: Path, name: str) -> int:
    """Count how many times *name* is defined or assigned in *path*.

    Args:
        path: The module to parse.
        name: The function or module-level name to look for.

    Returns:
        The number of definitions/assignments binding *name* in the module.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count += 1 if node.name == name else 0
        elif isinstance(node, ast.Assign):
            count += sum(
                1
                for target in node.targets
                if isinstance(target, ast.Name) and target.id == name
            )
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                count += 1
    return count


class TestRetiredResolver:
    """The duplicate resolver is gone and cannot reappear unnoticed."""

    def test_the_master_driver_copy_stays_deleted(self) -> None:
        """The retired module must not be reintroduced."""
        assert not RETIRED_MODULE.exists(), (
            "master_driver/utils/platform_utils.py was deleted by "
            "PLAN_docs_consolidation P1.5: it held a second `open_help` that "
            "looked for a guide beside the calling script and could not resolve "
            "the centralised documentation/user_guides/ tree. The Master Driver uses "
            "audio_suite_shared.platform_utils.open_help through "
            "_open_help_standard - put new behaviour there."
        )

    def _modules_defining(self, name: str) -> list[tuple[Path, int]]:
        """Return ``(module, count)`` for every module that binds *name*.

        Args:
            name: The function or module-level name to look for.

        Returns:
            One entry per defining module, in path order.
        """
        return [
            (path, count)
            for path in _production_modules()
            if (count := _definition_count(path, name))
        ]

    def _assert_single_home(self, name: str) -> None:
        """Assert *name* is defined in the shared resolver and nowhere else.

        Args:
            name: The function or module-level name that must have one home.
        """
        hits = self._modules_defining(name)
        found = "\n  ".join(
            f"{path.relative_to(REPO_ROOT).as_posix()} ({count} definition(s))"
            for path, count in hits
        )
        assert [path for path, _ in hits] == [SHARED_RESOLVER], (
            f"expected `{name}` to be defined once, in "
            "audio_suite_shared/platform_utils.py; found:\n  " + found
        )

    def test_open_help_is_defined_in_one_module_only(self) -> None:
        """Exactly one production module defines ``open_help``."""
        self._assert_single_home("open_help")

    def test_the_guide_registry_has_one_definition(self) -> None:
        """Exactly one production module owns ``guide_to_program``."""
        self._assert_single_home("guide_to_program")

    def test_scan_is_non_vacuous(self) -> None:
        """The walk must actually reach the tree, not an empty selection."""
        modules = _production_modules()
        assert len(modules) > 100, (
            f"the production-module walk found only {len(modules)} files; "
            "its exclusion rules are wrong, so the locks above prove nothing"
        )
        assert SHARED_RESOLVER.is_file(), (
            f"the surviving resolver is missing: {SHARED_RESOLVER}"
        )


#: Where the Help button looks for a tool's rendered guide.
GUIDE_ROOT = REPO_ROOT / "documentation" / "user_guides" / "individual_programs"

#: The generator that owns the tool-id-to-filename rule, loaded by path
#: because ``utilities/`` is a directory of scripts, not a package.
README_INDEX = REPO_ROOT / "utilities" / "generate_readme_tool_index.py"


def _load_readme_index() -> Any:
    """Load the README index generator, which owns the guide-name rule."""
    spec = importlib.util.spec_from_file_location("_guide_readme", README_INDEX)
    assert spec is not None and spec.loader is not None, (
        "cannot load the tool-id-to-guide-name rule from " + str(README_INDEX)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _shipped_modules() -> list[Path]:
    """Return shipped modules, excluding tests, tooling and the docs tree."""
    excluded = frozenset(
        {".venv", ".git", "__pycache__", "tests", "utilities", "documentation"}
    )
    return [
        path
        for path in sorted(REPO_ROOT.rglob("*.py"))
        if not excluded & set(path.relative_to(REPO_ROOT).parts)
    ]


def _app_guide_constants() -> set[str]:
    """Return every non-empty ``HELP_GUIDE`` filename a shipped app declares."""
    import ast as _ast

    found: set[str] = set()
    for path in _shipped_modules():
        tree = _ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _ast.walk(tree):
            value: _ast.expr | None = None
            if isinstance(node, _ast.Assign) and any(
                isinstance(target, _ast.Name) and target.id == "HELP_GUIDE"
                for target in node.targets
            ):
                value = node.value
            elif (
                isinstance(node, _ast.AnnAssign)
                and isinstance(node.target, _ast.Name)
                and node.target.id == "HELP_GUIDE"
            ):
                value = node.value
            if (
                isinstance(value, _ast.Constant)
                and isinstance(value.value, str)
                and value.value
            ):
                found.add(value.value)
    assert len(found) >= 20, f"the HELP_GUIDE scan found only {len(found)}"
    return found


class TestGuideMapAgainstManifest:
    """Every manifest tool reaches its guide through the Help map."""

    def test_every_tool_has_a_registered_reachable_guide(self) -> None:
        """A tool whose guide is unregistered has a button that fails."""
        from audio_suite_shared.tool_plugin import get_registry

        registry = _guide_registry()
        readme = _load_readme_index()
        offenders: list[str] = []
        for manifest in get_registry().first_party:
            name = readme.guide_filename_for(manifest.id, manifest.pyw_filename)
            folder = registry.get(name)
            if folder is None:
                offenders.append(f"{manifest.id}: {name} is not registered")
                continue
            if not (GUIDE_ROOT / folder / name).is_file():
                offenders.append(
                    f"{manifest.id}: {name} maps to {folder}/, which holds no such file"
                )
        assert registry, "guide_to_program parsed as empty"
        assert offenders == [], (
            "these tools cannot reach their guide through the Help button: "
            + "; ".join(offenders)
        )

    def test_no_registered_guide_belongs_to_no_tool(self) -> None:
        """A stale entry is a filename no tool or app can open."""
        from audio_suite_shared.tool_plugin import get_registry

        readme = _load_readme_index()
        known = {
            readme.guide_filename_for(manifest.id, manifest.pyw_filename)
            for manifest in get_registry().first_party
        } | _app_guide_constants()
        orphans = sorted(set(_guide_registry()) - known)
        assert orphans == [], (
            "guide_to_program registers guides nothing opens: " + ", ".join(orphans)
        )

    def test_every_guide_folder_is_registered(self) -> None:
        """A folder no entry names is a guide nobody can reach."""
        on_disk = {entry.name for entry in GUIDE_ROOT.iterdir() if entry.is_dir()}
        registered = set(_guide_registry().values())
        assert on_disk, "no guide folders found"
        assert on_disk == registered, (
            "guide folders and guide_to_program disagree: "
            f"unregistered={sorted(on_disk - registered)} "
            f"missing={sorted(registered - on_disk)}"
        )

    def test_every_app_guide_constant_is_registered(self) -> None:
        """The filename an app hands the button must be the registered one."""
        import ast as _ast

        registry = _guide_registry()
        offenders: list[str] = []
        seen = 0
        for path in _shipped_modules():
            tree = _ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in _ast.walk(tree):
                value: _ast.expr | None = None
                if isinstance(node, _ast.Assign) and any(
                    isinstance(target, _ast.Name) and target.id == "HELP_GUIDE"
                    for target in node.targets
                ):
                    value = node.value
                elif (
                    isinstance(node, _ast.AnnAssign)
                    and isinstance(node.target, _ast.Name)
                    and node.target.id == "HELP_GUIDE"
                ):
                    value = node.value
                if not (
                    isinstance(value, _ast.Constant)
                    and isinstance(value.value, str)
                    and value.value
                ):
                    continue
                seen += 1
                if value.value not in registry:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}: {value.value}"
                    )
        assert seen >= 20, f"the HELP_GUIDE scan found only {seen} constants"
        assert offenders == [], (
            "these HELP_GUIDE constants are not in guide_to_program: "
            + ", ".join(offenders)
        )
