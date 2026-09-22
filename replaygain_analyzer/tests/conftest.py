"""
conftest.py — Shared real Tk() root for replaygain_analyzer/tests.

Provides a session-scoped hidden Tk root so that real tkinter variables
can be used in tests without mocking sys.modules["tkinter"].
"""

import tkinter as tk

import pytest

_root: tk.Tk | None = None


def pytest_configure(config: pytest.Config) -> None:
    """Create the shared hidden Tk root before any test module is collected."""
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
    """The shared hidden Tk root, for tests that want it explicitly."""
    assert _root is not None, "pytest_configure should have created the root"
    return _root
