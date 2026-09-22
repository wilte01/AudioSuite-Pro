"""
conftest.py — Shared real Tk() root for master_driver/tests.

Background
----------
test_app_state.py and test_runner.py previously mocked sys.modules
["tkinter"] at import time, because AppState() and arg_builder's
tk.BooleanVar(value=True) call need *something* importable as `tkinter`,
and real tkinter variables raise RuntimeError if no Tk() root exists yet.

That approach caused a cross-file leak: pytest imports every test module
during collection before running any test, so whichever test file was
collected first "won" the sys.modules["tkinter"] slot for every later
file's own `import tkinter as tk` statement — permanently, since name
bindings made at import time can't be undone by another file's teardown.
test_ui_cards.py needs the *real* tkinter (it builds and inspects actual
widgets), so it broke whenever a mocking file was collected first.

Fix
---
Provide one real, hidden Tk root for the whole pytest session, created
here before any test module is collected. Real tkinter is used everywhere,
by every file — no mocking, no sys.modules patching, no import-order
sensitivity. AppState() and tk.BooleanVar(value=True) both work fine once
a root exists; they just need one to exist before the first variable is
constructed.
"""

import tkinter as tk

import pytest

_root: tk.Tk | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Create the shared hidden Tk root before any test module is collected.

    pytest_configure runs before collection, so the root exists before any
    test file's module-level code (e.g. AppState construction inside a
    fixture) or any of arg_builder's runtime tk.BooleanVar(...) calls can
    execute. This makes a default root available via tkinter's own
    _default_root mechanism for any code that doesn't explicitly take one
    as a parameter (e.g. arg_builder.build_refinery_args' internal
    tk.BooleanVar(value=True)).
    """
    global _root
    try:
        _root = tk.Tk()
        _root.withdraw()
    except tk.TclError:
        pytest.skip("No display available — tkinter tests require a GUI environment")


def pytest_unconfigure(config: pytest.Config) -> None:
    """Destroy the shared root after the whole session finishes."""
    global _root
    if _root is not None:
        _root.destroy()
        _root = None


@pytest.fixture(scope="session")
def root() -> tk.Tk:
    """The shared hidden Tk root, for tests that want it explicitly.

    test_ui_cards.py's existing fixtures (`root`, `parent`) consume this.
    """
    assert _root is not None, "pytest_configure should have created the root"
    return _root
