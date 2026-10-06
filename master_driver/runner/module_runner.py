"""
module_runner.py — Subprocess execution and log clearing.

Input is a list of (enabled, ToolManifest, args) tuples produced by
arg_builder.py and resolved by the launcher on the Tk main thread.  The
manifest replaces the old sentinel-string approach: manifest.standalone
controls whether the tool is launched as a standalone window or as a
blocking subprocess.

Both sequential and parallel execution delegate to
:class:`~master_driver.batch_orchestrator.BatchOrchestrator`.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from typing import Any, Callable, Optional

from audio_suite_shared.tool_plugin import ToolManifest

from ..batch_orchestrator import (
    BatchOrchestrator,
    BatchProgress,
    BatchStep,
    StepStatus,
    _launch_standalone,  # noqa: F401 — re-exported for identity test
)

logger = logging.getLogger(__name__)


def _clear_logs(
    path: str, on_error: Optional[Callable[[str, str], None]] = None
) -> None:
    """Delete all .txt files in the given directory."""

    def _err(title: str, msg: str) -> None:
        if on_error:
            on_error(title, msg)

    try:
        for item in os.listdir(path):
            if item.lower().endswith(".txt"):
                try:
                    os.remove(os.path.join(path, item))
                except PermissionError as e:
                    _err("Permission Denied", f"Cannot delete log file:\n{item}\n\n{e}")
                except OSError as e:
                    _err("File Error", f"Cannot delete log file:\n{item}\n\n{e}")
    except OSError as exc:
        _err("Log Clear Error", f"Could not access directory:\n{path}\n\n{exc}")


def _suite_root() -> str:
    """Return the absolute path of the suite root directory.

    File location: suite_root/master_driver/runner/module_runner.py
    So __file__ -> runner/ -> master_driver/ -> suite_root/
    """
    return os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )


def run_modules(
    module_specs: Sequence[tuple[Any, ToolManifest, list[str], dict[str, str] | None]],
    clear_logs: bool,
    dir_path: str,
    on_start: Callable[[], None],
    on_complete: Callable[[int], None],
    on_error: Optional[Callable[[str, str], None]] = None,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    parallel: bool = False,
    max_workers: int = 2,
) -> None:
    """
    Execute enabled modules sequentially, then call on_complete(executed_count).

    Each tuple in *module_specs* must be ``(enabled, ToolManifest, args)``.

    ``enabled`` is the toggle's value already resolved by the caller on the
    Tk main thread; a Tk variable is still tolerated for direct callers, but
    the launchers never pass one, so no ``.get()`` runs on the worker.

    Dispatch logic:
        manifest.standalone == True  → launch via start_python_script (non-blocking)
        manifest.standalone == False → run via run_python_script (blocking)

    When *progress_callback* is provided, ``BatchProgress`` snapshots are
    emitted before the first step, after each step, and after the batch.
    The actual subprocess execution is **identical** to the no-callback path.
    """
    on_start()
    root = _suite_root()

    # ── Extract the active specs into a flat list ──────────────────────────
    specs: list[tuple[ToolManifest, list[str], Any, dict[str, str] | None]] = []
    for item in module_specs:
        enabled = item[0]
        spec = item[1]
        args = item[2] if len(item) > 2 else []
        env = item[3] if len(item) > 3 else None

        # The launcher resolved every toggle on the main thread, so the common
        # path is a plain bool. A Tk variable is accepted for direct callers.
        if not (enabled if isinstance(enabled, bool) else bool(enabled.get())):
            continue

        # Accept ToolManifest specs (legacy str specs were removed in E4)
        if isinstance(spec, ToolManifest):
            manifest = spec
        else:
            if on_error:
                on_error(
                    "Plugin Error",
                    f"Invalid module spec: expected ToolManifest, "
                    f"got {type(spec).__name__}",
                )
            continue

        specs.append((manifest, args, enabled, env))

    # ═══════════════════════════════════════════════════════════════════════
    # Dispatch: both modes delegate to BatchOrchestrator.
    # ═══════════════════════════════════════════════════════════════════════

    if parallel:
        _run_modules_parallel(
            specs,
            root,
            on_error,
            on_complete,
            clear_logs,
            dir_path,
            progress_callback=progress_callback,
            max_workers=max_workers,
        )
        return

    _run_modules_sequential(
        specs,
        root,
        on_error,
        on_complete,
        clear_logs,
        dir_path,
        progress_callback=progress_callback,
    )


def _run_modules_sequential(
    specs: list[tuple[ToolManifest, list[str], object, dict[str, str] | None]],
    root: str,
    on_error: Optional[Callable[[str, str], None]],
    on_complete: Callable[[int], None],
    clear_logs: bool,
    dir_path: str,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
) -> None:
    """Sequential execution — delegates to :class:`BatchOrchestrator`.

    Error reporting and log-clearing are handled here; the orchestrator
    owns the execution loop, retry logic, and progress emission.
    """
    steps: list[BatchStep] = []
    for manifest, args, _toggle, env in specs:
        step = BatchStep.from_spec(
            tool_id=manifest.id,
            manifest=manifest,
            args=args,
            suite_root=root,
        )
        step.env = env
        steps.append(step)

    orchestrator = BatchOrchestrator(steps)
    report = orchestrator.run(progress_callback=progress_callback)

    if on_error:
        for step in report.steps:
            if step.status == StepStatus.FAILED:
                if not os.path.exists(step.script_path):
                    on_error(
                        "Module Not Found",
                        f"Module not found:\n{step.script_path}\n\n"
                        f"Please ensure all Audio Suite modules are present "
                        f"in the suite root folder.",
                    )
                else:
                    on_error(
                        "Module Error",
                        f"Module failed: {step.manifest.name}",
                    )

    _finalise(report.completed, clear_logs, dir_path, on_complete, on_error)


def _run_modules_parallel(
    specs: list[tuple[ToolManifest, list[str], object, dict[str, str] | None]],
    root: str,
    on_error: Optional[Callable[[str, str], None]],
    on_complete: Callable[[int], None],
    clear_logs: bool,
    dir_path: str,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
    max_workers: int = 2,
) -> None:
    """Parallel execution via BatchOrchestrator with dependency graph."""
    steps: list[BatchStep] = []
    for manifest, args, _toggle, env in specs:
        step = BatchStep.from_spec(
            tool_id=manifest.id,
            manifest=manifest,
            args=args,
            suite_root=root,
        )
        step.env = env
        steps.append(step)

    orchestrator = BatchOrchestrator(steps)

    _actual_progress_cb = progress_callback

    def _on_progress(p: BatchProgress) -> None:
        if _actual_progress_cb is not None:
            _actual_progress_cb(p)

    report = orchestrator.run(
        parallel=True,
        max_workers=max_workers,
        progress_callback=_on_progress,
    )

    if on_error:
        for step in report.steps:
            if step.status == StepStatus.FAILED:
                on_error(
                    "Module Error",
                    f"Module failed: {step.manifest.name}",
                )

    _finalise(report.completed, clear_logs, dir_path, on_complete, on_error)


def _finalise(
    executed: int,
    clear_logs: bool,
    dir_path: str,
    on_complete: Callable[[int], None],
    on_error: Optional[Callable[[str, str], None]],
) -> None:
    """Clear logs if requested and call on_complete."""
    if clear_logs and dir_path:
        _clear_logs(dir_path, on_error=on_error)
    on_complete(executed)
