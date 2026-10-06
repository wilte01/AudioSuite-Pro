"""
tool_launcher.py — Standalone processing launchers extracted from AudioSuiteDriver.

Contains the accent-colour helper and all Refinery / Enrich / Utility
processing functions that were originally methods on AudioSuiteDriver.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from collections.abc import Sequence
from tkinter import messagebox
from typing import Any, Callable, Optional, cast

from audio_refinery.core.models import StageConfig
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared import ui_common
from audio_suite_shared.tool_plugin import ToolManifest, get_registry

from .batch_orchestrator import BatchProgress
from .runner import arg_builder, module_runner
from .state.app_state import AppState

_log = logging.getLogger(__name__)


def _after(root: tk.Tk, func: Callable[[], object]) -> None:
    root.after(0, func)


def _get_current_accent() -> str | None:
    """Return the current Windows accent_normal hex string, or None."""
    try:
        import winaccent

        return cast(str, winaccent.accent_normal)
    except Exception as _exc:
        _log.debug("winaccent unavailable: %s", _exc)
        return None


# ── Refinery processing ───────────────────────────────────────────────────


def launch_refinery(
    state: AppState,
    config: StageConfig,
    refine_btn: tk.Button,
    root: tk.Tk,
) -> None:
    """Validate inputs and start the Refinery pipeline in a daemon thread."""
    source = state.refinery_source.get().strip()
    if not source:
        ui_common.show_message(
            root,
            "No Source Folder",
            "Please select a source folder for the Refinery.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    if not os.path.isdir(source):
        ui_common.show_message(
            root,
            "Directory Not Found",
            f"The selected folder does not exist:\n\n{source}\n\n"
            "Please select a valid source folder.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    stages_active = any(
        [
            config.declick,
            config.trim,
            config.enhance,
            config.normalise,
            config.reduce_noise,
        ]
    )
    if not stages_active:
        ui_common.show_message(
            root,
            "No Stages Selected",
            "Please enable at least one Refinery stage.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    # Snapshot tkinter variables on main thread before spawning daemon thread
    snapshot_clear_logs = state.clear_logs_var.get()
    snapshot_source = state.refinery_source.get().strip()

    # Build the argv here, on the main thread: build_refinery_args reads live
    # widget state, and an edit made while the batch is launching must not
    # change the run already in flight (audit H4). The thread receives the
    # finished spec list, not `state`.
    specs = _resolved_specs(
        arg_builder.build_refinery_args(state, config),
        tool_env=arg_builder.get_fingerprinter_api_key_env(state),
    )

    # Persist settings so standalone app stays in sync
    from .ui import refinery_tab

    refinery_tab.save_settings(config)
    _suite_config.save_last_directory(snapshot_source)
    threading.Thread(
        target=lambda: _run_refinery(
            specs,
            refine_btn,
            root,
            snapshot_clear_logs=snapshot_clear_logs,
            snapshot_source=snapshot_source,
        ),
        daemon=True,
    ).start()


def _resolved_specs(
    specs: Sequence[tuple[Any, ToolManifest, list[str]]],
    tool_env: dict[str, dict[str, str]] | None = None,
) -> list[tuple[bool, ToolManifest, list[str], dict[str, str] | None]]:
    """Replace each toggle variable with its current value.

    Called on the main thread so the worker's spec list holds no Tk variable:
    ``run_modules`` then never calls ``.get()`` off-thread.

    Args:
        specs: Raw specs from the arg builder (toggle, manifest, args).
        tool_env: Optional mapping of tool_id → env dict for subprocess
            environment variables (e.g. the AcoustID API key).

    Returns:
        Resolved specs as (enabled, manifest, args, env) tuples.
    """
    return [
        (bool(toggle.get()), manifest, args, (tool_env or {}).get(manifest.id))
        for toggle, manifest, args in specs
    ]


def _run_refinery(
    specs: Sequence[tuple[bool, ToolManifest, list[str], dict[str, str] | None]],
    refine_btn: tk.Button,
    root: tk.Tk,
    *,
    snapshot_clear_logs: bool = False,
    snapshot_source: str = "",
) -> None:
    module_runner.run_modules(
        module_specs=specs,
        clear_logs=snapshot_clear_logs,
        dir_path=snapshot_source,
        on_start=lambda: _after(
            root, lambda: refine_btn.config(state="disabled", text="REFINING...")
        ),
        on_complete=lambda executed: _on_refinery_complete(executed, refine_btn, root),
        on_error=lambda t, m: _after(root, lambda: messagebox.showerror(t, m)),
    )


def _on_refinery_complete(
    executed: int,
    refine_btn: tk.Button,
    root: tk.Tk,
) -> None:
    def _update() -> None:
        refine_btn.config(state="normal", text="LAUNCH REFINERY")
        if executed == 0:
            ui_common.show_message(
                root, "Complete", "No Refinery stages were executed."
            )

    root.after(0, _update)


# ── Enrich processing ─────────────────────────────────────────────────────


def launch_enrich(
    state: AppState,
    run_btn: tk.Button,
    root: tk.Tk,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    on_batch_done: Optional[Callable[[], None]] = None,
) -> None:
    """Validate inputs and start the Enrich pipeline in a daemon thread."""
    if not state.dir_path.get():
        ui_common.show_message(
            root,
            "No Directory",
            "Please select a directory first.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    if not os.path.isdir(state.dir_path.get()):
        ui_common.show_message(
            root,
            "Directory Not Found",
            f"The selected directory does not exist:\n\n{state.dir_path.get()}\n\n"
            "Please select a valid directory.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    # Snapshot tkinter variables on main thread before spawning daemon thread
    snapshot_dir = state.dir_path.get()
    snapshot_clear_logs = state.clear_logs_var.get()
    snapshot_parallel = state.parallel_var.get()

    # Built on the main thread; the thread receives the finished list.
    specs = _resolved_specs(
        arg_builder.build_enrich_args(state),
        tool_env=arg_builder.get_fingerprinter_api_key_env(state),
    )

    _suite_config.save_last_directory(snapshot_dir)
    threading.Thread(
        target=lambda: _run_enrich(
            specs,
            run_btn,
            root,
            progress_callback=progress_callback,
            on_batch_done=on_batch_done,
            parallel=snapshot_parallel,
            snapshot_clear_logs=snapshot_clear_logs,
            snapshot_dir=snapshot_dir,
        ),
        daemon=True,
    ).start()


def _run_enrich(
    specs: Sequence[tuple[bool, ToolManifest, list[str], dict[str, str] | None]],
    run_btn: tk.Button,
    root: tk.Tk,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    on_batch_done: Optional[Callable[[], None]] = None,
    parallel: bool = False,
    snapshot_clear_logs: bool = False,
    snapshot_dir: str = "",
) -> None:
    module_runner.run_modules(
        module_specs=specs,
        clear_logs=snapshot_clear_logs,
        dir_path=snapshot_dir,
        on_start=lambda: _after(
            root, lambda: run_btn.config(state="disabled", text="PROCESSING...")
        ),
        on_complete=lambda executed: _on_enrich_complete(
            executed,
            run_btn,
            root,
            on_batch_done=on_batch_done,
        ),
        on_error=lambda t, m: _after(root, lambda: messagebox.showerror(t, m)),
        progress_callback=progress_callback,
        parallel=parallel,
    )


def _on_enrich_complete(
    executed: int,
    run_btn: tk.Button,
    root: tk.Tk,
    *,
    on_batch_done: Optional[Callable[[], None]] = None,
) -> None:
    root.after(
        0,
        lambda: run_btn.config(state="normal", text="LAUNCH ENRICH PROCESS"),
    )
    if on_batch_done:
        root.after(0, on_batch_done)


# ── Utility processing ────────────────────────────────────────────────────


def launch_utility(
    state: AppState,
    util_run_btn: tk.Button,
    root: tk.Tk,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    on_batch_done: Optional[Callable[[], None]] = None,
) -> None:
    """Validate inputs and start the Utility pipeline in a daemon thread."""
    # Classification is derived from the registry manifests so newly
    # registered tools are picked up automatically: tools flagged
    # standalone open their own window; all others need a directory path.
    utility_manifests = get_registry().by_category("utility")
    needs_dir = any(
        state.module_toggles[m.id].get() for m in utility_manifests if not m.standalone
    )
    has_standalone = any(
        state.module_toggles[m.id].get() for m in utility_manifests if m.standalone
    )

    if needs_dir and not state.dir_path.get():
        ui_common.show_message(
            root,
            "No Directory",
            "Please select a directory first.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return
    if not needs_dir and not has_standalone:
        ui_common.show_message(
            root,
            "Nothing Selected",
            "Please select at least one utility.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    if needs_dir and not os.path.isdir(state.dir_path.get()):
        ui_common.show_message(
            root,
            "Directory Not Found",
            f"The selected directory does not exist:\n\n{state.dir_path.get()}\n\n"
            "Please select a valid directory.",
            icon="\u26a0",
            icon_color="#d97706",
        )
        return

    # Snapshot tkinter variables on main thread before spawning daemon thread
    snapshot_dir = state.dir_path.get()
    snapshot_clear_logs = state.util_clear_logs_var.get()
    snapshot_parallel = state.parallel_var.get()

    # Built on the main thread; the thread receives the finished list.
    specs = _resolved_specs(arg_builder.build_utility_args(state))

    _suite_config.save_last_directory(snapshot_dir)
    threading.Thread(
        target=lambda: _run_utility_modules(
            specs,
            util_run_btn,
            root,
            progress_callback=progress_callback,
            on_batch_done=on_batch_done,
            parallel=snapshot_parallel,
            snapshot_clear_logs=snapshot_clear_logs,
            snapshot_dir=snapshot_dir,
        ),
        daemon=True,
    ).start()


def _run_utility_modules(
    specs: Sequence[tuple[bool, ToolManifest, list[str], dict[str, str] | None]],
    util_run_btn: tk.Button,
    root: tk.Tk,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    on_batch_done: Optional[Callable[[], None]] = None,
    parallel: bool = False,
    snapshot_clear_logs: bool = False,
    snapshot_dir: str = "",
) -> None:
    module_runner.run_modules(
        module_specs=specs,
        clear_logs=snapshot_clear_logs,
        dir_path=snapshot_dir,
        on_start=lambda: _after(
            root, lambda: util_run_btn.config(state="disabled", text="PROCESSING...")
        ),
        on_complete=lambda executed: _on_utility_complete(
            executed,
            util_run_btn,
            root,
            on_batch_done=on_batch_done,
        ),
        on_error=lambda t, m: _after(root, lambda: messagebox.showerror(t, m)),
        progress_callback=progress_callback,
        parallel=parallel,
    )


def _on_utility_complete(
    executed: int,
    util_run_btn: tk.Button,
    root: tk.Tk,
    *,
    on_batch_done: Optional[Callable[[], None]] = None,
) -> None:
    root.after(
        0,
        lambda: util_run_btn.config(state="normal", text="LAUNCH UTILITY PROCESS"),
    )
    if on_batch_done:
        root.after(0, on_batch_done)
