"""Tests for the repo-root ``.pyw`` launchers' best-effort error dialogs.

Plan iteration 7, item A3 (audit A5): ``File_Reorganizer.pyw`` (two handlers)
and ``Tag_Field_Updater.pyw`` (one) wrapped their error dialog in
``except Exception: pass``. The Tk fallback *around* the error dialog failing
meant the original failure vanished completely - no dialog, no log, no trace.

The ``.pyw`` files are not importable as modules (their body sits under an
``if __name__ == "__main__":`` guard, and the extension is not importable), so
these tests ``exec`` the shipped source with ``__name__`` set to
``"__main__"``. That exercises the real file as written rather than a
re-implementation, so a future edit that drops the ``logger.exception`` call
fails here.

Locks:
1. A failing dialog still logs at ``ERROR`` with a traceback and does not
   propagate out of the launcher.
2. A *working* dialog logs nothing - the handlers must not add noise to the
   normal path.
3. Both handler branches are exercised: the generic-exception branch in both
   launchers, and the ``ImportError`` branch that only
   ``File_Reorganizer.pyw`` has.
4. Every root ``.pyw`` runs the pre-flight guard before its first tool import
   (AGENTS.md "Startup Pre-Flight Guard (Do Not Disable)").

Changed in 1.1.0: added ``TestEveryLauncherRunsThePreflightGuard``, the lock for
that mandatory guard, after 24 of 28 launchers were found to be missing it.
"""

from __future__ import annotations

import ast
import logging
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# (launcher file name, the module the launcher imports its entry point from)
LAUNCHERS: tuple[tuple[str, str], ...] = (
    ("File_Reorganizer.pyw", "file_reorganizer"),
    ("Tag_Field_Updater.pyw", "tag_field_updater"),
)

STARTUP_BRANCH = "startup-error dialog"
IMPORT_BRANCH = "import-error dialog"


def launcher_sources() -> tuple[tuple[Path, str], ...]:
    """Return each launcher's path and source text."""
    return tuple(
        (REPO_ROOT / name, (REPO_ROOT / name).read_text(encoding="utf-8"))
        for name, _ in LAUNCHERS
    )


def _run_launcher(
    monkeypatch: pytest.MonkeyPatch,
    launcher: str,
    tool_module: str,
    import_error: bool,
    dialog_raises: bool,
) -> None:
    """Execute a ``.pyw`` launcher end to end with the failure injected.

    Args:
        monkeypatch: pytest patcher, reverted after the test.
        launcher: File name of the launcher at the repo root.
        tool_module: The module the launcher imports its entry point from.
        import_error: Make the import fail, reaching the ``ImportError``
            branch, instead of making the entry point raise.
        dialog_raises: Make ``messagebox.showerror`` raise, simulating the
            broken Tk that the old silent ``pass`` swallowed.

    Raises:
        Nothing by design; any escaping exception fails the calling test.
    """
    import tkinter
    from tkinter import messagebox

    monkeypatch.setattr(tkinter, "Tk", MagicMock())

    if dialog_raises:

        def _explode(*_args: Any, **_kwargs: Any) -> None:
            raise RuntimeError("tk is broken")

        monkeypatch.setattr(messagebox, "showerror", _explode)
    else:
        monkeypatch.setattr(messagebox, "showerror", MagicMock())

    if import_error:
        # A None entry makes `from <tool_module> import main` raise ImportError.
        monkeypatch.setitem(sys.modules, tool_module, None)
    else:
        failing = types.ModuleType(tool_module)

        def _boom() -> None:
            raise RuntimeError("startup exploded")

        failing.main = _boom  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, tool_module, failing)

    path = REPO_ROOT / launcher
    namespace: dict[str, Any] = {"__name__": "__main__", "__file__": str(path)}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)


@pytest.mark.parametrize(("launcher", "tool_module"), LAUNCHERS)
class TestGenericStartupFailureIsWitnessed:
    """The entry point raises, the dialog raises, the launcher stays quiet
    to the user but loud in the log."""

    def test_dialog_failure_is_logged_and_not_propagated(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        launcher: str,
        tool_module: str,
    ) -> None:
        """Both launchers: a broken dialog must not hide the startup error."""
        with caplog.at_level(logging.ERROR):
            _run_launcher(
                monkeypatch,
                launcher,
                tool_module,
                import_error=False,
                dialog_raises=True,
            )

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, (
            f"{launcher}: the failing error dialog was swallowed silently; no "
            "ERROR record reached the log the launcher configures"
        )
        assert any(STARTUP_BRANCH in r.getMessage() for r in errors), (
            f"{launcher}: unexpected message {[r.getMessage() for r in errors]}"
        )
        assert any(r.exc_info is not None for r in errors), (
            f"{launcher}: the witness must carry the dialog-failure traceback"
        )

    def test_working_dialog_logs_no_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        launcher: str,
        tool_module: str,
    ) -> None:
        """When ``showerror`` succeeds, nothing is logged at ERROR."""
        with caplog.at_level(logging.ERROR):
            _run_launcher(
                monkeypatch,
                launcher,
                tool_module,
                import_error=False,
                dialog_raises=False,
            )

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
            f"{launcher}: a successful dialog must not log an error: "
            f"{[r.getMessage() for r in caplog.records]}"
        )


class TestFileReorganizerImportBranch:
    """``File_Reorganizer.pyw`` has a second, ImportError-specific handler."""

    def test_import_failure_dialog_is_witnessed(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The import-error dialog failing must still be logged."""
        with caplog.at_level(logging.ERROR):
            _run_launcher(
                monkeypatch,
                "File_Reorganizer.pyw",
                "file_reorganizer",
                import_error=True,
                dialog_raises=True,
            )

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errors, "the failing import-error dialog was swallowed silently"
        assert any(IMPORT_BRANCH in r.getMessage() for r in errors), (
            f"unexpected message {[r.getMessage() for r in errors]}"
        )
        assert any(r.exc_info is not None for r in errors)

    def test_import_failure_working_dialog_logs_no_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A successful import-error dialog stays silent."""
        with caplog.at_level(logging.ERROR):
            _run_launcher(
                monkeypatch,
                "File_Reorganizer.pyw",
                "file_reorganizer",
                import_error=True,
                dialog_raises=False,
            )

        assert not [r for r in caplog.records if r.levelno >= logging.ERROR], (
            f"a successful dialog must not log an error: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    def test_import_error_is_not_masked_by_the_generic_branch(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """``ImportError`` must reach its own handler, not the generic one."""
        with caplog.at_level(logging.ERROR):
            _run_launcher(
                monkeypatch,
                "File_Reorganizer.pyw",
                "file_reorganizer",
                import_error=True,
                dialog_raises=True,
            )

        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        messages = [r.getMessage() for r in errors]
        assert any(IMPORT_BRANCH in m for m in messages), messages
        assert not any(STARTUP_BRANCH in m for m in messages), (
            f"the ImportError was handled by the generic branch instead: {messages}"
        )


class TestLauncherSourcesHaveNoSilentHandler:
    """Static guards so the old pattern cannot reappear unnoticed.

    The bare-``pass`` sweep covers **every** root ``.pyw``, not just the two
    this item fixed, because that is the invariant A3 asks for and it is free.
    The behavioural tests above stay scoped to the handlers this item changed;
    a *new* launcher copying the old boilerplate is caught here instead.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def all_launchers() -> tuple[tuple[Path, str], ...]:
        """Every root ``.pyw`` launcher with its source text."""
        sources = tuple(
            (path, path.read_text(encoding="utf-8"))
            for path in sorted(REPO_ROOT.glob("*.pyw"))
        )
        # Non-vacuity: a glob that matched nothing would pass silently.
        assert len(sources) >= 20, (
            f"expected the full launcher set, found only {len(sources)}; "
            "the sweep would pass vacuously"
        )
        return sources

    def test_no_silent_pass_in_any_launcher(
        self, all_launchers: tuple[tuple[Path, str], ...]
    ) -> None:
        """No launcher may contain a bare ``pass`` swallow."""
        offenders = [
            f"{path.name}:{index + 1}"
            for path, source in all_launchers
            for index, line in enumerate(source.splitlines())
            if line.strip() == "pass"
        ]
        assert not offenders, (
            "a launcher error handler swallows silently again at: "
            + ", ".join(offenders)
        )

    def test_each_fixed_launcher_defines_and_uses_a_logger(self) -> None:
        """Each launcher this item touched builds a logger and uses it."""
        for path, source in launcher_sources():
            assert "logger = logging.getLogger(__name__)" in source, (
                f"{path.name} has no module logger"
            )
            assert "logger.exception(" in source, (
                f"{path.name} never calls logger.exception"
            )

    def test_cd_ripper_preload_failure_is_witnessed(self) -> None:
        """The discovered sixth site: a failed discid.dll preload.

        Found while implementing this item - the plan's premise that the rest
        of the suite was clean was false. A swallowed ``OSError`` here turns a
        wrong-architecture or corrupt DLL into an opaque downstream ``discid``
        failure with no traceable cause.
        """
        source = (REPO_ROOT / "CD_Ripper.pyw").read_text(encoding="utf-8")
        assert "logger = logging.getLogger(__name__)" in source
        assert "except OSError:" in source, "the narrow catch should be kept"
        assert "logger.debug(" in source, "the preload failure must be witnessed"
        assert not any(line.strip() == "pass" for line in source.splitlines()), (
            "CD_Ripper.pyw went back to a silent pass"
        )


#: Modules a launcher may import *before* the guard: the standard library, plus
#: the shared namespace the guard itself is imported from.
_PRE_GUARD_ALLOWED: frozenset[str] = frozenset(sys.stdlib_module_names) | {
    "audio_suite_shared"
}


def _root_module(node: ast.Import | ast.ImportFrom) -> str:
    """Return the top-level module name an import statement pulls in."""
    if isinstance(node, ast.Import):
        return node.names[0].name.split(".")[0]
    return (node.module or "").split(".")[0]


def _guard_call_line(tree: ast.Module) -> int | None:
    """Line of the first ``guard_or_exit(...)`` call, or ``None``."""
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "guard_or_exit"
    ]
    return min(lines) if lines else None


def _first_tool_import_line(tree: ast.Module) -> int | None:
    """Line of the first import that is neither stdlib nor shared, or ``None``.

    A tool import is what the guard has to run *before*: importing a tool's
    own package on a syntax error is exactly the opaque-traceback failure the
    guard exists to prevent.
    """
    lines = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        and _root_module(node) not in _PRE_GUARD_ALLOWED
    ]
    return min(lines) if lines else None


class TestEveryLauncherRunsThePreflightGuard:
    """AGENTS.md "Startup Pre-Flight Guard (Do Not Disable)".

    Static (AST) rather than behavioural on purpose: executing 28 shipped
    launchers would build 28 real GUIs.  The ordering rule is the substance -
    a guard that fires after the tool import cannot catch a broken import
    chain - so it is asserted directly instead of by side effect.
    """

    @staticmethod
    @pytest.fixture(scope="class")
    def launcher_trees() -> tuple[tuple[Path, ast.Module], ...]:
        """Every root ``.pyw`` launcher with its parsed syntax tree."""
        trees = tuple(
            (
                path,
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
            )
            for path in sorted(REPO_ROOT.glob("*.pyw"))
        )
        # Non-vacuity: a glob that matched nothing would pass silently.
        assert len(trees) >= 20, (
            f"expected the full launcher set, found only {len(trees)}; "
            "the guard sweep would pass vacuously"
        )
        return trees

    def test_guard_runs_before_the_first_tool_import(
        self, launcher_trees: tuple[tuple[Path, ast.Module], ...]
    ) -> None:
        """Every launcher calls the guard before it imports any tool module."""
        violations: list[str] = []
        for path, tree in launcher_trees:
            guard_line = _guard_call_line(tree)
            if guard_line is None:
                violations.append(f"{path.name}: no guard_or_exit(...) call")
                continue
            tool_line = _first_tool_import_line(tree)
            if tool_line is not None and tool_line < guard_line:
                violations.append(
                    f"{path.name}: tool import on line {tool_line} precedes the "
                    f"guard on line {guard_line}"
                )
        assert not violations, (
            "launchers missing (or mis-ordering) the pre-flight guard: "
            + "; ".join(violations)
        )

    def test_guard_comes_from_the_shared_preflight_module(
        self, launcher_trees: tuple[tuple[Path, ast.Module], ...]
    ) -> None:
        """The guard is the shared one, not a re-implementation."""
        violations: list[str] = []
        for path, tree in launcher_trees:
            imported = any(
                isinstance(node, ast.ImportFrom)
                and node.module == "audio_suite_shared.preflight"
                and any(alias.name == "guard_or_exit" for alias in node.names)
                for node in ast.walk(tree)
            )
            if not imported:
                violations.append(path.name)
        assert not violations, (
            "launchers importing the guard from somewhere else: "
            + ", ".join(violations)
        )
