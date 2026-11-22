"""Lock: the Tk-thread drain loop has one implementation.

``audio_suite_shared.event_pump.pump_events`` owns the loop that takes every
message a worker queued, renders it on the Tk thread and re-arms while the run
is live.  Twelve windows call it; four of them wrote it by hand until 2.9.0 -
``while True`` / ``get_nowait()`` / ``queue.Empty`` inside a
``_drain_ui_updates`` method - and each copy re-learned the same trap: a
completion queued between the last drain and the liveness check was stranded
with nothing left to pick it up (B2).  The gate cannot see a fifth copy, because
a hand-written drain is ordinary, valid Python that every check passes.

So this lock reads the shipped runtime and fails when a module that imports Tk
consumes a queue itself: taking a message off a queue on the Tk thread is the
pump's job, and a window keeps only its ``_dispatch_ui_message``.  The rule is
narrow on purpose.  ``get_nowait`` is the non-blocking primitive a poller
needs; a ``queue.Empty`` handler with no read, or a blocking ``get`` on a worker
thread, is a different thing and is not what this lock is about.

``ALLOWLIST`` freezes the remaining copies with the reason they still exist, and
every entry must still trip the rule - a converged module that kept its entry
would pre-approve the next copy.

A window does not own the wrapper around the pump either.  ``SuiteApp`` holds
``_start_worker`` (the per-run queue and its daemon thread) and
``_poll_ui_updates`` (the ``pump_events`` call), so a tool supplies only
``_dispatch_ui_message``; the second rule here fails if any module outside the
shell defines one of those two methods, which is how the four adopters had
carried four byte-identical copies of it.

Changed in 2.9.0: new lock, after the four SuiteApp windows' drain loops became
``pump_events`` calls and their dead ``_poll_id`` was cut (D29, D30).
Changed in 2.9.0: the second rule, for the wrapper the shell now owns (D31).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories that are not the shipped runtime or hold build output.
SKIPPED_DIRS = frozenset({".git", ".venv", "__pycache__", "build", "dist", "docs"})

#: The one module allowed to take a message off a queue: it *is* the loop.
THE_PUMP = "audio_suite_shared/event_pump.py"

#: The call that consumes a worker's queue without blocking the Tk thread.
DRAIN_CALL = "get_nowait"

#: The shell that owns the worker hand-off around the pump.
SHELL = "audio_suite_shared/suite_app.py"

#: The methods that hand-off consists of.  A tool supplies ``_dispatch_ui_message``
#: and nothing else.
SHELL_METHODS: tuple[str, ...] = ("_start_worker", "_poll_ui_updates")

#: Modules that still drain a queue on the Tk thread, with the reason.
ALLOWLIST: dict[str, str] = {
    "mood_analysis_batch_tagger/app.py": (
        "The batch engine publishes on this queue and the run ends on the "
        "engine's own 'done' message, not on a worker thread's lifetime: the "
        "window keeps no thread handle to test, so pump_events' is_running has "
        "nothing to read, and the 'done' handler renders the completion and "
        "closes the window from inside the drain.  Migrating it means giving "
        "the engine a thread handle first (D20, D29)."
    ),
    "plugins/example_plugin/window.py": (
        "The example plugin is the documented teaching case for the queue "
        "protocol (AGENTS.md, GUI Callback Contract - D136) and it is not part "
        "of the suite build: one run delivers exactly one result, so there is "
        "no batch to drain."
    ),
}


def _source_files() -> list[Path]:
    """Return every first-party module except test modules.

    Returns:
        Sorted ``.py``/``.pyw`` paths outside :data:`SKIPPED_DIRS`.
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


def _imports_tkinter(tree: ast.AST) -> bool:
    """Whether *tree* imports Tk, in either of the two forms a window uses.

    Args:
        tree: A parsed module.

    Returns:
        True when the module imports ``tkinter`` or something inside it.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(
                alias.name == "tkinter" or alias.name.startswith("tkinter.")
                for alias in node.names
            ):
                return True
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "tkinter" or module.startswith("tkinter."):
                return True
    return False


def _drain_lines(source: str, name: str = "<source>") -> list[int]:
    """Return the lines where *source* takes a message off a queue itself.

    A module that does not import Tk has no Tk thread to drain, so its queue
    reads are its own business (a CLI's producer loop, a worker's slot queue).

    Args:
        source: The module's text.
        name: The filename to report a syntax error against.

    Returns:
        Sorted line numbers of the module's ``get_nowait`` calls.
    """
    tree = ast.parse(source, filename=name)
    if not _imports_tkinter(tree):
        return []
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == DRAIN_CALL
    )


def _scan() -> dict[str, list[int]]:
    """Return every module that drains a queue on the Tk thread.

    Returns:
        Mapping of repository-relative path to the lines that drain.
    """
    found: dict[str, list[int]] = {}
    for path in _source_files():
        lines = _drain_lines(path.read_text(encoding="utf-8"), str(path))
        if lines:
            found[path.relative_to(REPO_ROOT).as_posix()] = lines
    return found


DRAINS = _scan()


def _shell_method_defs(source: str, name: str = "<source>") -> list[tuple[str, int]]:
    """Return the shell-owned methods *source* defines for itself.

    Args:
        source: The module's text.
        name: The filename to report a syntax error against.

    Returns:
        ``(method name, line)`` pairs, in file order.
    """
    tree = ast.parse(source, filename=name)
    found = [
        (node.name, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in SHELL_METHODS
    ]
    return sorted(found, key=lambda entry: entry[1])


def _scan_shell_methods() -> dict[str, list[tuple[str, int]]]:
    """Return every module that defines a shell-owned hand-off method.

    Returns:
        Mapping of repository-relative path to its ``(method, line)`` pairs.
    """
    found: dict[str, list[tuple[str, int]]] = {}
    for path in _source_files():
        defs = _shell_method_defs(path.read_text(encoding="utf-8"), str(path))
        if defs:
            found[path.relative_to(REPO_ROOT).as_posix()] = defs
    return found


SHELL_METHOD_DEFS = _scan_shell_methods()


class TestTheScanIsReal:
    """A scan that found nothing would pass the rule below vacuously."""

    def test_the_tree_is_discovered(self) -> None:
        assert len(_source_files()) >= 500, len(_source_files())

    def test_the_pump_is_scanned_and_still_drains(self) -> None:
        # The exclusion below is only honest while the pump is the thing that
        # drains: a rule whose excluded module stopped tripping it is dead.
        assert DRAINS.get(THE_PUMP), (
            "audio_suite_shared/event_pump.py no longer takes a message off a "
            "queue, so excluding it from the rule below proves nothing"
        )


class TestTheDrainLoopHasOneHome:
    def test_no_tk_module_drains_a_queue_itself(self) -> None:
        offenders = sorted(
            f"{module}:{line}"
            for module, lines in DRAINS.items()
            if module != THE_PUMP and module not in ALLOWLIST
            for line in lines
        )
        assert not offenders, (
            "module(s) take a message off a queue on the Tk thread — call "
            "audio_suite_shared.event_pump.pump_events and keep only a "
            "_dispatch_ui_message:\n  " + "\n  ".join(offenders)
        )


class TestTheAllowlistIsLoadBearing:
    def test_every_entry_still_trips_the_rule(self) -> None:
        stale = sorted(name for name in ALLOWLIST if not DRAINS.get(name))
        assert not stale, (
            "allowlist entries that no longer drain a queue (drop them, or they "
            "pre-approve the next copy):\n  " + "\n  ".join(stale)
        )

    def test_every_entry_carries_a_reason(self) -> None:
        thin = sorted(name for name, reason in ALLOWLIST.items() if len(reason) < 80)
        assert not thin, f"allowlist entries with no real reason: {thin}"


class TestTheShellOwnsTheHandOff:
    def test_only_the_shell_defines_the_wrapper(self) -> None:
        offenders = sorted(
            f"{module}:{line} {method}"
            for module, defs in SHELL_METHOD_DEFS.items()
            if module != SHELL
            for method, line in defs
        )
        assert not offenders, (
            "module(s) define a worker hand-off the shell already owns - call "
            "SuiteApp._start_worker and supply only a _dispatch_ui_message:\n  "
            + "\n  ".join(offenders)
        )

    def test_the_shell_still_defines_both(self) -> None:
        defined = {method for method, _line in SHELL_METHOD_DEFS.get(SHELL, [])}
        assert defined == set(SHELL_METHODS), (
            f"{SHELL} no longer defines {sorted(set(SHELL_METHODS) - defined)}, "
            "so the rule above proves nothing"
        )

    def test_the_detector_notices_a_window_wrapper(self) -> None:
        source = (
            "class Window:\n"
            "    def _start_worker(self, target: object) -> None:\n"
            "        pass\n"
            "\n"
            "    def _dispatch_ui_message(self, message: object) -> None:\n"
            "        pass\n"
        )

        assert _shell_method_defs(source) == [("_start_worker", 2)]


class TestTheDetectorCanFail:
    """The rule is a parse, so it needs a positive and a negative control."""

    def test_a_hand_written_drain_is_noticed(self) -> None:
        source = (
            "import queue\n"
            "import tkinter as tk\n"
            "\n"
            "\n"
            "def poll(app: object) -> None:\n"
            "    while True:\n"
            "        try:\n"
            "            item = app.events.get_nowait()\n"
            "        except queue.Empty:\n"
            "            return\n"
            "        app.render(item)\n"
        )

        assert _drain_lines(source) == [8]

    def test_a_queue_read_outside_a_window_is_not_the_tk_loop(self) -> None:
        source = (
            "import queue\n"
            "\n"
            "\n"
            "def drain(events: queue.SimpleQueue[object]) -> object:\n"
            "    return events.get_nowait()\n"
        )

        assert _drain_lines(source) == []
