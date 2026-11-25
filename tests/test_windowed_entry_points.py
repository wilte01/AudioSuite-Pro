"""Every windowed entry point installs the no-window proxy before its window.

``audio_suite_shared.logging_setup.configure_logging`` installs pydub's
no-window-FFmpeg proxy, and that function is the one startup seam a windowed
process can always reach.  This module is the census behind that claim: it
finds every entry point that can put a window on screen - the top-level
``.pyw`` launchers, the plugin launcher, the ``*/main.pyw`` package stubs and
the ``__main__.py`` packages that build a Tk root - and fails any of them that
does not call the seam before it creates its window.

The audit behind this lock found three windows that never called
``bootstrap_tool_app`` at all (the Master Driver, the Undo Tag Edits window and
plugin windows), so each of them is named as a known bypass: the lock cannot
silently stop covering the gap it was written for.

Changed in 2.9.0: new lock, closing the bypass the console-window audit found.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Windows that bypassed ``bootstrap_tool_app`` when the console-window defect
#: was fixed.  They are why the proxy lives at ``configure_logging``.
KNOWN_BYPASSES = (
    "Master_Driver.pyw",
    "Undo_Tag_Edits.pyw",
    "plugins/example_plugin/Example_Plugin.pyw",
)


def _read(path: Path) -> str:
    """Return *path*'s text."""
    return path.read_text(encoding="utf-8")


def _launchers() -> list[Path]:
    """Top-level ``.pyw`` launchers: one per tool window."""
    return sorted(REPO_ROOT.glob("*.pyw"))


def _plugin_launchers() -> list[Path]:
    """Plugin launchers, which live one level below the suite root."""
    return sorted(REPO_ROOT.glob("plugins/*/*.pyw"))


def _package_stubs() -> list[Path]:
    """``<package>/main.pyw`` stubs that build the package's own window."""
    return sorted(REPO_ROOT.glob("*/main.pyw"))


def _package_mains() -> list[Path]:
    """``<package>/__main__.py`` files that build a Tk root."""
    return sorted(
        path for path in REPO_ROOT.glob("*/__main__.py") if "tk.Tk(" in _read(path)
    )


def _entry_points() -> list[Path]:
    """Every file that can put a window on screen."""
    return _launchers() + _plugin_launchers() + _package_stubs() + _package_mains()


def _parse(path: Path) -> ast.Module:
    """Return *path*'s syntax tree."""
    return ast.parse(_read(path), filename=str(path))


def _calls(tree: ast.Module, name: str) -> list[ast.Call]:
    """Return every call to *name* in *tree*, in source order.

    Matches both a bare ``name(...)`` and an attribute ``x.name(...)``, so a
    module that imports the seam directly and one that reaches it through its
    module are covered alike.
    """
    found = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == name)
            or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
        )
    ]
    return sorted(found, key=lambda call: call.lineno)


def _tk_roots(tree: ast.Module) -> list[ast.Call]:
    """Return the file's own ``tk.Tk()`` calls, in source order."""
    return [
        call
        for call in _calls(tree, "Tk")
        if isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "tk"
    ]


class TestTheCensus:
    """The scan covers what it claims to, so it cannot pass vacuously."""

    def test_every_category_is_populated(self) -> None:
        assert len(_launchers()) >= 33, "the top-level launcher census lost files"
        assert len(_plugin_launchers()) >= 1, "the plugin launcher is not covered"
        assert len(_package_stubs()) >= 5, "the package stubs are not covered"
        assert len(_package_mains()) >= 2, "the Tk package mains are not covered"

    def test_the_known_bypasses_are_covered(self) -> None:
        covered = {path.relative_to(REPO_ROOT).as_posix() for path in _entry_points()}
        missing = [bypass for bypass in KNOWN_BYPASSES if bypass not in covered]
        assert not missing, f"the census stopped covering {missing}"

    def test_no_entry_point_is_counted_twice(self) -> None:
        entry_points = _entry_points()
        assert len(entry_points) == len(set(entry_points))


@pytest.mark.parametrize(
    "path",
    _entry_points(),
    ids=lambda path: path.relative_to(REPO_ROOT).as_posix(),
)
class TestEveryWindowedEntryPointReachesTheSeam:
    """``configure_logging`` runs once, early, in every windowed process."""

    def test_calls_configure_logging_once(self, path: Path) -> None:
        calls = _calls(_parse(path), "configure_logging")
        assert len(calls) == 1, (
            f"{path.relative_to(REPO_ROOT).as_posix()} must call "
            "configure_logging exactly once, before its window exists; it "
            f"called it {len(calls)} times. That call is what installs the "
            "pydub no-window proxy."
        )

    def test_names_the_program_it_configures(self, path: Path) -> None:
        (call,) = _calls(_parse(path), "configure_logging")
        assert call.args, "configure_logging needs its program name"
        program = call.args[0]
        assert isinstance(program, ast.Constant) and isinstance(program.value, str)
        assert program.value, "the program name must not be empty"

    def test_runs_before_the_window_entry_is_invoked(self, path: Path) -> None:
        tree = _parse(path)
        (seam,) = _calls(tree, "configure_logging")
        window_calls = _tk_roots(tree) + [
            call for call in _calls(tree, "main") if isinstance(call.func, ast.Name)
        ]
        assert window_calls, (
            f"{path.relative_to(REPO_ROOT).as_posix()} builds no window and "
            "calls no window entry, so it does not belong in this census"
        )
        first_window_line = min(call.lineno for call in window_calls)
        assert seam.lineno < first_window_line, (
            f"{path.relative_to(REPO_ROOT).as_posix()} builds its window before "
            "configure_logging runs, so the pydub proxy is not installed yet"
        )
