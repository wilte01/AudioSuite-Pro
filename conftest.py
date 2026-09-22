"""
conftest.py — Session-scoped hidden Tk root shared by every package's tests.

Implements the P5 consolidation of the per-tool Tk bootstraps:

- One module-level ``pytest_configure`` creates a single hidden Tk root before
  any test module is collected; package-level ``tests/conftest.py`` files no
  longer bootstrap their own root.
- On a headless host (``tk.Tk()`` raises ``tk.TclError``) every collected test
  is marked skipped via ``pytest_collection_modifyitems``. The previous
  per-tool pattern called ``pytest.skip()`` inside ``pytest_configure``, which
  crashes pytest with INTERNALERROR / exit code 3.

Session-scoped fixtures ``root`` and ``tk_root`` both resolve to that shared
root, so existing consumers (per-tool ``test_setup_tab.py`` suites,
``audio_suite_shared`` UI tests and ``lyrics_manager``) keep working
unchanged.
"""

from __future__ import annotations

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
        _root = None


def pytest_unconfigure(config: pytest.Config) -> None:
    """Destroy the shared root after the whole session finishes."""
    global _root
    if _root is not None:
        _root.destroy()
        _root = None


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip everything when no display is available.

    Skipping happens here rather than in ``pytest_configure`` because calling
    ``pytest.skip()`` from ``pytest_configure`` raises ``INTERNALERROR``
    (exit code 3). Items are only marked when root creation already failed.
    """
    if _root is None:
        for item in items:
            item.add_marker(
                pytest.mark.skip(
                    reason=(
                        "No display available — tkinter tests require a GUI environment"
                    )
                )
            )


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
