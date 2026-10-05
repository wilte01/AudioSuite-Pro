"""
module_runner.py — Sequential subprocess execution and log clearing.

Input is a list of (enabled, ToolManifest, args) tuples produced by
arg_builder.py and resolved by the launcher on the Tk main thread.  The
manifest replaces the old sentinel-string approach: manifest.standalone
controls whether the tool is launched as a standalone window or as a
blocking subprocess.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from collections.abc import Sequence
from typing import Any, Callable, Optional

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_python_script,
    start_python_script,
)
from audio_suite_shared.tool_plugin import ToolManifest

from ..batch_orchestrator import (
    BatchOrchestrator,
    BatchProgress,
    BatchStep,
    StepStatus,
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
    module_specs: Sequence[tuple[Any, ToolManifest, list[str]]],
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
    specs: list[tuple[ToolManifest, list[str], Any]] = []
    for item in module_specs:
        enabled = item[0]
        spec = item[1]
        args = item[2] if len(item) > 2 else []

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

        specs.append((manifest, args, enabled))

    # ═══════════════════════════════════════════════════════════════════════
    # Dispatch: parallel (orchestrator) or sequential (legacy loop).
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
    specs: list[tuple[ToolManifest, list[str], object]],
    root: str,
    on_error: Optional[Callable[[str, str], None]],
    on_complete: Callable[[int], None],
    clear_logs: bool,
    dir_path: str,
    *,
    progress_callback: Optional[Callable[[BatchProgress], None]] = None,
) -> None:
    """Sequential execution — identical to the original legacy loop,
    with optional progress events."""
    executed = 0
    total = len(specs)
    failed_steps: list[str] = []
    batch_start = time.monotonic()
    step_times: list[float] = []
    all_step_identities: list[tuple[str, str]] = [(m.id, m.name) for m, _a, _t in specs]

    for idx, (manifest, args, _toggle) in enumerate(specs):
        tool_id = manifest.id
        step_start = time.monotonic()

        _emit_progress(
            callback=progress_callback,
            total_steps=total,
            completed_steps=executed,
            current_step=tool_id,
            failed=failed_steps,
            batch_start=batch_start,
            step_times=step_times,
            all_step_identities=all_step_identities,
        )

        script = manifest.pyw_filename
        if not os.path.isabs(script):
            full_path = os.path.join(root, script)
        else:
            full_path = script

        if not os.path.exists(full_path):
            if on_error:
                on_error(
                    "Module Not Found",
                    f"Module not found:\n{full_path}\n\n"
                    f"Please ensure all Audio Suite modules are present "
                    f"in the suite root folder.",
                )
            # Record the tool as failed and emit its status line before
            # continuing. Without both, `_emit_progress`'s index-based mapping
            # (`i < completed_steps`) later renders this step as "completed"
            # once a *later* step finishes, because `executed` never advanced
            # for it and it was in neither `failed` nor the finished prefix.
            failed_steps.append(tool_id)
            step_times.append(time.monotonic() - step_start)
            _emit_progress(
                callback=progress_callback,
                total_steps=total,
                completed_steps=executed,
                current_step=tool_id,
                failed=failed_steps,
                batch_start=batch_start,
                step_times=step_times,
                all_step_identities=all_step_identities,
            )
            continue

        if manifest.standalone:
            if _launch_standalone(full_path, args, manifest.name, on_error=on_error):
                executed += 1
            else:
                failed_steps.append(tool_id)
        else:
            try:
                result = run_python_script(full_path, args)
                if result.returncode == 0:
                    executed += 1
                else:
                    logger.warning(
                        "Module exited with non-zero code %d: %s",
                        result.returncode,
                        manifest.name,
                    )
                    if on_error:
                        on_error(
                            "Module Error",
                            f"Module exited with error code {result.returncode}:\n"
                            f"{manifest.name}",
                        )
                    failed_steps.append(tool_id)
            except SubprocessSecurityError as exc:
                if on_error:
                    on_error(
                        "Security Error",
                        f"Cannot run module due to security restrictions:\n"
                        f"{manifest.name}\n\n{exc}",
                    )
                failed_steps.append(tool_id)
            except subprocess.CalledProcessError as exc:
                if on_error:
                    on_error(
                        "Module Error",
                        f"Module exited with error code {exc.returncode}:\n"
                        f"{manifest.name}",
                    )
                failed_steps.append(tool_id)
            except (PermissionError, FileNotFoundError, OSError) as exc:
                if on_error:
                    on_error(
                        "Execution Error",
                        f"Cannot run module:\n{manifest.name}\n\n{exc}",
                    )
                failed_steps.append(tool_id)

        step_times.append(time.monotonic() - step_start)
        _emit_progress(
            callback=progress_callback,
            total_steps=total,
            completed_steps=executed,
            current_step=tool_id,
            failed=failed_steps,
            batch_start=batch_start,
            step_times=step_times,
            all_step_identities=all_step_identities,
        )

    _finalise(executed, clear_logs, dir_path, on_complete, on_error)


def _run_modules_parallel(
    specs: list[tuple[ToolManifest, list[str], object]],
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
    for manifest, args, _toggle in specs:
        step = BatchStep.from_spec(
            tool_id=manifest.id,
            manifest=manifest,
            args=args,
            suite_root=root,
        )
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


def _emit_progress(
    callback: Optional[Callable[[BatchProgress], None]],
    total_steps: int,
    completed_steps: int,
    current_step: str,
    failed: list[str],
    *,
    batch_start: float = 0.0,
    step_times: list[float] | None = None,
    all_step_identities: list[tuple[str, str]] | None = None,
) -> None:
    """Build and send a BatchProgress snapshot if a callback is registered."""
    if callback is None:
        return
    from datetime import timedelta

    elapsed_secs = time.monotonic() - batch_start if batch_start else 0.0
    elapsed = timedelta(seconds=int(elapsed_secs))

    remaining = total_steps - completed_steps
    estimated_remaining_secs = 0.0
    if step_times and remaining > 0:
        avg = sum(step_times) / len(step_times)
        estimated_remaining_secs = avg * remaining
    estimated_remaining = timedelta(seconds=int(estimated_remaining_secs))

    # Build per-step status list for the UI
    steps_list: list[tuple[str, str, str]] = []
    for i, (tid, name) in enumerate(all_step_identities or []):
        if tid in failed:
            steps_list.append((tid, name, "failed"))
        elif i < completed_steps:
            steps_list.append((tid, name, "completed"))
        elif tid == current_step:
            steps_list.append((tid, name, "running"))
        else:
            steps_list.append((tid, name, "pending"))

    progress = BatchProgress(
        total_steps=total_steps,
        completed_steps=completed_steps,
        current_step=current_step,
        current_progress=(completed_steps / total_steps if total_steps > 0 else 0.0),
        elapsed=elapsed,
        estimated_remaining=estimated_remaining,
        failed_steps=list(failed),
        running_steps=[],
        pending_steps=[],
        steps=steps_list,
    )
    callback(progress)


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


def _launch_standalone(
    script: str,
    args: list[str],
    label: str,
    on_error: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Launch a standalone .pyw script and wait for it to close.

    Returns True if the script was found and launched successfully,
    False otherwise.
    """

    def _err(title: str, msg: str) -> None:
        if on_error:
            on_error(title, msg)

    if not os.path.exists(script):
        _err(
            f"{label} — Not Found",
            f"Could not launch {label}.\n\n"
            f"Expected location:\n{script}\n\n"
            f"Please ensure all Audio Suite modules are present "
            f"in the suite root folder.",
        )
        return False

    try:
        process = start_python_script(script, args)
        process.wait()
        if process.returncode != 0:
            _err(
                f"{label} — Error",
                f"{label} exited with error code {process.returncode}.",
            )
            return False
        return True
    except SubprocessSecurityError as exc:
        _err(
            f"{label} — Security Error",
            f"Security restrictions prevented launching {label}:\n\n{exc}",
        )
        return False
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        _err(
            f"{label} — Launch Error",
            f"An error occurred while launching {label}:\n\n{user_message_for(mapped)}",
        )
        return False
