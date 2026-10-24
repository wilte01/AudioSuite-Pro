"""
batch_orchestrator.py — Unified batch queue with progress tracking,
dependency-aware parallel execution, and per-step retry.

Replaces the simple sequential loop in module_runner.py with a proper
orchestrator that emits progress callbacks for live UI updates.

Changed in 1.0.1: a step whose script is missing (FileNotFoundError) now
fails immediately with a "Script not found" warning instead of being
retried as a generic OSError and logged as "failed after retries".
Changed in 1.2.0: carries a per-step ``note`` from
:mod:`audio_suite_shared.run_outcome` into ``BatchProgress``, so a step that
completed with a caveat (e.g. a rejected ISRC submission) says so in the batch
report.  The note never changes the step's status.
Changed in 1.3.0: adds ``spectral_viewer`` to the dependency graph as a leaf
that runs after analysis, because it only reads what the analyzers wrote.
Changed in 1.4.1: ``BatchProgress.verdict`` derives one closing line from every
step note, so a long batch can be judged from one line instead of from each
step's line (PLAN D110).
Changed in 2.0.0: adds ``stem_separator`` to the dependency graph as a leaf
(Sprint 6, Item 6.1).
Changed in 2.0.0: adds ``ml_denoiser`` as a leaf (Item 6.2).  It rewrites the
files already in the directory, so it depends on nothing another tool produces
and imposes no ordering on the rest of the batch.
Changed in 2.1.0: a standalone step records the launcher's exit code on
``BatchStep.exit_code`` (the module-level ``_launch_standalone`` reports it
through ``on_exit``).  Without it the caller's summary was a bare "Module
failed: <name>" naming no reason, which is how a plugin launcher that raised
``ModuleNotFoundError`` read to the user (``PLAN_feature_expansion.md`` D135).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from audio_suite_shared.error_recovery import RetryConfig, retry_with_backoff
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.run_outcome import clear_outcome, read_outcome
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_python_script,
    start_python_script,
)
from audio_suite_shared.tool_plugin import ToolManifest

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class BatchStep:
    """A single tool invocation within a batch."""

    tool_id: str
    manifest: ToolManifest
    script_path: str
    args: list[str]
    env: dict[str, str] | None = None
    status: StepStatus = StepStatus.PENDING
    start_time: float | None = None
    end_time: float | None = None
    exit_code: int | None = None
    log_output: str = ""
    retry_count: int = 0
    note: str = ""
    """One-line caveat the tool recorded for this run (empty when none).

    Read from :mod:`audio_suite_shared.run_outcome` after a successful step;
    informational only, so it is never counted as a failure.
    """

    @property
    def duration(self) -> float | None:
        if self.start_time is not None and self.end_time is not None:
            return self.end_time - self.start_time
        return None

    @classmethod
    def from_spec(
        cls,
        tool_id: str,
        manifest: ToolManifest,
        args: list[str],
        suite_root: str = "",
    ) -> BatchStep:
        script = manifest.pyw_filename
        if suite_root and not os.path.isabs(script):
            script = os.path.join(suite_root, script)
        return cls(
            tool_id=tool_id,
            manifest=manifest,
            script_path=script,
            args=args,
        )


#: Longest verdict line kept.  The report is a text panel sized for one line
#: per step, so a statement that grew with the number of caveats would push the
#: steps out of view; whole clauses are dropped past this length instead.
VERDICT_MAX_CHARS = 400


@dataclass(frozen=True)
class BatchProgress:
    """Snapshot of batch progress, emitted via callback."""

    total_steps: int
    completed_steps: int
    current_step: str | None
    current_progress: float
    elapsed: timedelta
    estimated_remaining: timedelta
    failed_steps: list[str]
    running_steps: list[str]
    pending_steps: list[str]
    steps: list[tuple[str, str, str]] = field(default_factory=list)
    """Per-step status list: [(tool_id, name, status_str), ...]"""

    notes: dict[str, str] = field(default_factory=dict)
    """tool_id to the caveat that step recorded, for steps that recorded one.

    The per-step lines read this dict; :attr:`verdict` folds it into one line.
    """

    @property
    def finished(self) -> bool:
        """Whether every step in this snapshot reached a terminal status.

        Returns:
            ``True`` when nothing is still pending or running.
        """
        return not self.pending_steps and not self.running_steps

    @property
    def verdict(self) -> str:
        """Return one line summarising every note this batch recorded.

        A twelve-step batch puts its caveats on twelve separate lines, so
        judging the run means scanning all of them.  This folds them into one
        closing statement that names each tool with a caveat, in run order,
        and leads with the failure count when steps failed, so the line stands
        on its own.

        Empty while the batch is unfinished (a verdict may not describe a run
        that is still going) and empty for a batch that recorded no notes (a
        clean run has nothing to say, and the report is only kept on screen
        for a verdict worth reading).

        The line is bounded by :data:`VERDICT_MAX_CHARS`.  When the clauses do
        not fit, whole clauses are dropped from the end and the remainder is
        counted, because a clause cut mid-sentence reads as a different caveat;
        every note stays visible in full on its own step line.

        Returns:
            The verdict line, or ``""`` when there is nothing to report.
        """
        if not self.finished or not self.notes:
            return ""
        caveats = [
            f"{name}: {self.notes[tool_id]}"
            for tool_id, name, _status in self.steps
            if tool_id in self.notes
        ]
        if not caveats:
            # Notes for tools that are not steps in this batch: nothing this
            # line could truthfully attribute.
            return ""
        noun = "step" if self.total_steps == 1 else "steps"
        head = "Batch verdict: "
        if self.failed_steps:
            head += f"{len(self.failed_steps)} failed \u00b7 "
        head += f"{len(caveats)} of {self.total_steps} {noun} completed with caveats"
        separator = " \u2014 "

        line = head + separator + "; ".join(caveats)
        if len(line) <= VERDICT_MAX_CHARS:
            return line

        kept: list[str] = []
        for clause in caveats:
            omitted = len(caveats) - len(kept) - 1
            tail = f"; +{omitted} more" if omitted else ""
            candidate = head + separator + "; ".join([*kept, clause]) + tail
            if len(candidate) > VERDICT_MAX_CHARS:
                break
            kept.append(clause)
        if not kept:
            # Not even the first clause fits: shorten it rather than say
            # nothing, since which step it belongs to is the useful part.
            room = VERDICT_MAX_CHARS - len(head) - len(separator) - len("...")
            return f"{head}{separator}{caveats[0][: max(room, 1)].rstrip()}..."
        return (
            head + separator + "; ".join(kept) + f"; +{len(caveats) - len(kept)} more"
        )


@dataclass(frozen=True)
class BatchReport:
    """Final report returned after batch execution."""

    total: int
    completed: int
    failed: int
    skipped: int
    steps: list[BatchStep]
    total_elapsed: timedelta


# ---------------------------------------------------------------------------
# Dependency graph for parallel execution
# ---------------------------------------------------------------------------

DEPENDENCY_GRAPH: dict[str, list[str]] = {
    "tempo": ["bpm"],
    "genre_sync": [],
    "fingerprinter": [],
    "replaygain": [],
    "scrubber": [],
    "art": [],
    "album_genre": [],
    "bpm": [],
    "key": [],
    "mood_analyzer": [],
    "converter": [],
    "asx_extractor": [],
    "album_art_normalizer": [],
    "cd_ripper": [],
    "mood_analysis_batch": [],
    "noise_reduction": [],
    "library_stats": [],
    "spectral_viewer": [],
    "file_reorganizer": [],
    "lyrics_manager": [],
    "audio_refinery": [],
    "audio_enhancer": [],
    "audio_normalizer": [],
    "pop_click_remover": [],
    "tag_field_updater": [],
    "silence_trimmer": [],
    "stem_separator": [],
    "ml_denoiser": [],
    "tag_editor": [],
}


def _resolve_dependencies(
    tool_ids: list[str],
) -> dict[str, set[str]]:
    """Resolve full transitive dependency closure for the given tool ids."""
    resolved: dict[str, set[str]] = {}
    for tid in tool_ids:
        deps: set[str] = set()
        _collect_deps(tid, deps, tool_ids)
        resolved[tid] = deps
    return resolved


def _collect_deps(
    tool_id: str,
    collected: set[str],
    available: list[str],
    visited: set[str] | None = None,
    _stack: set[str] | None = None,
) -> None:
    if visited is None:
        visited = set()
    if _stack is None:
        _stack = set()
    if tool_id in _stack:
        raise ValueError(f"Circular dependency detected involving tool '{tool_id}'")
    if tool_id in visited:
        return
    _stack.add(tool_id)
    visited.add(tool_id)
    for dep in DEPENDENCY_GRAPH.get(tool_id, []):
        if dep in available and dep not in collected:
            collected.add(dep)
            _collect_deps(dep, collected, available, visited, _stack)
    _stack.discard(tool_id)


# ---------------------------------------------------------------------------
# Shared standalone launcher
# ---------------------------------------------------------------------------


def _launch_standalone(
    script_path: str,
    args: list[str],
    label: str,
    *,
    on_error: Callable[[str, str], None] | None = None,
    on_exit: Callable[[int], None] | None = None,
) -> bool:
    """Launch a standalone .pyw script and wait for it to close.

    This is the single authoritative implementation used by both
    :class:`BatchOrchestrator` and :func:`module_runner.run_modules`.

    Args:
        script_path: The launcher to run.
        args: Arguments forwarded to it.
        label: Name used in the error dialogs and the log line.
        on_error: Callable(title, message) reporting a launch failure.
        on_exit: Callable(code) receiving the launcher's exit code as soon as
            the window closes, so the caller can keep it for its own report.

    Returns ``True`` if the script was found, launched, and exited with
    code 0.  Returns ``False`` otherwise.
    """

    def _err(title: str, msg: str) -> None:
        if on_error:
            on_error(title, msg)

    if not os.path.exists(script_path):
        logger.warning("Script not found: %s", script_path)
        _err(
            f"{label} — Not Found",
            f"Could not launch {label}.\n\n"
            f"Expected location:\n{script_path}\n\n"
            f"Please ensure all Audio Suite modules are present "
            f"in the suite root folder.",
        )
        return False

    try:
        process = start_python_script(script_path, args)
        process.wait()
        if on_exit is not None:
            on_exit(process.returncode)
        if process.returncode != 0:
            logger.warning(
                "Standalone %s exited with code %d",
                label,
                process.returncode,
            )
            _err(
                f"{label} — Error",
                f"{label} exited with error code {process.returncode}.",
            )
            return False
        return True
    except SubprocessSecurityError as exc:
        logger.warning("Security error for %s: %s", label, exc)
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


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class BatchOrchestrator:
    """Orchestrates a sequence of enrichment/utility steps with progress
    tracking, estimated time remaining, and per-step retry logic.

    Usage::

        specs = [
            BatchStep.from_spec("bpm", manifest, ["/music", ...]),
            ...
        ]
        orch = BatchOrchestrator(specs)
        report = orch.run(parallel=False, progress_callback=my_cb)
    """

    def __init__(self, steps: list[BatchStep]) -> None:
        self._steps = steps
        self._start_time: float | None = None

    # ── Public API ─────────────────────────────────────────────────────────

    def run(
        self,
        *,
        parallel: bool = False,
        max_workers: int = 2,
        progress_callback: Callable[[BatchProgress], None] | None = None,
    ) -> BatchReport:
        """Execute all steps and return a report.

        Args:
            parallel: When True, independent steps run concurrently using
                      a ``ThreadPoolExecutor`` subject to the dependency graph.
            max_workers: Max concurrent subprocesses (ignored in sequential mode).
            progress_callback: Called after each step completes (or fails) with a
                               ``BatchProgress`` snapshot.

        Returns:
            A ``BatchReport`` with per-step results and aggregate counts.
        """
        self._start_time = time.monotonic()
        total = len(self._steps)
        completed_count = 0
        failed_steps: list[str] = []

        if parallel:
            return self._run_parallel(
                total, max_workers, progress_callback, completed_count, failed_steps
            )

        return self._run_sequential(
            total, progress_callback, completed_count, failed_steps
        )

    def _run_sequential(
        self,
        total: int,
        progress_callback: Callable[[BatchProgress], None] | None,
        completed_count: int,
        failed_steps: list[str],
    ) -> BatchReport:
        for step in self._steps:
            if step.status == StepStatus.SKIPPED:
                continue

            step.status = StepStatus.RUNNING
            step.start_time = time.monotonic()
            self._emit_progress(
                step, total, completed_count, failed_steps, progress_callback
            )

            success = self._execute_with_retry(step)

            if success:
                step.status = StepStatus.COMPLETED
                completed_count += 1
            else:
                step.status = StepStatus.FAILED
                failed_steps.append(step.tool_id)

            step.end_time = time.monotonic()
            self._emit_progress(
                step, total, completed_count, failed_steps, progress_callback
            )

        return self._build_report(total, completed_count, failed_steps)

    def _run_parallel(
        self,
        total: int,
        max_workers: int,
        progress_callback: Callable[[BatchProgress], None] | None,
        completed_count: int,
        failed_steps: list[str],
    ) -> BatchReport:
        tool_ids = [s.tool_id for s in self._steps]
        dep_map = _resolve_dependencies(tool_ids)
        step_map: dict[str, BatchStep] = {s.tool_id: s for s in self._steps}
        completed: set[str] = set()
        running: set[str] = set()

        # A standalone step is a blocking GUI window, so it cannot be driven
        # concurrently with the rest of the batch. Parallel mode does not launch
        # it (sequential mode does, via _launch_standalone) and the step is
        # reported as SKIPPED — never counted as completed, which would report a
        # tool that never ran as one that did. `skipped_ids` is tracked
        # separately from `completed` because `completed` doubles as the
        # dependency-satisfaction set: a skipped step's dependents must not run
        # either, so they stay PENDING and are reported as not-run.
        skipped_ids: set[str] = set()
        for s in self._steps:
            if s.manifest.standalone:
                s.status = StepStatus.SKIPPED
                s.start_time = time.monotonic()
                s.end_time = time.monotonic()
                skipped_ids.add(s.tool_id)

        if skipped_ids:
            logger.info(
                "Parallel batch skipped %d standalone step(s): %s",
                len(skipped_ids),
                ", ".join(sorted(skipped_ids)),
            )

        def _can_run(tid: str) -> bool:
            return (
                dep_map[tid].issubset(completed)
                and tid not in completed
                and tid not in running
                and tid not in skipped_ids
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures: dict[str, Future[bool]] = {}

            # Keep submitting tasks as dependencies resolve
            while len(completed) + len(skipped_ids) < len(tool_ids):
                for tid in tool_ids:
                    if _can_run(tid) and tid not in futures:
                        step = step_map[tid]
                        step.status = StepStatus.RUNNING
                        step.start_time = time.monotonic()
                        running.add(tid)
                        futures[tid] = executor.submit(self._execute_with_retry, step)

                if not futures:
                    break

                # Wait for any future to complete
                try:
                    for fid in as_completed(futures.values(), timeout=3600):
                        # Find which tid completed
                        for tid, fut in list(futures.items()):
                            if fut == fid:
                                success = fid.result()
                                step = step_map[tid]
                                if success:
                                    step.status = StepStatus.COMPLETED
                                    completed.add(tid)
                                    running.discard(tid)
                                    completed_count += 1
                                else:
                                    step.status = StepStatus.FAILED
                                    failed_steps.append(tid)
                                    completed.add(tid)
                                    running.discard(tid)
                                step.end_time = time.monotonic()
                                self._emit_progress(
                                    step,
                                    total,
                                    completed_count,
                                    failed_steps,
                                    progress_callback,
                                )
                                del futures[tid]
                                break
                        break  # Re-evaluate dependencies after each completion
                except TimeoutError:
                    logger.warning(
                        "Batch timed out waiting for step completion after 3600s"
                    )
                    for tid in list(futures):
                        step = step_map[tid]
                        step.status = StepStatus.FAILED
                        step.end_time = time.monotonic()
                        failed_steps.append(tid)
                        completed.add(tid)
                        running.discard(tid)
                    futures.clear()

        return self._build_report(total, completed_count, failed_steps)

    # ── Internals ────────────────────────────────────────────────────────────

    def _execute_with_retry(self, step: BatchStep) -> bool:
        """Execute a single step with exponential-backoff retry.

        Exceptions from retryable errors (OSError, PermissionError) are
        propagated so that ``retry_with_backoff`` can catch and retry them.
        Non-retryable or final failures are caught and return False.
        ``FileNotFoundError`` is caught before the ``OSError`` arm (it is a
        subclass): a missing script is a deterministic configuration error,
        so it is not retried.
        """

        # A note from an earlier batch must never be shown against this run, so
        # it is cleared before the tool can possibly write a new one.  A tool
        # that records no note therefore reports none.
        try:
            clear_outcome(step.tool_id)
        except ValueError:
            logger.warning("Unusable tool id for a run note: %r", step.tool_id)

        def _run() -> bool:
            if step.manifest.standalone:
                return self._launch_standalone(step)

            # Use plain subprocess.run (no PIPE) — identical to the legacy
            # path in module_runner._run_modules_legacy.  GUI-based tools
            # like ReplayGain can stall when stdout is piped.
            try:
                result = run_python_script(
                    step.script_path,
                    step.args,
                    env=step.env,
                )
                step.exit_code = result.returncode
                if result.returncode == 0:
                    return True
                logger.warning(
                    "Step %s exited with code %d",
                    step.tool_id,
                    result.returncode,
                )
                return False
            except SubprocessSecurityError:
                logger.warning("Security error for %s", step.tool_id)
                return False
            except FileNotFoundError:
                logger.warning("Script not found for %s", step.tool_id)
                return False
            except (PermissionError, OSError):
                logger.warning(
                    "Retryable error for %s",
                    step.tool_id,
                )
                raise

        retry_cfg = RetryConfig(
            max_retries=2,
            retry_delay=2.0,
            backoff_factor=2.0,
            retry_on_exceptions=[OSError, PermissionError],
        )

        try:
            result = retry_with_backoff(
                _run,
                retry_cfg,
                operation_id=step.tool_id,
            )
            success = bool(result)
        except Exception:
            logger.exception("Step %s failed after retries", step.tool_id)
            success = False

        # Only a completed step reports its caveat: a failed step already shows
        # as FAILED, and pairing it with a note about a run that did not finish
        # would describe work this batch never did.
        step.note = read_outcome(step.tool_id) if success else ""
        return success

    def _launch_standalone(self, step: BatchStep) -> bool:
        """Launch standalone — delegates to module-level ``_launch_standalone``.

        The launcher's exit code is recorded on the step as it arrives: the
        module-level function reports its own dialog, so without this the
        caller's later error summary ("Module failed: <name>") would be the
        only evidence left and would name no reason at all.
        """

        def _record(code: int) -> None:
            step.exit_code = code

        return _launch_standalone(
            step.script_path, step.args, step.tool_id, on_exit=_record
        )

    def _emit_progress(
        self,
        current: BatchStep,
        total: int,
        completed_count: int,
        failed_steps: list[str],
        callback: Callable[[BatchProgress], None] | None,
    ) -> None:
        if callback is None:
            return
        elapsed_secs = time.monotonic() - (self._start_time or time.monotonic())
        elapsed = timedelta(seconds=int(elapsed_secs))

        # Estimate remaining based on completed steps' average duration
        completed_durations = [
            s.duration
            for s in self._steps
            if s.duration is not None and s.status == StepStatus.COMPLETED
        ]
        remaining = total - completed_count
        estimated_remaining_secs = 0.0
        if completed_durations and remaining > 0:
            avg = sum(completed_durations) / len(completed_durations)
            estimated_remaining_secs = avg * remaining
        elif completed_count == 0 and remaining > 0:
            # No completed data yet; use historical average from config
            from audio_suite_shared import suite_config as _cfg

            avg_dur = _cfg.load_average_tool_duration(current.tool_id)
            if avg_dur is not None:
                estimated_remaining_secs = avg_dur * remaining

        estimated_remaining = timedelta(seconds=int(estimated_remaining_secs))

        running_steps = [
            s.tool_id for s in self._steps if s.status == StepStatus.RUNNING
        ]
        pending_steps = [
            s.tool_id for s in self._steps if s.status == StepStatus.PENDING
        ]

        # Build per-step status list for the UI display
        status_map = {
            StepStatus.COMPLETED: "completed",
            StepStatus.RUNNING: "running",
            StepStatus.FAILED: "failed",
            StepStatus.PENDING: "pending",
            StepStatus.WAITING: "waiting",
            StepStatus.SKIPPED: "skipped",
        }
        steps_list: list[tuple[str, str, str]] = []
        for s in self._steps:
            display = status_map.get(s.status, "pending")
            steps_list.append((s.tool_id, s.manifest.name, display))

        progress = BatchProgress(
            total_steps=total,
            completed_steps=completed_count,
            current_step=current.tool_id,
            current_progress=(completed_count / total if total > 0 else 1.0),
            elapsed=elapsed,
            estimated_remaining=estimated_remaining,
            failed_steps=list(failed_steps),
            running_steps=running_steps,
            pending_steps=pending_steps,
            steps=steps_list,
            notes={s.tool_id: s.note for s in self._steps if s.note},
        )
        callback(progress)

    def _build_report(
        self,
        total: int,
        completed_count: int,
        failed_steps: list[str],
    ) -> BatchReport:
        elapsed_secs = time.monotonic() - (self._start_time or time.monotonic())
        return BatchReport(
            total=total,
            completed=completed_count,
            failed=len(failed_steps),
            skipped=total - completed_count - len(failed_steps),
            steps=list(self._steps),
            total_elapsed=timedelta(seconds=int(elapsed_secs)),
        )
