"""Tests for the root ``conftest.py`` display handling (plan item B4).

B4 replaced a headless run that marked **every** collected test skipped — a run
that could report thousands of skips and still exit 0.  These tests pin the
replacement: a bounded, attributable, and loud skip.

The headless simulation runs in a **subprocess** against a byte-for-byte copy of
the real ``conftest.py``, with ``tk.Tk`` patched to raise ``tk.TclError``.  A
subprocess is required rather than an in-process fixture because the behaviour
under scrutiny is session-level (``pytest_configure`` →
``pytest_collection_modifyitems`` → ``pytest_terminal_summary``), which cannot
be re-entered inside a live session.

Changed in 2.9.0: ``TestSuiteConfigWriteGuard`` holds the session's guard on
``audio_suite_shared.suite_config._save``, so a test can no longer rewrite the
developer's real ``audio_suite_config.json`` (the last directory included) -
nor save a hidden window's ``1x1+X+Y`` geometry into it, which the session's
last act now compares and refuses.
"""

from __future__ import annotations

import ast
import gc
import importlib
import importlib.util
import json
import os
import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Injected into the simulated run: a host where no display can be opened.
HEADLESS_PLUGIN = '''\
"""Simulate a headless host by making tk.Tk() fail."""

import tkinter as tk


def _no_display(*_args, **_kwargs):
    raise tk.TclError("no display name and no $DISPLAY environment variable")


tk.Tk = _no_display
'''

#: A stand-in for the display-dependent and display-independent halves of the
#: suite, so the simulation exercises both sides of the decision.
SAMPLE_TESTS = """\
import pytest


def test_plain_logic_passes_without_a_display():
    assert 2 + 2 == 4


def test_needs_the_shared_root(root):
    assert root is not None


def test_needs_the_shared_tk_root(tk_root):
    assert tk_root is not None


@pytest.mark.gui
def test_declares_its_own_display_requirement():
    raise AssertionError("a gui-marked test must never run headless")


class TestClassLevelMarker:
    @pytest.mark.gui
    def test_inherits_the_class_marker(self):
        raise AssertionError("a gui-marked class must never run headless")
"""

#: Reproduces the Tk ``Variable.__del__`` warning end-to-end.  Test A drops a
#: ``Variable`` into a reference cycle (so it is reachable only from the cycle
#: and is collectable only by the GC); test B then forces a GC cycle from a
#: worker thread.  Without the root conftest's main-thread collection between
#: tests, the Variable's finalizer runs on that worker thread and raises
#: ``RuntimeError: main thread is not in main loop`` as an unraisable exception
#: (verified with a one-off script: 1 unraisable on the worker, 0 after a
#: main-thread ``gc.collect()`).
TK_GC_TESTS = """\
import gc
import threading
import tkinter


def test_a_drops_a_variable_into_an_unreachable_cycle(root):
    variable = tkinter.Variable(master=root)
    cycle = [variable]
    cycle.append(cycle)
    del variable, cycle


def test_b_collects_from_a_worker_thread():
    thread = threading.Thread(target=gc.collect)
    thread.start()
    thread.join()
"""

#: One leaking test among two clean neighbours.  The leaking one must fail at
#: its own teardown, and the test after it must still see an empty root because
#: the lock destroys what it refuses to forgive.
SHARED_ROOT_TESTS = """\
import tkinter as tk


def test_zero_destroys_what_it_builds(root):
    frame = tk.Frame(root)
    frame.pack()
    frame.destroy()


def test_first_leaves_a_frame_on_the_root(root):
    tk.Frame(root).pack()


def test_second_still_sees_a_clean_root(root):
    assert [w for w in root.winfo_children() if isinstance(w, tk.Frame)] == []
"""

#: A module that declares it builds on the shared root: its leftovers are the
#: lock's to destroy, and they must not fail it.
SHARED_ROOT_DECLARED = """\
import tkinter as tk

import pytest

pytestmark = pytest.mark.usefixtures("clean_shared_root")


def test_declared_module_leaves_a_frame(root):
    tk.Frame(root).pack()
"""

#: Mirrors the real ``[tool.pytest.ini_options]`` closely enough to prove the
#: ``gui`` marker is registered and that ``--strict-markers`` accepts it.
PYTEST_INI = """\
[pytest]
addopts = --strict-markers -ra
markers =
    integration: requires ffmpeg
    hardware: requires physical hardware
    gui: requires a graphical display
"""


def _load_root_conftest() -> ModuleType:
    """Import the repository's root ``conftest.py`` as a standalone module.

    Args:
        None.

    Returns:
        The loaded module, so the pure helpers can be unit-tested directly
        without re-entering a live pytest session.
    """
    path = REPO_ROOT / "conftest.py"
    spec = importlib.util.spec_from_file_location("audiosuite_root_conftest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


root_conftest = _load_root_conftest()


class _StubItem:
    """Minimal stand-in for a collected ``pytest.Item``."""

    def __init__(self, fixturenames: tuple[str, ...] = (), markers: str = ()) -> None:
        self.fixturenames = list(fixturenames)
        self._markers = list(markers)

    def iter_markers(self):
        return [type("M", (), {"name": name})() for name in self._markers]


def _display_present() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


_OUTCOMES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR", "XFAIL", "XPASS"})


def _outcome(line: str) -> str:
    """Extract the outcome token from a ``-v`` result line.

    Args:
        line: A terminal line such as
            ``test_sample.py::test_x SKIPPED (No display...) [ 40%]``.

    Returns:
        The outcome token, e.g. ``SKIPPED``.

    Raises:
        AssertionError: When no known outcome token is present.
    """
    for token in line.split()[1:]:
        if token in _OUTCOMES:
            return token
    raise AssertionError(f"no outcome token in {line!r}")


def _outcome_line(outcomes, test_name: str) -> str:
    """Return the ``-v`` result line for *test_name* from a simulated run.

    Args:
        outcomes:  The ``RunResult`` of the simulated subprocess run.
        test_name: The bare test function name to look for.

    Returns:
        The full terminal line, e.g.
        ``test_sample.py::test_plain_logic_passes_without_a_display PASSED``.

    Raises:
        AssertionError: When no line mentions the test, which would mean the
            test was not collected at all (a silent harness failure).
    """
    for line in outcomes.stdout.lines:
        if f"::{test_name}" in line:
            return line.rstrip()
    raise AssertionError(f"no -v result line for {test_name}")


@pytest.fixture()
def headless_run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """Run a simulated headless session against the real conftest.

    Args:
        pytester:  The pytester fixture (a tmp dir + subprocess runner).
        monkeypatch: Used to expose the simulated-run plugin on ``PYTHONPATH``.

    Yields:
        The ``pytester`` instance, already populated with a copy of the real
        conftest, the headless plugin and the sample tests, plus the recorded
        run outcomes.
    """
    shutil.copyfile(REPO_ROOT / "conftest.py", pytester.path / "conftest.py")
    (pytester.path / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
    (pytester.path / "headless_host.py").write_text(HEADLESS_PLUGIN, encoding="utf-8")
    (pytester.path / "test_sample.py").write_text(SAMPLE_TESTS, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    # The skip reason contains a non-ASCII em dash, so the child must write
    # UTF-8 or pytester's output capture fails to decode it on Windows.
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    outcomes = pytester.runpytest_subprocess(
        "-p", "headless_host", "-p", "no:cacheprovider", "-v"
    )
    yield pytester, outcomes


class TestRequiresDisplayDetection:
    """The bounded rule: only declared display-dependent tests are skipped."""

    def test_a_test_requesting_the_shared_root_needs_a_display(self) -> None:
        assert root_conftest.requires_display(_StubItem(fixturenames=("root",)))

    def test_a_test_requesting_the_shared_tk_root_needs_a_display(self) -> None:
        assert root_conftest.requires_display(_StubItem(fixturenames=("tk_root",)))

    def test_a_gui_marked_test_needs_a_display(self) -> None:
        assert root_conftest.requires_display(_StubItem(markers=("gui",)))

    def test_a_plain_test_does_not_need_a_display(self) -> None:
        assert not root_conftest.requires_display(_StubItem(fixturenames=("tmp_path",)))

    def test_an_unrelated_marker_is_not_treated_as_a_display_marker(self) -> None:
        assert not root_conftest.requires_display(_StubItem(markers=("integration",)))


class TestHeadlessRun:
    """End-to-end: the session must stay green and stay honest."""

    def test_the_session_still_exits_zero(self, headless_run) -> None:
        _pytester, outcomes = headless_run
        assert outcomes.ret == 0
        outcomes.assert_outcomes(passed=1, skipped=4, errors=0, failed=0)

    def test_a_non_gui_test_is_not_skipped(self, headless_run) -> None:
        """The regression this item exists to fix: the non-GUI majority of the
        suite must execute, not be hidden behind a display skip."""
        _pytester, outcomes = headless_run
        line = _outcome_line(outcomes, "test_plain_logic_passes_without_a_display")
        assert _outcome(line) == "PASSED"

    def test_every_display_dependent_test_is_skipped(self, headless_run) -> None:
        """Bounded from the other side: the two fixture requesters, the
        ``gui``-marked test and the class-marked test are all skipped."""
        _pytester, outcomes = headless_run
        for name in (
            "test_needs_the_shared_root",
            "test_needs_the_shared_tk_root",
            "test_declares_its_own_display_requirement",
            "test_inherits_the_class_marker",
        ):
            assert _outcome(_outcome_line(outcomes, name)) == "SKIPPED", name

    def test_every_display_skip_names_the_missing_display(self, headless_run) -> None:
        """Attributable: ``-ra`` groups skips by reason, and every group must
        carry the display reason (not an inherited, unattributed skip)."""
        _pytester, outcomes = headless_run
        groups = [
            line
            for line in outcomes.stdout.lines
            if line.startswith("SKIPPED") and "[" in line
        ]
        assert groups
        for group in groups:
            assert root_conftest.NO_DISPLAY_REASON in group

    def test_the_summary_states_gui_behaviour_was_not_verified(
        self, headless_run
    ) -> None:
        _pytester, outcomes = headless_run
        output = outcomes.stdout.str()
        assert root_conftest.SUMMARY_HEADING in output
        assert "GUI behaviour" in output
        assert "NOT VERIFIED" in output
        assert "Tk display available  : NO" in output

    def test_the_summary_reports_how_many_tests_the_display_cost(
        self, headless_run
    ) -> None:
        _pytester, outcomes = headless_run
        output = outcomes.stdout.str()
        assert "Tests skipped for display reasons : 4" in output
        assert "of 5 collected" in output

    def test_the_missing_display_raises_a_warning(self, headless_run) -> None:
        """A warning, not only skips, so it is a distinct class in CI logs.

        pytest writes the warnings summary to stderr, so that is where the
        warning must appear.
        """
        _pytester, outcomes = headless_run
        stderr = outcomes.stderr.str()
        assert "GuiDisplayUnavailableWarning" in stderr
        assert "cannot be verified" in stderr

    def test_the_warning_names_the_escape_hatch(self, headless_run) -> None:
        _pytester, outcomes = headless_run
        assert root_conftest.GUI_SKIP_ENV in outcomes.stderr.str()


class TestSafetyNet:
    """The retained session-wide skip must be explicit and must say so."""

    def test_the_safety_net_skips_everything_and_is_labelled(
        self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        shutil.copyfile(REPO_ROOT / "conftest.py", pytester.path / "conftest.py")
        (pytester.path / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
        (pytester.path / "headless_host.py").write_text(
            HEADLESS_PLUGIN, encoding="utf-8"
        )
        (pytester.path / "test_sample.py").write_text(SAMPLE_TESTS, encoding="utf-8")
        monkeypatch.setenv("PYTHONPATH", str(pytester.path))
        monkeypatch.setenv("PYTHONUTF8", "1")
        monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
        monkeypatch.setenv(root_conftest.GUI_SKIP_ENV, "all")

        outcomes = pytester.runpytest_subprocess(
            "-p", "headless_host", "-p", "no:cacheprovider"
        )

        outcomes.assert_outcomes(passed=0, skipped=5, errors=0, failed=0)
        output = outcomes.stdout.str()
        assert root_conftest.BLANKET_REASON in output
        assert "SAFETY NET ACTIVE" in output
        assert "proves nothing" in output

    def test_the_default_mode_is_bounded_not_blanket(self) -> None:
        assert os.environ.get(root_conftest.GUI_SKIP_ENV, "") != "all"


class TestSummaryFormatting:
    """The always-printed report, unit-tested for both host states."""

    def test_a_display_present_run_reports_gui_as_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(root_conftest, "_display_available", True)
        monkeypatch.setattr(root_conftest, "_display_skips", 0)
        report = "\n".join(root_conftest.format_display_summary())
        assert root_conftest.SUMMARY_HEADING in report
        assert "VERIFIED in this run" in report
        assert "NOT VERIFIED" not in report

    def test_a_headless_run_reports_gui_as_not_verified(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(root_conftest, "_display_available", False)
        monkeypatch.setattr(root_conftest, "_display_skips", 741)
        monkeypatch.setattr(root_conftest, "_collected", 7162)
        monkeypatch.setattr(root_conftest, "_blanket_mode", False)
        report = "\n".join(root_conftest.format_display_summary())
        assert "NOT VERIFIED in this run" in report
        assert "741 of 7162 collected" in report
        assert "SAFETY NET ACTIVE" not in report

    def test_the_summary_is_printed_even_with_a_display(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Always-printed, per the item's scope — not only on the sad path."""
        monkeypatch.setattr(root_conftest, "_display_available", True)
        written: list[str] = []

        class _Reporter:
            @staticmethod
            def write_line(line: str) -> None:
                written.append(line)

        root_conftest.pytest_terminal_summary(_Reporter(), 0, None)
        assert root_conftest.SUMMARY_HEADING in "\n".join(written)


def _live_conftest(config: pytest.Config) -> ModuleType:
    """Return the root conftest module **as pytest loaded it**.

    Deliberately not ``importlib.import_module("conftest")``: that can build a
    second, unconfigured module object whose ``_display_available`` is still the
    initial ``False``, which makes the display-present assertion below fail in a
    full-suite run while passing in isolation.  The plugin manager is the public
    API that reports which module actually participated in this session.

    Args:
        config: The active pytest config.

    Returns:
        The loaded root ``conftest`` module.

    Raises:
        AssertionError: When the root conftest is not registered exactly once.
    """
    target = (REPO_ROOT / "conftest.py").resolve()
    matches = [
        plugin
        for plugin in config.pluginmanager.get_plugins()
        if isinstance(plugin, ModuleType)
        and (REPO_ROOT / str(getattr(plugin, "__file__", ""))).resolve() == target
    ]
    assert len(matches) == 1, f"expected one loaded root conftest, got {matches}"
    return matches[0]


@pytest.mark.skipif(
    not _display_present(),
    reason=(
        "This case asserts the display-present branch of the report, which "
        "requires an actual Tk display on the host running the suite."
    ),
)
def test_the_live_session_reports_gui_as_verified(
    request: pytest.FixtureRequest,
) -> None:
    """With a display (the normal CI case) the report must claim verification.

    Asserted against the conftest module pytest actually loaded for this
    session, so this checks the report the developer really sees.  Skipped,
    with the constraint named, on a genuinely headless host — the same reason
    the plan forbids inheriting a blanket skip for.
    """
    live = _live_conftest(request.config)
    assert live._display_available is True
    report = "\n".join(live.format_display_summary())
    assert "VERIFIED in this run" in report
    assert "NOT VERIFIED" not in report
    assert live._display_skips == 0


def test_the_conftest_is_registered_as_a_session_plugin(
    request: pytest.FixtureRequest,
) -> None:
    """The hooks that implement the bounded skip must be active in *this*
    session, not merely present in the file."""
    live = _live_conftest(request.config)
    assert callable(live.pytest_collection_modifyitems)
    assert callable(live.pytest_terminal_summary)
    assert callable(live.pytest_configure)


def test_the_conftest_never_calls_pytest_skip() -> None:
    """A3 regression lock: a session-level ``pytest.skip()`` aborts the whole
    run with ``INTERNALERROR`` (exit code 3) instead of skipping anything.

    Checked over the AST rather than the raw text, because the conftest's own
    docstring must be able to *mention* the call it is forbidden to make.
    ``pytest.mark.skip(reason=...)`` is the marker factory and stays legal —
    only the imperative ``pytest.skip()`` / ``pytest.skipif()`` are banned.
    """
    tree = ast.parse((REPO_ROOT / "conftest.py").read_text(encoding="utf-8"))
    offenders = sorted(
        {
            _dotted_name(node.func)
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and _dotted_name(node.func).rsplit(".", 1)[-1] in {"skip", "skipif"}
            and not _dotted_name(node.func).endswith("mark.skip")
        }
    )
    assert not offenders, f"conftest.py must not call {offenders}"


def _dotted_name(func: ast.expr) -> str:
    """Return the dotted source path of a call target.

    Args:
        func: The ``ast.Call`` node's ``func`` expression.

    Returns:
        The reconstructed path, e.g. ``"pytest.mark.skip"`` for
        ``pytest.mark.skip(reason=...)``, or ``""`` if it is not a plain
        attribute/name chain.
    """
    parts: list[str] = []
    while isinstance(func, ast.Attribute):
        parts.append(func.attr)
        func = func.value
    if isinstance(func, ast.Name):
        parts.append(func.id)
    else:
        return ""
    return ".".join(reversed(parts))


def _is_autouse_fixture(node: ast.FunctionDef) -> bool:
    """Return True when *node* is decorated ``@pytest.fixture(autouse=True)``.

    Args:
        node: A function definition from the root conftest's AST.

    Returns:
        True for an autouse fixture decorator, False otherwise.
    """
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if _dotted_name(decorator.func) != "pytest.fixture":
            continue
        for keyword in decorator.keywords:
            if keyword.arg == "autouse" and keyword.value.value is True:
                return True
    return False


def _calls_gc_collect(node: ast.AST) -> bool:
    """Return True when *node*'s body calls ``gc.collect()``."""
    return any(
        isinstance(child, ast.Call) and _dotted_name(child.func) == "gc.collect"
        for child in ast.walk(node)
    )


@pytest.fixture()
def tk_gc_run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """Run the drop-a-Variable-then-collect-on-a-worker simulation.

    Args:
        pytester:   The pytester fixture (a tmp dir + subprocess runner).
        monkeypatch: Used to expose the simulated-run plugin on ``PYTHONPATH``.

    Yields:
        The ``pytester`` instance and the recorded run outcomes.
    """
    shutil.copyfile(REPO_ROOT / "conftest.py", pytester.path / "conftest.py")
    (pytester.path / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
    (pytester.path / "test_tk_gc.py").write_text(TK_GC_TESTS, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    outcomes = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-v")
    yield pytester, outcomes


class TestTkGarbageCollection:
    """Main-thread GC between tests keeps Tk finalizers off worker threads.

    ``tkinter.Variable.__del__`` calls back into the interpreter, which raises
    ``RuntimeError: main thread is not in main loop`` if the finalizer runs on a
    worker thread.  The root conftest collects dropped Tk objects on the main
    thread after every test so a later worker-threaded test cannot finalize one.
    """

    def test_an_autouse_fixture_collects_garbage_on_the_main_thread(self) -> None:
        """Structural lock: the seam the fix relies on must stay autouse.

        Without an autouse fixture every test's dropped ``Variable`` stays
        collectable until an arbitrary later GC cycle — which, for a
        worker-threaded audio test, is where the finalizer runs off the main
        thread.
        """
        tree = ast.parse((REPO_ROOT / "conftest.py").read_text(encoding="utf-8"))
        seams = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and _is_autouse_fixture(node)
            and _calls_gc_collect(node)
        ]
        assert seams, "conftest.py must keep an autouse fixture calling gc.collect()"

    def test_main_thread_collection_prevents_the_off_thread_finalizer(
        self, request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Mechanism lock: collecting on the main thread is what prevents it.

        Reproduces the exact failure in-process — a ``Variable`` dropped into a
        reference cycle, then a GC cycle run from a worker thread — and asserts
        the main-thread collection leaves nothing for the worker to finalize.
        """
        root = request.getfixturevalue("root")
        captured: list[object] = []
        monkeypatch.setattr(sys, "unraisablehook", captured.append)

        variable = tk.Variable(master=root)
        cycle: list[object] = [variable]
        cycle.append(cycle)
        del variable, cycle

        gc.collect()  # the seam under test: finalize on the main thread
        thread = threading.Thread(target=gc.collect)
        thread.start()
        thread.join()

        assert captured == [], (
            "a Tk Variable was finalized off the main thread: "
            f"{[getattr(u, 'exc_value', u) for u in captured]}"
        )

    @pytest.mark.skipif(
        not _display_present(),
        reason=(
            "The end-to-end reproduction needs a real Tk root in the child "
            "process; the shared-root fixture is display-dependent."
        ),
    )
    def test_the_seam_keeps_the_session_free_of_the_warning(self, tk_gc_run) -> None:
        """End-to-end: the shared conftest prevents the warning entirely.

        The child drops a ``Variable`` in one test and forces a worker-thread GC
        in the next; with the seam active the run must report no
        ``PytestUnraisableExceptionWarning``.
        """
        _pytester, outcomes = tk_gc_run
        outcomes.assert_outcomes(passed=2, errors=0, failed=0)
        combined = outcomes.stdout.str() + outcomes.stderr.str()
        assert "PytestUnraisableExceptionWarning" not in combined
        assert "main thread is not in main loop" not in combined


@pytest.fixture()
def shared_root_run(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch):
    """Run a child session with one test leaking a frame on the shared root.

    Args:
        pytester:   The pytester fixture (a tmp dir + subprocess runner).
        monkeypatch: Used to expose the copy of the conftest on ``PYTHONPATH``.

    Yields:
        The recorded run outcomes of the four-test child session.
    """
    shutil.copyfile(REPO_ROOT / "conftest.py", pytester.path / "conftest.py")
    (pytester.path / "pytest.ini").write_text(PYTEST_INI, encoding="utf-8")
    (pytester.path / "test_shared_root.py").write_text(
        SHARED_ROOT_TESTS, encoding="utf-8"
    )
    (pytester.path / "test_shared_root_declared.py").write_text(
        SHARED_ROOT_DECLARED, encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(pytester.path))
    monkeypatch.setenv("PYTHONUTF8", "1")
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    outcomes = pytester.runpytest_subprocess("-p", "no:cacheprovider", "-v")
    yield outcomes


class TestSharedRootCleanliness:
    """A test that leaves widgets on the shared root fails where it leaks.

    The Album Art Normalizer's and the Music Format Converter's Setup suites
    shipped leaking because the bare gate collected root ``tests/`` before the
    package directories: the contract test that counts a tool's title on the
    root ran before the leaks existed, and ``pytest album_art_normalizer
    tests/test_suite_app_contract.py`` — the other order — failed.  The lock
    fails the leaking test itself, so no collection order can hide it.
    """

    @pytest.mark.skipif(
        not _display_present(),
        reason=(
            "The simulation needs a real Tk root in the child process; the "
            "shared-root fixture is display-dependent."
        ),
    )
    def test_a_leaking_test_fails_at_its_own_teardown(self, shared_root_run) -> None:
        """The leak is an error on the test that made it, not on a later one."""
        outcomes = shared_root_run
        assert outcomes.ret != 0
        outcomes.assert_outcomes(passed=4, errors=1, failed=0)
        # A teardown error prints its own line after the test's PASSED line.
        lines = [
            line
            for line in outcomes.stdout.lines
            if "::test_first_leaves_a_frame_on_the_root " in line
        ]
        assert any(_outcome(line) == "ERROR" for line in lines), lines
        assert "left widgets on the session-scoped Tk root" in outcomes.stdout.str()

    @pytest.mark.skipif(
        not _display_present(),
        reason=(
            "The simulation needs a real Tk root in the child process; the "
            "shared-root fixture is display-dependent."
        ),
    )
    def test_a_test_that_destroys_what_it_builds_still_passes(
        self, shared_root_run
    ) -> None:
        """The lock is about leftovers, not about using the root at all."""
        outcomes = shared_root_run
        line = _outcome_line(outcomes, "test_zero_destroys_what_it_builds")
        assert _outcome(line) == "PASSED"

    @pytest.mark.skipif(
        not _display_present(),
        reason=(
            "The simulation needs a real Tk root in the child process; the "
            "shared-root fixture is display-dependent."
        ),
    )
    def test_a_declared_module_keeps_its_leftovers_without_failing(
        self, shared_root_run
    ) -> None:
        """Declaring the root is allowed; the lock still cleans up after it."""
        outcomes = shared_root_run
        line = _outcome_line(outcomes, "test_declared_module_leaves_a_frame")
        assert _outcome(line) == "PASSED"

    def test_the_leftovers_are_destroyed_before_the_failure(
        self, shared_root_run
    ) -> None:
        """One leak costs one test; it cannot poison every later walk."""
        outcomes = shared_root_run
        line = _outcome_line(outcomes, "test_second_still_sees_a_clean_root")
        assert _outcome(line) == "PASSED"


class TestSuiteConfigWriteGuard:
    """The session cannot rewrite the developer's real shared config.

    ``audio_suite_config.json`` sits beside the checkout and every
    ``suite_config.save_*`` call is a read-modify-write of the whole document,
    so one save aimed at it replaces the last directory, the palette, the font
    sizes and every window geometry.  The guard is installed by the root
    ``conftest.py``, whose fixtures a test cannot see from the inside, so the
    writer's identity is the seam this lock holds.
    """

    def test_the_shared_writer_is_guarded_for_the_session(self) -> None:
        """Structural lock: the installed writer refuses the live path.

        Without it, a test that saves a preference without redirecting
        ``CONFIG_PATH`` - the Master Driver's Mode pick and the Refinery
        launch both do - rewrites the file next to the checkout.
        """
        import audio_suite_shared.suite_config as suite_config

        writer = suite_config._save
        assert getattr(writer, "__name__", "") == "guarded_save", (
            "conftest.py must guard suite_config._save for the session"
        )

    def test_a_temp_redirect_keeps_the_real_save_behaviour(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request
    ) -> None:
        """The guard delegates: a test that redirects still saves and loads."""
        import audio_suite_shared.suite_config as suite_config

        target = tmp_path / "audio_suite_config.json"
        monkeypatch.setattr(suite_config, "CONFIG_PATH", target)
        monkeypatch.setattr(
            suite_config, "_LOCK_PATH", target.with_suffix(".json.lock")
        )
        suite_config._invalidate_cache()
        request.addfinalizer(suite_config._invalidate_cache)

        suite_config.save_last_directory(str(tmp_path / "music"))

        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["last_directory"] == str(tmp_path / "music")
        assert suite_config.load_last_directory() == str(tmp_path / "music")

    def test_the_teardown_redirect_aims_the_writer_at_a_scratch_file(
        self, monkeypatch: pytest.MonkeyPatch, request
    ) -> None:
        """Every window left open saves its geometry as the root is destroyed.

        That happens after the session fixture has restored the real writer, so
        ``pytest_unconfigure`` aims ``CONFIG_PATH`` at a scratch directory
        first.  Without it the last 70 saves of a full run land in the
        developer's file.
        """
        import audio_suite_shared.suite_config as suite_config

        live = suite_config.CONFIG_PATH
        monkeypatch.setattr(suite_config, "CONFIG_PATH", live)
        monkeypatch.setattr(suite_config, "_LOCK_PATH", suite_config._LOCK_PATH)
        request.addfinalizer(suite_config._invalidate_cache)

        root_conftest._redirect_suite_config_for_teardown()

        assert suite_config.CONFIG_PATH != live
        assert suite_config.CONFIG_PATH.parent != live.parent
        suite_config.save_value("geometry_probe", "800x600+0+0")
        saved = json.loads(suite_config.CONFIG_PATH.read_text(encoding="utf-8"))
        assert saved["geometry_probe"] == "800x600+0+0"

    def test_unconfigure_redirects_destroys_and_then_checks(self) -> None:
        """Structural lock: redirect, destroy, then prove nothing was saved."""
        tree = ast.parse((REPO_ROOT / "conftest.py").read_text(encoding="utf-8"))
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        positions: dict[str, int] = {}
        for node in ast.walk(functions["pytest_unconfigure"]):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                positions[node.func.id] = node.lineno
            elif isinstance(node.func, ast.Attribute):
                positions[node.func.attr] = node.lineno
        assert "_redirect_suite_config_for_teardown" in positions, (
            "pytest_unconfigure must redirect suite_config before _root.destroy()"
        )
        assert positions["_redirect_suite_config_for_teardown"] < positions["destroy"]
        assert positions["destroy"] < positions["_assert_no_hidden_geometry_persisted"]

        configured = {
            node.func.id
            for node in ast.walk(functions["pytest_configure"])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "_snapshot_live_window_geometries" in configured, (
            "pytest_configure must snapshot the developer's saved window geometry"
        )

    @pytest.mark.parametrize(
        ("geometry", "hidden"),
        [
            ("1x1+104+19", True),
            ("0x1+5+5", True),
            ("200x200+133+33", True),
            ("200x200", False),
            ("850x950+951+101", False),
            ("1120x1004+340+48", False),
            ("800x600", False),
            ("", False),
            (None, False),
            (42, False),
        ],
    )
    def test_a_hidden_window_geometry_is_recognised(
        self, geometry: object, hidden: bool
    ) -> None:
        """``1x1`` and ``200x200`` are what Tk reports for a window never shown.

        Measured on this host: a positioned top-level reports ``1x1+X+Y`` until
        it is first mapped, and ``200x200+X+Y`` once its idle tasks have run
        without it being shown.  No shipped window is that small, so either
        shape can only have been saved from a hidden window.
        """
        assert root_conftest._hidden_window_geometry(geometry) is hidden

    def test_the_session_fails_when_it_persists_a_hidden_geometry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The teardown lock names the key a hidden geometry landed on."""
        target = tmp_path / "audio_suite_config.json"

        def write(values: dict[str, str]) -> None:
            target.write_text(json.dumps(values), encoding="utf-8")

        write({"master_driver_window": "1120x1004+340+47"})
        monkeypatch.setattr(
            root_conftest,
            "_live_window_snapshot",
            (target, root_conftest._window_geometries(target)),
        )

        # A save the developer's own tool could make is not this lock's business.
        write({"master_driver_window": "900x700+10+10", "last_directory": "D:/Music"})
        root_conftest._assert_no_hidden_geometry_persisted()

        write({"master_driver_window": "1x1+104+19", "last_directory": "D:/Music"})
        with pytest.raises(AssertionError) as raised:
            root_conftest._assert_no_hidden_geometry_persisted()
        message = str(raised.value)
        assert "master_driver_window" in message
        assert "1x1+104+19" in message
        assert "1120x1004+340+47" in message

    def test_a_hidden_geometry_the_run_inherited_is_not_a_violation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The file already holds several: only a change means this run."""
        target = tmp_path / "audio_suite_config.json"
        target.write_text(
            json.dumps({"master_driver_window": "1x1+104+19"}), encoding="utf-8"
        )
        monkeypatch.setattr(
            root_conftest,
            "_live_window_snapshot",
            (target, root_conftest._window_geometries(target)),
        )

        target.write_text(
            json.dumps(
                {"master_driver_window": "1x1+104+19", "last_directory": "D:/Music"}
            ),
            encoding="utf-8",
        )
        root_conftest._assert_no_hidden_geometry_persisted()

    def test_the_geometry_selector_follows_the_value_not_the_key(
        self, tmp_path: Path
    ) -> None:
        """A window's geometry is watched under whatever key it was saved.

        ``bootstrap_tool_app`` takes its config key as an argument, so
        ``audio_suite_shared/tests/test_app_bootstrap.py`` writes windows under
        ``log_key``, ``notes_window_key`` and ``queue_key`` - names that do not
        end in ``_window``.  Selecting values by their saved shape needs no list
        of keys to keep in step with the tests that choose them, and a setting
        that merely looks like a size (no ``+X+Y``) is left alone.
        """
        target = tmp_path / "audio_suite_config.json"
        target.write_text(
            json.dumps(
                {
                    "master_driver_window": "1250x950+100+100",
                    "queue_key": "200x200+951+101",
                    "a_key_no_test_uses_yet": "850x950+951+101",
                    "thumbnail_size": "200x200",
                    "last_directory": "D:/Music",
                }
            ),
            encoding="utf-8",
        )

        assert set(root_conftest._window_geometries(target)) == {
            "master_driver_window",
            "queue_key",
            "a_key_no_test_uses_yet",
        }
