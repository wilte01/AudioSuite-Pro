"""
conftest.py — Session-scoped hidden Tk root shared by every package's tests.

Implements the P5 consolidation of the per-tool Tk bootstraps:

- One module-level ``pytest_configure`` creates a single hidden Tk root before
  any test module is collected; package-level ``tests/conftest.py`` files no
  longer bootstrap their own root.
- Session-scoped fixtures ``root`` and ``tk_root`` both resolve to that shared
  root, so existing consumers (per-tool ``test_setup_tab.py`` suites,
  ``audio_suite_shared`` UI tests and ``lyrics_manager``) keep working
  unchanged.

B4 replaced the blanket headless skip.  A host with no display used to mark
**every** collected test skipped, so a run could report thousands of skips and
still exit 0 — nothing distinguished "this machine verified nothing" from
"everything passed".  The skip is now:

- **Bounded** — only tests that actually need Tk are skipped.  A test declares
  that by requesting the shared ``root``/``tk_root`` fixture, or by carrying the
  ``gui`` marker.  Everything else runs, which is the regression this fixes.
- **Attributable** — every skip carries a reason naming the missing display,
  and tests that need a display without the shared root keep their own
  explicit ``requires_display`` skipif (a reason, not an inherited blanket).
- **Loud** — the absence of a display raises a real warning (visible under
  ``-ra`` and in CI logs) and the session summary always prints whether GUI
  behaviour was verified, and how many tests the display cost.
- **Still recoverable** — ``AUDIOSUITE_GUI_SKIP=all`` restores the old
  session-wide skip as an explicit, warned-about safety net for hosts that
  cannot yet run a bounded subset.

D1 (Stage 3) completes the marker contract on the same principle:

- ``hardware`` is *deselected* by default (``-m "not hardware"`` in pyproject
  ``addopts``) and never runs in CI; documented opt-in is ``pytest -m hardware``.
- ``integration`` runs by default wherever the declared ffmpeg/ffprobe
  executables are found — the same A5 declaration the startup preflight
  consults — and where one is missing, each integration test skips with a
  reason naming the missing binary. The skip is bounded to the marker, so a
  missing ffmpeg can never take the rest of the run with it.

Changed in 1.3.0: the session sets ``AUDIOSUITE_WHATS_NEW=0``, so a test that
pumps Tk's event loop never pops the release-notes panel or writes
``last_seen_version`` into the real shared config.  The panel's own suite
clears the variable and exercises it directly.

Changed in 2.7.0: the session also holds its skips to a committed budget
(``tests/skip_budget.py`` and ``tests/data/skip_budget.json``).  A skip reports
green, so the six ``importorskip("setuptools")`` skips the 2.6.0 floor leg
carried cost the wheel checks silently; a reason outside the budget now fails
the session and names the test.

Changed in 2.9.0: ``_isolated_refinery_settings`` fails a test that aims a
save at the developer's live ``~/.audiosuite/refinery_settings.json``
instead of letting the run overwrite it, and ``_isolated_suite_config`` does
the same for the live ``audio_suite_config.json`` beside the checkout - which
also earns the ``pytest_unconfigure`` redirect, because each window the tests
leave open saves its geometry as the shared root is destroyed - and the
the session's last act compares every saved window geometry it can find -
selected by its ``WxH+X+Y`` shape, so no list of keys has to keep up with the
labels the tests name their windows - with the values it started from, so a
run that ever saves a hidden window's geometry fails instead of reporting
green.  ``clean_shared_root``'s declaration is load-bearing too: the lock
records the modules it sees building on the root, and the session fails every
module that declared it and built nothing - an unused declaration
pre-approves the next leak.
"""

from __future__ import annotations

import gc
import json
import os
import re
import tkinter as tk
import warnings
from pathlib import Path
from typing import Generator

import pytest
from _pytest.terminal import TerminalReporter

#: Enables the ``pytester`` fixture, used by ``tests/test_conftest.py`` to run
#: the suite's own conftest against a simulated headless host.  Only the
#: rootdir conftest may declare this.
pytest_plugins = ["pytester"]

_root: tk.Tk | None = None
_display_available = False
_display_skips = 0
_blanket_mode = False
_collected = 0

#: Every skip this session reported, as ``(nodeid, reason)``.
_skip_records: list[tuple[str, str]] = []

#: The developer's live config and its saved window-geometry values as the
#: session found them, so the teardown can prove the run did not save a hidden
#: window's geometry into it.  ``None`` when there is no display or no readable
#: file.
_live_window_snapshot: tuple[Path, dict[str, str]] | None = None

#: The session-scoped fixtures whose presence means "this test needs a display".
_GUI_FIXTURES = frozenset({"root", "tk_root", "clean_shared_root"})

#: Node attribute ``clean_shared_root`` sets: this module builds on the shared
#: root deliberately and leaves the teardown to the session's lock.
_SHARED_ROOT_ADOPTED = "_audiosuite_shared_root_adopted"

#: Modules whose declared tests left a widget on the shared root this session.
#: A declaration is load-bearing only when the module it names really builds
#: there, so the session fails on a declaration that built nothing.
_SHARED_ROOT_BUILDERS: set[str] = set()

#: Env var that restores the pre-B4 session-wide skip (safety net only).
GUI_SKIP_ENV = "AUDIOSUITE_GUI_SKIP"

_NO_FFMPEG_REASON_TEMPLATE = (
    "Requires ffmpeg and ffprobe for real audio decode/export "
    "({missing} not found on PATH) — install with the commands quoted in "
    "audio_suite_shared/system_requirements.py"
)

_missing_executables: list[str] | None = None

INTEGRATION_MARKER = "integration"

NO_DISPLAY_REASON = "No display available — this test needs a real Tk root"

BLANKET_REASON = (
    "AUDIOSUITE_GUI_SKIP=all — the session-wide skip-all safety net is active, "
    "so this run verifies nothing at all"
)

SUMMARY_HEADING = "GUI / display report"


class GuiDisplayUnavailableWarning(UserWarning):
    """The suite ran without a usable Tk display.

    A distinct category (rather than a bare ``UserWarning``) so CI can filter
    or fail on it, and so it is attributable in the warnings summary.
    """


def probe_missing_executables() -> list[str]:
    """Return the declared system executables that cannot be found on PATH.

    Probed once per session and cached: the declaration lives in
    :mod:`audio_suite_shared.system_requirements` (plan A5), the same single
    source the startup preflight consults, so the dialog a user sees at launch
    and the skip a CI log shows for an ``integration`` test cannot disagree.

    A conftest can be copied out of its repository (``tests/test_conftest.py``
    does exactly that), so an import failure here degrades to "cannot probe"
    rather than aborting the whole session — those runs let the integration
    tests execute and fail loudly instead of hiding anything.

    Returns:
        Names of the missing executables in declaration order; empty when
        every declared requirement resolves (or the declaration is
        unreachable).
    """
    global _missing_executables
    if _missing_executables is None:
        # Probed against the live module at call time (function-local import,
        # matching the AGENTS.md patch rule): a test harness that replaces the
        # declaration module sees the replacement, regardless of import order.
        try:
            from audio_suite_shared import system_requirements as declared
        except ImportError:
            missing: list[str] = []
        else:
            missing = [
                requirement.name for requirement in declared.find_missing_requirements()
            ]
        _missing_executables = missing
    return _missing_executables


def integration_skip_reason(missing: list[str]) -> str:
    """Build the attributable skip reason for one missing-binary report.

    Args:
        missing: Names returned by :func:`probe_missing_executables`.

    Returns:
        A reason naming exactly which prerequisite is absent, so a reader can
        interpret the skip without guessing (plan D1).
    """
    return _NO_FFMPEG_REASON_TEMPLATE.format(missing=", ".join(missing))


def pytest_configure(config: pytest.Config) -> None:
    """Create the shared hidden Tk root before any test module is collected."""
    global _root, _display_available
    config.addinivalue_line(
        "markers",
        "gui: test genuinely requires a graphical display. Skipped with an "
        "attributable reason on a headless host; use for tests that need Tk "
        "without the shared root/tk_root fixture.",
    )
    try:
        _root = tk.Tk()
        _root.withdraw()
    except tk.TclError:
        _root = None
        _display_available = False
        warnings.warn(
            f"No Tk display is available on this host, so GUI behaviour cannot "
            f"be verified. Only tests that need Tk will be skipped; set "
            f"{GUI_SKIP_ENV}=all to skip the whole session instead.",
            GuiDisplayUnavailableWarning,
            stacklevel=2,
        )
    else:
        _display_available = True
        _snapshot_live_window_geometries()


def _redirect_suite_config_for_teardown() -> None:
    """Point ``suite_config`` at a scratch file while the root is destroyed.

    A window the tests left open saves its geometry from the widget's
    ``<Destroy>`` binding as the shared root goes away, and that is a save of
    the whole document: measured on a full run, 70 of them fired here, aimed
    at the developer's real ``audio_suite_config.json`` after
    ``_isolated_suite_config``'s guard had already been restored.  The writer
    is aimed at a scratch directory instead, so the last thing a run does
    cannot rewrite the user's preferences.
    """
    import tempfile

    import audio_suite_shared.suite_config as suite_config

    scratch = Path(tempfile.mkdtemp(prefix="audiosuite-teardown-"))
    suite_config.CONFIG_PATH = scratch / "audio_suite_config.json"
    suite_config._LOCK_PATH = suite_config.CONFIG_PATH.with_suffix(".json.lock")
    suite_config._invalidate_cache()


#: The shape ``setup_window`` stores: ``root.geometry()`` always reports a size
#: and a position, so the trailing ``+X+Y`` is what tells a saved geometry apart
#: from a config value that merely looks like a size.
_SAVED_GEOMETRY = re.compile(r"^(\d+)x(\d+)[+-]\d+[+-]\d+$")


def _saved_geometry_size(value: object) -> tuple[int, int] | None:
    """Return the ``(width, height)`` a saved window geometry carries, or None."""
    if not isinstance(value, str):
        return None
    match = _SAVED_GEOMETRY.match(value)
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)))


def _hidden_window_geometry(value: object) -> bool:
    """Return True for a geometry only a window the user never saw can carry.

    Measured on this host's Tk: a top-level that has been positioned but never
    mapped reports ``1x1+X+Y`` - the requested size is realised only when the
    window is first shown - and one that has run its idle tasks without being
    shown reports Tk's default ``200x200+X+Y``.  No shipped window is that
    small (the smallest asks for ``760x620``), so a saved value of either shape
    came from a hidden window - a test root, or a window destroyed before it
    was ever mapped - saving its geometry from ``<Destroy>``.
    """
    size = _saved_geometry_size(value)
    return size is not None and (min(size) <= 1 or size == (200, 200))


def _window_geometries(path: Path) -> dict[str, str]:
    """Return the saved window-geometry values from one config file.

    Selected by the value's shape, not the key's name: ``bootstrap_tool_app``
    takes its config key as an argument, so a window is stored under whatever
    label the caller passes (``audio_suite_shared/tests/test_app_bootstrap.py``
    writes ``log_key``, ``notes_window_key`` and ``queue_key``), and a list of
    keys would stop matching the day a test passes a new one.  A missing,
    unreadable or malformed file yields an empty mapping: a first run with no
    config yet must not be reported as a violation.
    """
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        key: value
        for key, value in data.items()
        if isinstance(value, str) and _saved_geometry_size(value) is not None
    }


def _hidden_geometry_regressions(
    before: dict[str, str], after: dict[str, str]
) -> list[str]:
    """Return the keys whose saved geometry became a hidden window's.

    A key that already held one is not a regression - the live file has carried
    several since before the guard existed - but a key that *changed* to one,
    or appeared with one, is a window this run saved from a root it never
    showed.
    """
    return sorted(
        key
        for key, value in after.items()
        if _hidden_window_geometry(value) and before.get(key) != value
    )


def _snapshot_live_window_geometries() -> None:
    """Record the developer's saved window geometry before any test runs."""
    global _live_window_snapshot
    if _root is None:
        return
    try:
        import audio_suite_shared.suite_config as suite_config
    except ImportError:  # a conftest copied out of its repository
        return
    path = Path(suite_config.CONFIG_PATH)
    _live_window_snapshot = (path, _window_geometries(path))


def _assert_no_hidden_geometry_persisted() -> None:
    """Fail the session if it saved a hidden window's geometry to the file.

    ``_isolated_suite_config`` refuses a save aimed at the live path and
    ``pytest_unconfigure`` aims the teardown's saves at a scratch file, so this
    should never fire: it is the lock that says neither seam can be bypassed
    quietly.  It reads the path recorded at configure time - the teardown
    redirect has moved ``CONFIG_PATH`` by now - and compares only values shaped
    like a saved window geometry, so anything else the developer's own tool
    saves during the run is not this session's doing.
    """
    if _live_window_snapshot is None:
        return
    path, before = _live_window_snapshot
    after = _window_geometries(path)
    regressions = _hidden_geometry_regressions(before, after)
    if not regressions:
        return
    detail = ", ".join(
        f"{key}={after[key]!r} (was {before.get(key)!r})" for key in regressions
    )
    raise AssertionError(
        "the run persisted a hidden window's geometry into the developer's "
        f"{path.name}: {detail}. Tk reports 1x1+X+Y for a top-level that was "
        "never mapped and 200x200+X+Y for one that was never laid out, so this "
        "came from a window no user saw saving on <Destroy>; point "
        "suite_config.CONFIG_PATH at a temp path in the test that builds it."
    )


def pytest_unconfigure(config: pytest.Config) -> None:
    """Destroy the shared root after the whole session finishes."""
    global _root
    if _root is not None:
        _redirect_suite_config_for_teardown()
        _root.destroy()
        _root = None
        _assert_no_hidden_geometry_persisted()


def requires_display(item: pytest.Item) -> bool:
    """Return True when *item* cannot run without a usable Tk display.

    Two declarative signals, both chosen because a test cannot get a Tk root by
    accident:

    1. it requests one of the shared session fixtures, or
    2. it carries the ``gui`` marker.

    Tests that need a display but build their own Tk objects use an explicit
    ``requires_display`` skipif instead, which names the requirement in its own
    skip reason.
    """
    if any(marker.name == "gui" for marker in item.iter_markers()):
        return True
    # ``fixturenames`` is public on a concrete Item but absent from the typeshed
    # surface mypy sees, and it is absent entirely for some node types.
    requested = getattr(item, "fixturenames", ())
    return bool(_GUI_FIXTURES.intersection(requested))


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip the display-dependent subset when no display is available.

    Skipping happens here rather than in ``pytest_configure`` because calling
    ``pytest.skip()`` from ``pytest_configure`` raises ``INTERNALERROR``
    (exit code 3).

    Args:
        config: The active pytest config (used to read the safety-net opt-in).
        items:  Every collected test, mutated in place.
    """
    global _display_skips, _blanket_mode, _collected
    _collected = len(items)
    _blanket_mode = os.environ.get(GUI_SKIP_ENV, "").strip().lower() == "all"

    # D1: `integration` runs by default wherever the declared executables are
    # present; where they are missing, each integration test skips with a
    # reason naming the missing prerequisite — bounded to the marker, so a
    # missing ffmpeg never takes the rest of the run with it.
    missing = probe_missing_executables()
    if missing:
        reason = integration_skip_reason(missing)
        for item in items:
            if item.get_closest_marker(INTEGRATION_MARKER):
                item.add_marker(pytest.mark.skip(reason=reason))

    if _display_available:
        return

    if _blanket_mode:
        to_skip, reason = items, BLANKET_REASON
    else:
        to_skip = [item for item in items if requires_display(item)]
        reason = NO_DISPLAY_REASON

    for item in to_skip:
        item.add_marker(pytest.mark.skip(reason=reason))
    _display_skips = len(to_skip)


def format_display_summary() -> list[str]:
    """Build the always-printed display report for the terminal summary.

    Returns:
        One header line followed by the report body.  The "GUI behaviour" line
        is the load-bearing one: it states plainly whether this run verified
        the Tk-dependent behaviour at all.
    """
    lines = [SUMMARY_HEADING]
    if _display_available:
        lines.append("  Tk display available  : yes (a real Tk root was created)")
        lines.append(f"  Tests skipped for display reasons : {_display_skips}")
        lines.append("  GUI behaviour         : VERIFIED in this run")
        return lines

    lines.append("  Tk display available  : NO — tk.Tk() raised TclError")
    lines.append(
        f"  Tests skipped for display reasons : {_display_skips} "
        f"of {_collected} collected"
    )
    lines.append(
        "  GUI behaviour         : NOT VERIFIED in this run — "
        "every Tk-dependent behaviour was skipped"
    )
    if _blanket_mode:
        lines.append(
            f"  SAFETY NET ACTIVE     : {GUI_SKIP_ENV}=all skipped the whole "
            "session, so this run proves nothing"
        )
    return lines


def pytest_terminal_summary(
    terminalreporter: TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    """Always print the display report, display present or not.

    Args:
        terminalreporter: Pytest's reporter, used to emit the report lines.
        exitstatus: The session's exit status (unused).
        config: The active pytest config (unused).
    """
    del exitstatus, config
    for line in format_display_summary():
        terminalreporter.write_line(line)


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """Record every skip so the session can be judged against its budget.

    A skip's ``longrepr`` is a ``(file, line, reason)`` tuple in the common
    case.  Anything else is stringified rather than dropped, so an unfamiliar
    shape is judged by the budget instead of vanishing from it.

    The extraction is inline on purpose.  A module-level conftest helper that
    takes an argument is registered as a fixture by pytest 9, which then refuses
    the direct call: ``Failed: Fixture "_skipped_reason" called directly`` inside
    ``pytest_runtest_logreport``, surfacing as an INTERNALERROR (exit 3) on the
    first skipped test.
    """
    if not report.skipped:
        return
    longrepr: object = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        reason = str(longrepr[2])
    else:
        reason = str(longrepr).strip()
    _skip_records.append((report.nodeid, reason))


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Judge the session on the two greens a run cannot see for itself.

    A skip and an unused root declaration both report green: the first because
    a prerequisite went missing, the second because a module was pre-approved
    for a leak it never makes.  Each rule lives in its own helper, so each
    verdict is read in one place.

    Args:
        session: The finished session, whose exit status is raised on a
            violation.
        exitstatus: Pytest's own verdict; unused, because pytest reads
            ``session.exitstatus`` after this hook.
    """
    del exitstatus
    _fail_on_skip_budget(session)
    _fail_on_unused_root_declarations(session)


def _fail_on_skip_budget(session: pytest.Session) -> None:
    """Fail the session on a skip the committed budget does not permit.

    A skip reports green, so a run's own total cannot distinguish "this host
    verified everything it could" from "a prerequisite went missing and six
    tests stopped checking anything" - the shape the 2.6.0 floor leg had.  The
    rule lives in :mod:`tests.skip_budget` and is tested against fixtures there;
    this helper only feeds it the session's skips.

    Args:
        session: The finished session, whose exit status is raised on a
            violation.
    """
    if not _skip_records:
        return
    try:
        from tests import skip_budget
    except ImportError:  # a conftest copied out of its repository
        return
    # The budget belongs to the tree under test, not to whichever conftest file
    # was loaded: a conftest copied into a temp directory (tests/test_conftest.py
    # does that against simulated headless hosts) would otherwise enforce the
    # real repository's budget on a run that is not the repository.
    budget_path = session.config.rootpath / "tests" / "data" / "skip_budget.json"
    if not budget_path.is_file():
        return
    try:
        entries, total = skip_budget.load_budget(budget_path)
    except skip_budget.BudgetError as exc:
        warnings.warn(
            f"skip budget unusable, so this run's skips went unchecked: {exc}",
            stacklevel=2,
        )
        return
    problems = skip_budget.violations(
        [skip_budget.Skip(nodeid, reason) for nodeid, reason in _skip_records],
        entries,
        total,
    )
    if not problems:
        return
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    lines = [
        "Skip budget exceeded (tests/data/skip_budget.json):",
        *(f"  {problem}" for problem in problems),
    ]
    if reporter is None:  # pragma: no cover - a session with no terminal
        print("\n".join(lines))
    else:
        for line in lines:
            reporter.write_line(line)
    if session.exitstatus == 0:
        session.exitstatus = 1


def _fail_on_unused_root_declarations(session: pytest.Session) -> None:
    """Fail the session on a module that declared the root and never built there.

    ``clean_shared_root`` pre-approves whatever a module leaves on the
    session-scoped root, so a declaration whose module never leaves anything is
    dead weight that pre-approves the next leak - the rule
    ``tests/test_shared_code_reuse.py`` applies to its allowlists, where an
    entry that excuses nothing is a bug rather than a licence.  Only the modules
    whose tests actually ran can be judged: a module skipped down to nothing
    never got as far as building.  ``tests/test_conftest.py`` drives both
    verdicts in a child session.

    Args:
        session: The finished session, whose declaring modules are compared
            against the ones the lock saw building on the root.
    """
    unused = sorted(
        {
            str(item.path)
            for item in session.items
            if getattr(item, _SHARED_ROOT_ADOPTED, False)
        }
        - _SHARED_ROOT_BUILDERS
    )
    if not unused:
        return
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    lines = [
        "Root declarations that build nothing (clean_shared_root):",
        *(
            f"  {_relative_to_root(path, session)} declares clean_shared_root "
            "but left no widget on the shared root"
            for path in unused
        ),
        "  A declaration that cleans nothing pre-approves the next leak: remove "
        "it, or destroy what the module builds.",
    ]
    if reporter is None:  # pragma: no cover - a session with no terminal
        print("\n".join(lines))
    else:
        for line in lines:
            reporter.write_line(line)
    if session.exitstatus == 0:
        session.exitstatus = 1


def _relative_to_root(path: str, session: pytest.Session) -> str:
    """Name *path* relative to the session's root, for the message."""
    try:
        return os.path.relpath(path, session.config.rootpath)
    except ValueError:  # pragma: no cover - a path on another Windows drive
        return path


@pytest.fixture(scope="session")
def root() -> tk.Tk:
    """The shared hidden Tk root, for tests that want it explicitly."""
    root = _root
    assert root is not None, "No display available — Tk root was not created"
    return root


@pytest.fixture(scope="session")
def tk_root() -> tk.Tk:
    """Alias of root; used by audio_suite_shared and lyrics_manager tests."""
    tk_root = _root
    assert tk_root is not None, "No display available — Tk root was not created"
    return tk_root


@pytest.fixture()
def clean_shared_root(request: pytest.FixtureRequest) -> None:
    """Declare that this module builds on the session-scoped root.

    The root outlives every test, so a module whose tests parent widgets on it
    says so once, in the module body::

        pytestmark = pytest.mark.usefixtures("clean_shared_root")

    and ``_shared_root_keeps_nothing`` destroys the leftovers silently instead
    of failing the test.  A module that builds on the root *without* declaring
    it fails at the leaking test, so collection order cannot hide the leak.
    """
    setattr(request.node, _SHARED_ROOT_ADOPTED, True)


def _leftover_widget(widget: tk.Misc) -> str:
    """Name one widget left on the shared root, closely enough to find its test."""
    try:
        text = str(widget.cget("text"))
    except tk.TclError:
        text = ""
    label = f"{widget.winfo_class()} {widget!s}"
    return f"{label} (text={text!r})" if text else label


@pytest.fixture(autouse=True)
def _shared_root_keeps_nothing(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Fail the test that leaves a widget on the session-scoped root.

    ``root`` outlives every test, so a suite that parents a tab on it and never
    destroys it hands the leftovers to whatever runs next — and only a test that
    walks the root can notice.  That is how the Album Art Normalizer's and the
    Music Format Converter's Setup suites shipped leaking: ``pytest
    album_art_normalizer tests/test_suite_app_contract.py`` counts the tool's
    title on the window it just built and saw twelve, while the bare gate
    collected root ``tests/`` first and never looked.  Failing at the leak's own
    teardown makes collection order irrelevant.  A module that builds on the root
    on purpose declares ``clean_shared_root`` instead, and its leftovers are
    destroyed without failing it.

    The leftovers are destroyed before the failure is raised, so one leak costs
    one test instead of poisoning every later walk of the root.
    """
    if _root is None or not requires_display(request.node):
        yield
        return
    before = set(_root.winfo_children())
    yield
    # Read the declaration here, not at setup: autouse fixtures are set up
    # before the module's own, so a flag read first would always be False.
    adopted = getattr(request.node, _SHARED_ROOT_ADOPTED, False)
    leftovers = [widget for widget in _root.winfo_children() if widget not in before]
    if leftovers and adopted:
        _SHARED_ROOT_BUILDERS.add(str(request.path))
    # Describe before destroying: a destroyed widget has no Tcl path to name.
    names = ", ".join(_leftover_widget(widget) for widget in leftovers)
    for widget in leftovers:
        if widget.winfo_exists():
            widget.destroy()
    if leftovers and not adopted:
        raise AssertionError(
            "this test left widgets on the session-scoped Tk root, so every "
            f"later test that walks it sees them: {names}. Destroy what you "
            "build, or declare the module's use of the root with "
            '``pytestmark = pytest.mark.usefixtures("clean_shared_root")``.'
        )


@pytest.fixture(autouse=True)
def _collect_tk_garbage_on_main_thread(
    request: pytest.FixtureRequest,
) -> Generator[None, None, None]:
    """Finalize dropped Tk objects on the main thread after UI tests.

    ``tkinter.Variable.__del__`` calls back into the Tcl interpreter, which
    raises ``RuntimeError: main thread is not in main loop`` when the finalizer
    runs off the main thread.  Tests that process audio spawn worker threads,
    and a GC cycle triggered by one of those threads can finalize a ``Variable``
    dropped by an earlier UI test — surfacing as a ``PytestUnraisableException``
    warning and a non-zero warning count for an otherwise-green run (it appeared
    as ``noise_reduction``'s audio test finalizing a Variable another package
    dropped).

    Only display-dependent tests can create such a ``Variable`` (against the
    shared root or a self-built Tk), so the collection is scoped to them: a full
    ``gc.collect()`` after *every* test is needlessly expensive once the session
    heap grows, whereas the UI subset is small.  ``requires_display`` is the same
    bounded predicate that drives the headless skip, so the two cannot disagree.
    """
    collect_after = requires_display(request.node)
    yield
    if collect_after:
        gc.collect()


@pytest.fixture(scope="session", autouse=True)
def _isolated_undo_db(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[None, None, None]:
    """Point the shared undo log at a scratch database for the whole session.

    Every batch_undo access that relies on the default path — CLI commands
    wrapping runs in ``active_batch(...)``, and the GUI ``active_batch``
    callers — would otherwise write into the real per-user
    ``~/.audiosuite/undo_log.db`` and pollute the Undo Tag Edits "Recent
    runs" list with pytest artifacts (paths like
    ``pytest-of-<user>\\test_skip_existing_by_default0\\song.mp3``).  The
    override is session-wide and autouse so no test can ever touch the
    production log, no matter which tool it exercises.
    """
    path = tmp_path_factory.mktemp("undo_db") / "undo_log.db"
    previous = os.environ.get("AUDIOSUITE_UNDO_DB")
    os.environ["AUDIOSUITE_UNDO_DB"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AUDIOSUITE_UNDO_DB", None)
        else:
            os.environ["AUDIOSUITE_UNDO_DB"] = previous


@pytest.fixture(scope="session", autouse=True)
def _isolated_log_dir(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[None, None, None]:
    """Point the suite's file logging at a scratch directory for the session.

    ``logging_setup.configure_logging`` writes ``logs/audio_suite.log`` and
    ``logs/<program>.log`` relative to the suite root.  Any test that drives
    a real entry point (the CLI's ``configure_logging`` call, a bootstrap
    helper, an app constructed without a stubbed logger) would otherwise
    write DEBUG/INFO processing records and many
    ``=== <program> started ===`` lines straight into the shipped
    ``logs/`` tree — the pollution that made the real suite log 10,000+
    lines of test artifacts.  ``AUDIOSUITE_LOG_DIR`` redirects every write
    to the session's temp directory, so no test can touch production logs.
    """
    path = tmp_path_factory.mktemp("logs")
    previous = os.environ.get("AUDIOSUITE_LOG_DIR")
    os.environ["AUDIOSUITE_LOG_DIR"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AUDIOSUITE_LOG_DIR", None)
        else:
            os.environ["AUDIOSUITE_LOG_DIR"] = previous


@pytest.fixture(scope="session", autouse=True)
def _isolated_refinery_settings() -> Generator[None, None, None]:
    """Fail a test that would rewrite the developer's real Refinery settings.

    ``audio_refinery.utils.settings.save`` writes
    ``~/.audiosuite/refinery_settings.json``, and the Master Driver calls it
    before it launches a batch (``master_driver/tool_launcher.py``).  A test
    that reached a real launch would overwrite the selection the developer's
    own windows restore - and, through the Best Audio lock, change which
    control states later tests measure.

    The live path stays where it is, because a lock asserts it; the *writer* is
    guarded instead.  A test that deliberately exercises saving points
    ``_SETTINGS_FILE`` at a temp path, as ``audio_refinery/tests/test_settings``
    does, and passes straight through.
    """
    import sys
    from typing import Any

    import audio_refinery.utils.settings as settings

    real_path = settings._SETTINGS_FILE
    real_save = settings.save

    def guarded_save(config: Any) -> None:
        if settings._SETTINGS_FILE != real_path:
            real_save(config)
            return
        raise AssertionError(
            "a test tried to write the developer's real Refinery settings "
            f"({real_path}). Point _SETTINGS_FILE at a temp path, or patch "
            "master_driver.ui.refinery_tab.save_settings."
        )

    setattr(settings, "save", guarded_save)
    for module_name, attr in (
        ("audio_refinery.app", "save_settings"),
        ("master_driver.ui.refinery_tab", "_save_settings"),
    ):
        module = sys.modules.get(module_name)
        if module is not None and getattr(module, attr, None) is real_save:
            setattr(module, attr, guarded_save)
    try:
        yield
    finally:
        setattr(settings, "save", real_save)


@pytest.fixture(scope="session", autouse=True)
def _isolated_suite_config() -> Generator[None, None, None]:
    """Fail a test that would rewrite the developer's real shared config.

    ``audio_suite_config.json`` sits beside the checkout and holds every
    tool's saved preference: the last directory, the palette, the font sizes
    and each window's geometry.  Every ``suite_config.save_*`` call is a
    read-modify-write of that whole document, so one save aimed at the live
    path rewrites all of it - and the Master Driver saves the last directory
    immediately after the Refinery settings (``master_driver/tool_launcher.py``
    ``launch_refinery``), which is the pair a test that reached a real launch
    would overwrite.

    Reads stay untouched, so a test that asserts the live path's shape still
    sees it; the *writer* is guarded instead, exactly as
    ``_isolated_refinery_settings`` guards ``~/.audiosuite/refinery_settings.json``.
    A test that deliberately saves points ``CONFIG_PATH`` at a temp file, as
    ``audio_suite_shared/tests/test_suite_config.py`` does, and passes straight
    through.
    """
    from typing import Any

    import audio_suite_shared.suite_config as suite_config

    real_path = suite_config.CONFIG_PATH
    real_save = suite_config._save

    def guarded_save(data: dict[str, Any]) -> None:
        if suite_config.CONFIG_PATH != real_path:
            real_save(data)
            return
        raise AssertionError(
            "a test tried to write the developer's real audio_suite_config.json "
            f"({real_path}). Point suite_config.CONFIG_PATH at a temp path, or "
            "patch the writer (e.g. _suite_config.save_last_directory)."
        )

    setattr(suite_config, "_save", guarded_save)
    try:
        yield
    finally:
        setattr(suite_config, "_save", real_save)


@pytest.fixture(scope="session", autouse=True)
def _no_release_notes_panel() -> Generator[None, None, None]:
    """Keep the What's New panel out of every test that builds a real app.

    ``bootstrap_tool_app`` and the Master Driver schedule the panel on idle, so
    any test that pumps the Tk event loop would otherwise pop a Toplevel and
    write ``last_seen_version`` into the real ``audio_suite_config.json`` - a
    click-through dialog is both unwanted and unasserted there.  The panel's
    own suite clears this variable and calls ``offer_pending``/``show``
    directly, so the feature is tested rather than disabled.
    """
    previous = os.environ.get("AUDIOSUITE_WHATS_NEW")
    os.environ["AUDIOSUITE_WHATS_NEW"] = "0"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("AUDIOSUITE_WHATS_NEW", None)
        else:
            os.environ["AUDIOSUITE_WHATS_NEW"] = previous
