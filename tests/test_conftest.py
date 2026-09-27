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
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import os
import shutil
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
