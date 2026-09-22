"""
conftest.py — Shared real Tk() root for lyrics_manager/tests.

Provides a session-scoped hidden Tk root so that real tkinter variables
and widget trees can be used in tests without mocking sys.modules.
"""

import tkinter as tk

import pytest


@pytest.fixture(scope="session")
def tk_root() -> tk.Tk:
    """Single session-scoped Tk root — never destroyed to avoid Tcl corruption
    on platforms where creating a second Tk instance after destroying the first
    fails (Windows Python 3.14+)."""
    root = tk.Tk()
    root.withdraw()
    return root  # keep alive for entire session


@pytest.fixture
def root(tk_root: tk.Tk) -> tk.Tk:
    """Alias kept for parity with the shared suite's fixture name."""
    return tk_root
