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

"""

from __future__ import annotations

import ast
from pathlib import Path

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
