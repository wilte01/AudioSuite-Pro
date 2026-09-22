"""
thread_safe_slot_var.py — Thread-safe wrapper for tkinter StringVar.

Provides a drop-in replacement for ``tk.StringVar`` that safely schedules
``.set()`` calls on the main tkinter thread via ``root.after(0, ...)``.

Use this in any tool that passes slot variables to worker threads running
in ``ThreadPoolExecutor`` or ``threading.Thread`` targets.

Usage::

    from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

    # In your app's __init__:
    self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(num_workers)]
    self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)

    # Pass self._safe_slot_vars to your core processor instead of self.slot_vars
"""

from __future__ import annotations

import tkinter as tk


class ThreadSafeSlotVar:
    """Wrap a ``tk.StringVar`` so that ``.set()`` is always
    scheduled on the main thread.

    ``.get()`` is synchronous (reads from the main-thread variable directly,
    which is safe on CPython due to the GIL).
    """

    def __init__(self, root: tk.Misc, var: tk.StringVar) -> None:
        self._root = root
        self._var = var

    def set(self, value: str) -> None:
        """Schedule ``var.set(value)`` on the main tkinter thread."""
        self._root.after(0, self._var.set, value)

    def get(self) -> str:
        """Read the current value (safe from any thread on CPython)."""
        return self._var.get()


def make_safe_slot_vars(
    root: tk.Misc, slot_vars: list[tk.StringVar]
) -> list[ThreadSafeSlotVar]:
    """Wrap a list of ``tk.StringVar`` into thread-safe equivalents.

    Args:
        root: The tkinter root window (used for ``after()`` scheduling).
        slot_vars: List of ``tk.StringVar`` to wrap.

    Returns:
        List of ``ThreadSafeSlotVar`` wrappers.
    """
    return [ThreadSafeSlotVar(root, var) for var in slot_vars]
