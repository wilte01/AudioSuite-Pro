"""
Lock: every shipped ``*/ui/`` module is reachable from a non-test importer.

The audit's C-M9 found ``noise_reduction/ui/setup_tab.py`` — 173 lines of a
dashboard that no tool ever showed, because the tool became a stage of the
Refinery and its ``ui`` package kept the leftover tab. Nothing failed: an
unimported module is not an untested one, so the suite stayed green while the
code was dead.

The scan parses every shipped module (``.py`` and ``.pyw`` — two ``ui/app.py``
windows are reached only from their launchers) and resolves each import to the
module path it binds, including relative forms such as ``from .ui import
setup_tab``. Test modules are not importers: a ``ui`` package kept alive only by
its own tests is exactly the shape that hides.

The Master Driver's cards are exempt by *evidence*, not by name: they are loaded
through an ``importlib`` f-string template in two files, and this lock reads that
template out of those files, so deleting or renaming the loader fails here
instead of silently widening the exemption.

Changed in 2.4.1: new lock for orphan ui modules (plan WP-3, C-M9).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directory names that are not the shipped runtime (same set the subprocess
#: policy lock uses, plus the docs build output).
SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "docs",
        "plugins",
        "utilities",
    }
)

#: The importlib template the Master Driver cards are loaded through, and the
#: two files that carry it.
CARD_PREFIX = "master_driver.ui.cards."
CARD_LOADERS: tuple[str, ...] = (
    "master_driver/ui/enrich_tab.py",
    "master_driver/ui/utilities_window.py",
)


def _source_files() -> list[Path]:
    """Return every shipped module: ``.py`` and ``.pyw``, tests excluded.

    Returns:
        Sorted paths outside :data:`SKIPPED_DIRS` that are not test modules.
    """
    files: list[Path] = []
    for pattern in ("*.py", "*.pyw"):
        for path in sorted(REPO_ROOT.rglob(pattern)):
            rel = path.relative_to(REPO_ROOT)
            if SKIPPED_DIRS.intersection(rel.parts[:-1]):
                continue
            if "tests" in rel.parts[:-1] or rel.name.startswith("test_"):
                continue
            files.append(path)
    return files


def _module_parts(path: Path) -> list[str]:
    """Return the dotted parts a module is importable under.

    Args:
        path: The module's absolute path.

    Returns:
        The path's components without the extension.
    """
    return list(path.relative_to(REPO_ROOT).with_suffix("").parts)


def _imported_names(path: Path, parts: list[str]) -> set[str]:
    """Return every module path this file imports, fully qualified.

    Args:
        path: The importing module's absolute path.
        parts: The importer's own dotted parts.

    Returns:
        Fully qualified names, including the name each ``from`` import binds.
    """
    names: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = parts if path.name == "__init__.py" else parts[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            level = node.level or 0
            if level > len(package):
                base: list[str] = []
            elif level:
                base = package[: len(package) - (level - 1)]
            else:
                base = []
            target = list(base) + (node.module.split(".") if node.module else [])
            if target:
                names.add(".".join(target))
                for alias in node.names:
                    names.add(".".join(target + [alias.name]))
    return names


def _ui_modules() -> dict[str, Path]:
    """Return every shipped ``*/ui/*.py`` module except package markers.

    Returns:
        Mapping of dotted module path to its file.
    """
    found: dict[str, Path] = {}
    for path in _source_files():
        parts = _module_parts(path)
        if "ui" not in parts[:-1] or path.name == "__init__.py":
            continue
        found[".".join(parts)] = path
    return found


def _importers() -> dict[str, set[str]]:
    """Return, for every imported module path, the modules importing it.

    Returns:
        Mapping of imported module path to the importing modules' dotted paths.
    """
    index: dict[str, set[str]] = {}
    for path in _source_files():
        dotted = ".".join(_module_parts(path))
        for name in _imported_names(path, _module_parts(path)):
            index.setdefault(name, set()).add(dotted)
    return index


UI_MODULES = _ui_modules()
IMPORTERS = _importers()


class TestTheScanIsReal:
    def test_the_ui_tree_is_discovered(self) -> None:
        assert len(UI_MODULES) >= 100, sorted(UI_MODULES)[:5]
        assert {
            "bpm_analyzer.ui.setup_tab",
            "master_driver.ui.cards.bpm_card",
            "restoration.ui.app",
        } <= set(UI_MODULES)

    def test_the_launchers_count_as_importers(self) -> None:
        # ``restoration/ui/app.py`` is reached only from ``Restoration.pyw``;
        # a scan restricted to ``.py`` files would call it an orphan.
        assert (REPO_ROOT / "Restoration.pyw").is_file()
        assert "Restoration" in IMPORTERS["restoration.ui.app"]


class TestEveryUiModuleIsReached:
    def test_no_ui_module_is_orphaned(self) -> None:
        orphans = sorted(
            name
            for name in UI_MODULES
            if name.startswith(CARD_PREFIX) is False
            and not (IMPORTERS.get(name, set()) - {name})
        )
        assert not orphans, (
            "ui module(s) no shipped module imports — delete them or wire them:"
            f"\n  {chr(10).join(orphans)}"
        )

    def test_the_card_exemption_is_earned_by_a_loader(self) -> None:
        # The exemption above is only honest while the dynamic loader exists.
        for loader in CARD_LOADERS:
            source = (REPO_ROOT / loader).read_text(encoding="utf-8")
            assert "importlib.import_module" in source, loader
            assert f'"{CARD_PREFIX}{{' in source, loader
        cards = [name for name in UI_MODULES if name.startswith(CARD_PREFIX)]
        assert len(cards) >= 20, cards
