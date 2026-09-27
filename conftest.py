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
"""

from __future__ import annotations

import os
import tkinter as tk
import warnings
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

#: The session-scoped fixtures whose presence means "this test needs a display".
_GUI_FIXTURES = frozenset({"root", "tk_root"})

#: Env var that restores the pre-B4 session-wide skip (safety net only).
GUI_SKIP_ENV = "AUDIOSUITE_GUI_SKIP"

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


def pytest_unconfigure(config: pytest.Config) -> None:
    """Destroy the shared root after the whole session finishes."""
    global _root
    if _root is not None:
        _root.destroy()
        _root = None


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
