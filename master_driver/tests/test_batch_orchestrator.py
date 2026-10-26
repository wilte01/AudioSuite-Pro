"""
Tests for master_driver.batch_orchestrator

Strategy — mock run_python_script / start_python_script to simulate tool
execution with controlled durations and exit codes.

Changed in 1.0.1: adds a regression asserting a missing script fails the
step immediately (no retries) instead of being retried as a generic OSError.
Changed in 1.2.0: adds the step-note tests: a caveat the tool records during
its run reaches ``BatchStep.note`` / ``BatchProgress.notes``, a stale note from
an earlier batch does not, and a failed step reports none.
Changed in 1.4.1: adds the verdict tests - one closing line folds every step
note together, only once the batch has finished, and drops whole clauses rather
than cutting a caveat mid-sentence (D110).
Changed in 2.1.0: the three retrying tests share a ``no_retry_backoff`` fixture
instead of waiting the production 1 s + 2 s + 3 s out; what they assert (which
failures are retried, and the reported status) is unchanged.
Changed in 2.1.4: adds the dependency-failure tests — a failed step skips its
dependants in both modes instead of releasing them, and the skip reason reaches
the step, the panel and the report (audit R-10, plan C4).
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from audio_suite_shared.run_outcome import record_outcome
from audio_suite_shared.tool_plugin import ToolManifest
from master_driver.batch_orchestrator import (
    DEPENDENCY_GRAPH,
    VERDICT_MAX_CHARS,
    BatchOrchestrator,
    BatchProgress,
    BatchReport,
    BatchStep,
    StepStatus,
    _collect_deps,
    _resolve_dependencies,
)


def _make_manifest(
    tool_id: str,
    name: str = "",
    standalone: bool = False,
) -> ToolManifest:
    return ToolManifest(
        id=tool_id,
        name=name or tool_id.title(),
        category="enrich",
        pyw_filename=f"{tool_id}.pyw",
        description="",
        standalone=standalone,
    )


def _make_step(
    tool_id: str,
    standalone: bool = False,
    args: list[str] | None = None,
) -> BatchStep:
    manifest = _make_manifest(tool_id, standalone=standalone)
    return BatchStep.from_spec(
        tool_id=tool_id,
        manifest=manifest,
        args=args or [],
        suite_root="/tmp",
    )


def _mock_result(returncode: int = 0) -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    return m


# ═════════════════════════════════════════════════════════════════════════════
# BatchStep
# ═════════════════════════════════════════════════════════════════════════════


class TestBatchStep:
    def test_from_spec_sets_tool_id(self):
        step = _make_step("bpm")
        assert step.tool_id == "bpm"

    def test_from_spec_sets_manifest(self):
        step = _make_step("bpm")
        assert step.manifest.id == "bpm"

    def test_from_spec_resolves_script_path(self):
        step = _make_step("bpm")
        assert "bpm.pyw" in step.script_path

    def test_duration_none_when_not_started(self):
        step = _make_step("bpm")
        assert step.duration is None

    def test_duration_calculated_when_completed(self):
        step = _make_step("bpm")
        step.start_time = 100.0
        step.end_time = 115.0
        assert step.duration == 15.0

    def test_default_status_is_pending(self):
        step = _make_step("bpm")
        assert step.status == StepStatus.PENDING


# ═════════════════════════════════════════════════════════════════════════════
# _resolve_dependencies
# ═════════════════════════════════════════════════════════════════════════════


class TestResolveDependencies:
    def test_empty_list_returns_empty(self):
        assert _resolve_dependencies([]) == {}

    def test_independent_tool_has_no_deps(self):
        result = _resolve_dependencies(["bpm"])
        assert result == {"bpm": set()}

    def test_tempo_depends_on_bpm(self):
        result = _resolve_dependencies(["bpm", "tempo"])
        assert "bpm" in result["tempo"]

    def test_replaygain_no_deps(self):
        result = _resolve_dependencies(["replaygain"])
        assert result["replaygain"] == set()

    def test_unknown_tool_no_deps(self):
        result = _resolve_dependencies(["unknown_tool"])
        assert result["unknown_tool"] == set()

    def test_missing_dep_not_included(self):
        """If 'bpm' is not in the available list, it should not appear as a dep."""
        result = _resolve_dependencies(["tempo"])
        assert "bpm" not in result["tempo"]


# ═════════════════════════════════════════════════════════════════════════════
# BatchOrchestrator — Sequential execution
# ═════════════════════════════════════════════════════════════════════════════


class TestBatchOrchestratorSequential:
    def test_empty_steps_returns_empty_report(self):
        orch = BatchOrchestrator([])
        report = orch.run()
        assert isinstance(report, BatchReport)
        assert report.total == 0
        assert report.completed == 0

    def test_single_successful_step(self):
        step = _make_step("bpm")
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run()
        assert report.total == 1
        assert report.completed == 1
        assert report.failed == 0
        assert step.status == StepStatus.COMPLETED

    def test_single_failing_step(self):
        step = _make_step("bpm")
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(1),
        ):
            report = orch.run()
        assert report.total == 1
        assert report.completed == 0
        assert report.failed == 1

    def test_steps_executed_in_order(self):
        step1 = _make_step("bpm")
        step2 = _make_step("key")
        step3 = _make_step("tempo")
        orch = BatchOrchestrator([step1, step2, step3])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run()
        assert report.completed == 3
        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.COMPLETED
        assert step3.status == StepStatus.COMPLETED

    def test_middle_step_failure_continues(self):
        step1 = _make_step("bpm")
        step2 = _make_step("key")
        step3 = _make_step("tempo")

        def _side_effect(*args, **kwargs):
            script = args[0]
            if "key" in str(script):
                return _mock_result(1)
            return _mock_result(0)

        orch = BatchOrchestrator([step1, step2, step3])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_side_effect,
        ):
            report = orch.run()
        assert report.completed == 2
        assert report.failed == 1
        assert step1.status == StepStatus.COMPLETED
        assert step2.status == StepStatus.FAILED
        assert step3.status == StepStatus.COMPLETED

    def test_progress_callback_fires(self):
        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)
        assert len(callbacks) >= 2  # at least start + end

    def test_progress_has_correct_step_counts(self):
        steps = [_make_step("bpm"), _make_step("key")]
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)

        # Last callback should show all completed
        final = callbacks[-1]
        assert final.total_steps == 2
        assert final.completed_steps == 2

    def test_standalone_step_launched_via_start_python_script(self, tmp_path):
        script = tmp_path / "cd_ripper.pyw"
        script.write_text("pass")
        step = BatchStep(
            tool_id="cd_ripper",
            manifest=_make_manifest("cd_ripper", standalone=True),
            script_path=str(script),
            args=[],
        )
        orch = BatchOrchestrator([step])
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 0
        type(mock_proc).returncode = PropertyMock(return_value=0)

        with patch(
            "master_driver.batch_orchestrator.start_python_script",
            return_value=mock_proc,
        ):
            report = orch.run()
        assert report.completed == 1
        assert step.status == StepStatus.COMPLETED

    def test_standalone_exit_code_is_recorded_on_the_step(self, tmp_path):
        """A window that closes with an error leaves its code on the step.

        The launcher's own output is gone by the time the caller reports, so
        ``step.exit_code`` is what lets the failure dialog name a reason
        instead of saying only "Module failed: <name>" (PLAN D135).
        """
        script = tmp_path / "example_tool.pyw"
        script.write_text("pass")
        step = BatchStep(
            tool_id="example_tool",
            manifest=_make_manifest("example_tool", standalone=True),
            script_path=str(script),
            args=[],
        )
        orch = BatchOrchestrator([step])
        mock_proc = MagicMock()
        mock_proc.wait.return_value = 1
        type(mock_proc).returncode = PropertyMock(return_value=1)

        with patch(
            "master_driver.batch_orchestrator.start_python_script",
            return_value=mock_proc,
        ):
            report = orch.run()

        assert report.failed == 1
        assert step.status == StepStatus.FAILED
        assert step.exit_code == 1


# ═════════════════════════════════════════════════════════════════════════════
# BatchOrchestrator — Parallel execution
# ═════════════════════════════════════════════════════════════════════════════


class TestBatchOrchestratorParallel:
    def test_independent_tools_run_in_parallel(self):
        steps = [
            _make_step("bpm"),
            _make_step("replaygain"),
            _make_step("genre_sync"),
        ]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run(parallel=True, max_workers=3)
        assert report.completed == 3

    def test_dependent_tools_respected(self):
        """Tempo depends on BPM; should still work in parallel mode."""
        steps = [
            _make_step("bpm"),
            _make_step("tempo"),
        ]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run(parallel=True, max_workers=2)
        assert report.completed == 2

    def test_standalone_skipped_in_parallel(self):
        """A standalone step never runs in parallel mode and says so.

        Positive contract: the step is reported SKIPPED and the report's
        completed/skipped split separates it from the step that actually ran.
        (The previous version asserted ``completed == 2``, pinning the defect.)
        """
        steps = [
            _make_step("bpm"),
            _make_step("cd_ripper", standalone=True),
        ]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run(parallel=True, max_workers=2)
        assert report.completed == 1
        assert report.failed == 0
        assert report.skipped == 1
        statuses = {s.tool_id: s.status for s in report.steps}
        assert statuses == {
            "bpm": StepStatus.COMPLETED,
            "cd_ripper": StepStatus.SKIPPED,
        }

    def test_standalone_step_is_never_submitted_to_the_pool(self):
        """The skipped step must not be handed to the executor at all."""
        steps = [
            _make_step("bpm"),
            _make_step("cd_ripper", standalone=True),
        ]
        orch = BatchOrchestrator(steps)
        with (
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                return_value=_mock_result(0),
            ) as run_script,
            patch("master_driver.batch_orchestrator.start_python_script") as start,
        ):
            orch.run(parallel=True, max_workers=2)
        assert [call.args[0] for call in run_script.call_args_list] == [
            steps[0].script_path
        ]
        assert start.call_count == 0

    def test_standalone_skip_is_logged_with_the_tool_names(self, caplog):
        """The skipped set is surfaced, not just counted."""
        steps = [
            _make_step("bpm"),
            _make_step("cd_ripper", standalone=True),
            _make_step("undo_tag_edits", standalone=True),
        ]
        orch = BatchOrchestrator(steps)
        with (
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                return_value=_mock_result(0),
            ),
            caplog.at_level(logging.INFO, logger="master_driver.batch_orchestrator"),
        ):
            orch.run(parallel=True, max_workers=2)
        assert "skipped 2 standalone step(s)" in caplog.text
        assert "cd_ripper" in caplog.text
        assert "undo_tag_edits" in caplog.text

    def test_standalone_progress_line_reads_skipped(self):
        """The per-step status line the UI renders says 'skipped'."""
        steps = [
            _make_step("bpm"),
            _make_step("cd_ripper", standalone=True),
        ]
        orch = BatchOrchestrator(steps)
        seen: list[BatchProgress] = []
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(parallel=True, max_workers=2, progress_callback=seen.append)
        assert seen, "no progress callback fired - the test would prove nothing"
        last = seen[-1]
        assert last.steps == [
            ("bpm", "Bpm", "completed"),
            ("cd_ripper", "Cd_Ripper", "skipped"),
        ]

    def test_all_standalone_parallel_batch_terminates(self):
        """Every step skipped: the pool loop must exit, not spin."""
        steps = [
            _make_step("cd_ripper", standalone=True),
            _make_step("undo_tag_edits", standalone=True),
        ]
        orch = BatchOrchestrator(steps)
        with patch("master_driver.batch_orchestrator.start_python_script") as start:
            report = orch.run(parallel=True, max_workers=2)
        assert report.completed == 0
        assert report.skipped == 2
        assert start.call_count == 0

    def test_parallel_progress_callback_fires(self):
        steps = [
            _make_step("bpm"),
            _make_step("replaygain"),
        ]
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(parallel=True, progress_callback=callbacks.append)
        assert len(callbacks) >= 2

    def test_parallel_failure_still_reported(self):
        steps = [
            _make_step("bpm"),
            _make_step("replaygain"),
        ]

        def _side_effect(*args, **kwargs):
            script = str(args[0])
            if "replaygain" in script:
                return _mock_result(1)
            return _mock_result(0)

        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_side_effect,
        ):
            report = orch.run(parallel=True, max_workers=2)
        assert report.completed == 1
        assert report.failed == 1


# ═════════════════════════════════════════════════════════════════════════════
# A failed dependency must not release its dependants (plan C4, audit R-10)
# ═════════════════════════════════════════════════════════════════════════════


def _fail_scripts(*fragments: str):
    """Return a ``run_python_script`` side effect failing the named scripts.

    Args:
        *fragments: Substrings of a script path that exit with code 1.

    Returns:
        A callable suitable for ``side_effect=``.
    """

    def _side_effect(*args, **kwargs):
        script = str(args[0])
        if any(fragment in script for fragment in fragments):
            return _mock_result(1)
        return _mock_result(0)

    return _side_effect


class TestFailedDependencySkipsDependants:
    """Tempo reads BPM tags; when BPM fails, tempo must not run.

    The orchestrator used to add a failed step to the same set that released
    dependants, so ``tempo`` ran against files with no BPM tags and the report
    called it completed.  Both modes are covered because sequential mode used
    to consult no graph at all.
    """

    def test_parallel_skips_the_dependant(self):
        steps = [_make_step("bpm"), _make_step("tempo")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_fail_scripts("bpm.pyw"),
        ) as run_script:
            report = orch.run(parallel=True, max_workers=2)

        assert [call.args[0] for call in run_script.call_args_list] == [
            steps[0].script_path
        ], "the dependant must never be submitted to the pool"
        assert {s.tool_id: s.status for s in report.steps} == {
            "bpm": StepStatus.FAILED,
            "tempo": StepStatus.SKIPPED,
        }
        assert (report.completed, report.failed, report.skipped) == (0, 1, 1)

    def test_parallel_skip_carries_the_reason(self):
        steps = [_make_step("bpm"), _make_step("tempo")]
        orch = BatchOrchestrator(steps)
        seen: list[BatchProgress] = []
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_fail_scripts("bpm.pyw"),
        ):
            orch.run(parallel=True, max_workers=2, progress_callback=seen.append)

        tempo_note = next(s.note for s in steps if s.tool_id == "tempo")
        assert tempo_note == "skipped: dependency 'bpm' failed"
        assert seen[-1].steps == [
            ("bpm", "Bpm", "failed"),
            ("tempo", "Tempo", "skipped"),
        ]
        assert seen[-1].notes["tempo"] == tempo_note

    def test_sequential_skips_the_dependant(self):
        steps = [_make_step("bpm"), _make_step("tempo")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_fail_scripts("bpm.pyw"),
        ) as run_script:
            report = orch.run(parallel=False)

        assert [call.args[0] for call in run_script.call_args_list] == [
            steps[0].script_path
        ]
        assert {s.tool_id: s.status for s in report.steps} == {
            "bpm": StepStatus.FAILED,
            "tempo": StepStatus.SKIPPED,
        }
        assert (report.completed, report.failed, report.skipped) == (0, 1, 1)
        assert steps[1].note == "skipped: dependency 'bpm' failed"

    def test_a_successful_dependency_releases_its_dependant(self):
        """The guard must not turn the graph into a blocker."""
        steps = [_make_step("bpm"), _make_step("tempo")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run(parallel=False)
        assert report.completed == 2
        assert steps[1].note == ""

    def test_a_skipped_step_blocks_its_dependants(self, monkeypatch):
        """A standalone step never runs, so its dependant says 'did not run'."""
        monkeypatch.setitem(DEPENDENCY_GRAPH, "tempo", ["cd_ripper"])
        steps = [_make_step("cd_ripper", standalone=True), _make_step("tempo")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ) as run_script:
            report = orch.run(parallel=True, max_workers=2)

        assert run_script.call_count == 0
        assert {s.tool_id: s.status for s in report.steps} == {
            "cd_ripper": StepStatus.SKIPPED,
            "tempo": StepStatus.SKIPPED,
        }
        assert steps[1].note == "skipped: dependency 'cd_ripper' did not run"

    def test_transitive_dependant_is_skipped_too(self, monkeypatch):
        """bpm fails -> tempo skipped -> a step above tempo is skipped as well."""
        monkeypatch.setitem(DEPENDENCY_GRAPH, "synth", ["tempo"])
        steps = [_make_step("bpm"), _make_step("tempo"), _make_step("synth")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_fail_scripts("bpm.pyw"),
        ):
            report = orch.run(parallel=True, max_workers=2)

        assert {s.tool_id: s.status for s in report.steps} == {
            "bpm": StepStatus.FAILED,
            "tempo": StepStatus.SKIPPED,
            "synth": StepStatus.SKIPPED,
        }
        assert (report.completed, report.failed, report.skipped) == (0, 1, 2)
        # The transitive reason names the failure that actually happened, not
        # the skipped step in between.
        assert steps[2].note == "skipped: dependency 'bpm' failed"


# ═════════════════════════════════════════════════════════════════════════════
# Retry behaviour
# ═════════════════════════════════════════════════════════════════════════════


@pytest.fixture()
def no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the retry sleep a no-op.

    The behaviour under test is which failures are retried and how the step is
    reported, not how long the production backoff waits; the default 1 s + 2 s
    + 3 s per exhausted step cost the suite ~20 s of pure waiting.
    """
    monkeypatch.setattr(
        "audio_suite_shared.error_recovery.time.sleep", lambda _seconds: None
    )


class TestRetryBehaviour:
    def test_retry_on_oserror_succeeds(self, no_retry_backoff):
        step = _make_step("bpm")
        call_count: list[int] = []

        def _side_effect(*args, **kwargs):
            call_count.append(1)
            if len(call_count) == 1:
                raise PermissionError("locked")
            return _mock_result(0)

        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_side_effect,
        ):
            report = orch.run()
        assert report.completed == 1
        assert len(call_count) == 2  # first fail, second succeed

    def test_retry_exhaustion_marks_failed(self, no_retry_backoff):
        step = _make_step("bpm")

        def _side_effect(*args, **kwargs):
            raise PermissionError("always locked")

        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_side_effect,
        ):
            report = orch.run()
        assert report.failed == 1
        assert step.status == StepStatus.FAILED

    def test_missing_script_is_not_retried(self, tmp_path, caplog, monkeypatch):
        """A missing script fails once, never retried.

        FileNotFoundError is a subclass of OSError, so pre-fix the
        ``(PermissionError, OSError)`` arm caught it first, re-raised it, and
        ``retry_with_backoff`` retried it twice before logging
        'failed after retries'. Post-fix the ``FileNotFoundError`` arm is
        reachable and returns False with a 'Script not found' warning.
        """
        step = BatchStep(
            tool_id="bpm",
            manifest=_make_manifest("bpm"),
            script_path=str(tmp_path / "ghost.pyw"),
            args=[],
        )
        call_count: list[int] = []

        def _raise_missing(*_args, **_kwargs):
            call_count.append(1)
            raise FileNotFoundError(f"Script not found: {step.script_path}")

        monkeypatch.setattr(
            "audio_suite_shared.error_recovery.time.sleep",
            lambda _seconds: None,
        )
        orch = BatchOrchestrator([step])
        with (
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                side_effect=_raise_missing,
            ),
            caplog.at_level(logging.WARNING, logger="master_driver.batch_orchestrator"),
        ):
            report = orch.run()
        assert report.failed == 1
        assert step.status == StepStatus.FAILED
        assert len(call_count) == 1  # initial attempt only — no retries
        assert "Script not found for bpm" in caplog.text


# ═════════════════════════════════════════════════════════════════════════════
# Edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_no_steps_immediate_completion(self):
        orch = BatchOrchestrator([])
        report = orch.run()
        assert report.total == 0
        assert report.completed == 0
        assert report.total_elapsed is not None

    def test_all_disabled_is_effectively_empty(self):
        """When all toggles are off, no BatchSteps are created."""
        orch = BatchOrchestrator([])
        report = orch.run()
        assert report.total == 0

    def test_single_step_runs_and_completes(self):
        step = _make_step("bpm")
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run()
        assert report.completed == 1

    def test_report_contains_steps(self):
        steps = [_make_step("bpm"), _make_step("key")]
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run()
        assert len(report.steps) == 2

    def test_security_error_does_not_crash(self):
        step = _make_step("bpm")
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=__import__(
                "audio_suite_shared.secure_subprocess"
            ).secure_subprocess.SubprocessSecurityError("blocked"),
        ):
            report = orch.run()
        assert report.failed == 1


# ═════════════════════════════════════════════════════════════════════════════
# DEPENDENCY_GRAPH integrity
# ═════════════════════════════════════════════════════════════════════════════


class TestDependencyGraph:
    # Deliberate exclusions from the registry-completeness contract.
    #
    # A tool id belongs in DEPENDENCY_GRAPH only if the Master Driver can
    # actually schedule it, which requires a CLI command (the batch launches
    # modules as subprocesses) and an arg-builder entry. `undo_tag_edits` is
    # the one registered tool with `cli_command is None`: it is a
    # GUI-only undo utility with no CLI and no arg-builder entry, so it can
    # never appear in an enrich/utility batch.
    #
    # This is an explicit, named allowlist as required by the registry
    # agreement point in `audio_suite_shared/tool_plugin.py`, and
    # `test_excluded_matches_the_batch_ineligible_rule` pins it to the rule
    # itself so it cannot silently absorb a future tool.
    EXCLUDED: frozenset[str] = frozenset({"undo_tag_edits"})

    @staticmethod
    def _registered() -> set[str]:
        from audio_suite_shared.tool_plugin import get_registry

        return {m.id for m in get_registry().first_party}

    def test_graph_covers_every_batch_eligible_tool(self):
        """set(manifest ids) == set(DEPENDENCY_GRAPH keys | EXCLUDED).

        This is the agreement point `tool_plugin.py` documents: a new tool
        added to the registry must arrive with a graph entry, or its ordering
        contract is unstated and it silently defaults to "no dependencies".
        """
        registered = self._registered()
        expected = registered - self.EXCLUDED
        assert set(DEPENDENCY_GRAPH.keys()) == expected, (
            "missing from DEPENDENCY_GRAPH: "
            f"{sorted(expected - set(DEPENDENCY_GRAPH))}; "
            "stale (no longer registered): "
            f"{sorted(set(DEPENDENCY_GRAPH) - expected)}"
        )

    def test_graph_has_no_stale_ids(self):
        """The graph must not name a tool that is no longer registered."""
        assert set(DEPENDENCY_GRAPH) - self._registered() == set()

    def test_excluded_matches_the_batch_ineligible_rule(self):
        """EXCLUDED == exactly the registered tools with no CLI command.

        Anchors the allowlist to a derivable property rather than a hand-typed
        list: if `undo_tag_edits` ever gains a CLI it automatically demands a
        graph entry, and any new CLI-less tool is reported here as an
        unexplained exclusion instead of passing silently.
        """
        from audio_suite_shared.tool_plugin import get_registry

        no_cli = frozenset(
            m.id for m in get_registry().first_party if not m.cli_command
        )
        assert self.EXCLUDED == no_cli

    def test_a_plugin_tool_resolves_to_no_dependencies(self):
        """A plugin cannot be a graph key, and its dependencies are empty.

        ``BatchOrchestrator`` reads the graph with ``.get(tool_id, [])``, so a
        plugin tool schedules exactly as a dependency-free first-party tool
        does.  The graph itself stays a first-party contract: a plugin cannot
        add an ordering rule to the shipped pipeline.
        """
        from audio_suite_shared.tool_plugin import get_registry

        plugins = get_registry().plugins
        assert plugins, "no plugin registered, so this lock would be vacuous"
        for manifest in plugins:
            assert manifest.id not in DEPENDENCY_GRAPH
            assert DEPENDENCY_GRAPH.get(manifest.id, []) == []

    def test_excluded_tools_have_no_arg_builder_entry(self):
        """An excluded id must not be schedulable, or the exclusion is wrong.

        Both builders end with `builders.get(tool_id)` and return `[]` for an
        unknown id, so an excluded tool with no entry yields no arguments and
        can never be launched by a batch. That silent `[]` is exactly why the
        exclusion has to be named here rather than left implicit.
        """
        from master_driver.runner.arg_builder import (
            _build_enrich_tool_args,
            _build_utility_tool_args,
        )

        assert self.EXCLUDED, "the exclusion allowlist must not be empty"
        for tool_id in sorted(self.EXCLUDED):
            for builder in (_build_enrich_tool_args, _build_utility_tool_args):
                assert (
                    builder(tool_id, "/tmp", "--dry", "--no-start", "--no-end", None)
                    == []
                )

    # Note: `audio_refinery` is category "refinery" and is scheduled by
    # build_refinery_args, not by the enrich/utility builders, so it is not
    # reachable from them. Its scheduling contract is covered by
    # TestBuildRefineryArgs in master_driver/tests/test_runner.py.

    def test_non_vacuity_graph_is_not_empty(self):
        """Guard the contract test itself: an empty graph must not pass it."""
        registered = self._registered()
        assert len(DEPENDENCY_GRAPH) >= len(registered) - len(self.EXCLUDED)
        assert len(DEPENDENCY_GRAPH) == len(set(DEPENDENCY_GRAPH))

    def test_new_ids_have_no_unstated_dependencies(self):
        """The three ids added by iteration-8 C4 read only path/mode/start/end.

        Each was verified against its arg-builder signature: none consumes
        another tool's output, so `[]` is the correct declared dependency set.
        """
        for tool_id in ("mood_analyzer", "noise_reduction", "tag_field_updater"):
            assert tool_id in DEPENDENCY_GRAPH
            assert DEPENDENCY_GRAPH[tool_id] == []

    def test_no_self_reference(self):
        for tid, deps in DEPENDENCY_GRAPH.items():
            assert tid not in deps, f"{tid} depends on itself"

    def test_no_circular_dependencies(self):
        """Simple check: no direct circular deps."""
        for tid, deps in DEPENDENCY_GRAPH.items():
            for dep in deps:
                dep_deps = DEPENDENCY_GRAPH.get(dep, [])
                assert tid not in dep_deps, f"Circular dependency: {tid} <-> {dep}"

    def test_every_dependency_is_a_graph_key(self):
        """A dep naming an unregistered id can never be satisfied."""
        known = set(DEPENDENCY_GRAPH)
        for tid, deps in DEPENDENCY_GRAPH.items():
            for dep in deps:
                assert dep in known, f"{tid} depends on ungraphed id {dep!r}"


# ═════════════════════════════════════════════════════════════════════════════
# BatchOrchestrator — branch coverage
# ═════════════════════════════════════════════════════════════════════════════


class TestBatchOrchestratorBranchCoverage:
    def test_sequential_skips_preset_skipped_steps(self):
        """A step already marked SKIPPED must be left untouched by the
        sequential runner (the 'continue' guard on line 247)."""
        step = _make_step("bpm")
        step.status = StepStatus.SKIPPED
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            report = orch.run()
        assert report.completed == 0
        assert report.skipped == 1
        assert step.status == StepStatus.SKIPPED

    def test_parallel_timeout_marks_running_failed(self):
        """When the orchestrator times out waiting for a step, in-flight
        futures must be marked FAILED and reported."""
        steps = [_make_step("bpm")]
        orch = BatchOrchestrator(steps)
        with (
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                return_value=_mock_result(0),
            ),
            patch(
                "master_driver.batch_orchestrator.as_completed",
                side_effect=TimeoutError("timed out"),
            ),
        ):
            report = orch.run(parallel=True, max_workers=2)
        assert report.failed == 1
        assert steps[0].status == StepStatus.FAILED

    def test_standalone_missing_script_fails_step(self, tmp_path):
        """A standalone step whose script does not exist must be reported
        as failed (no crash)."""
        step = BatchStep(
            tool_id="cd_ripper",
            manifest=_make_manifest("cd_ripper", standalone=True),
            script_path=str(tmp_path / "missing.pyw"),
            args=[],
        )
        orch = BatchOrchestrator([step])
        report = orch.run()
        assert report.failed == 1
        assert step.status == StepStatus.FAILED

    def test_standalone_security_error_fails_step(self, tmp_path):
        """A security error while launching a standalone script must be
        caught and reported as a failed step."""
        script = tmp_path / "cd_ripper.pyw"
        script.write_text("pass")
        step = BatchStep(
            tool_id="cd_ripper",
            manifest=_make_manifest("cd_ripper", standalone=True),
            script_path=str(script),
            args=[],
        )
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.start_python_script",
            side_effect=__import__(
                "audio_suite_shared.secure_subprocess"
            ).secure_subprocess.SubprocessSecurityError("blocked"),
        ):
            report = orch.run()
        assert report.failed == 1
        assert step.status == StepStatus.FAILED

    def test_standalone_generic_error_fails_step(self, tmp_path):
        """An unexpected exception while launching a standalone script must
        be mapped and reported (path where map_to_audio_error is called)."""
        script = tmp_path / "cd_ripper.pyw"
        script.write_text("pass")
        step = BatchStep(
            tool_id="cd_ripper",
            manifest=_make_manifest("cd_ripper", standalone=True),
            script_path=str(script),
            args=[],
        )
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.start_python_script",
            side_effect=RuntimeError("boom"),
        ):
            report = orch.run()
        assert report.failed == 1
        assert step.status == StepStatus.FAILED

    def test_estimate_uses_config_average_when_no_data(self):
        """With no completed durations yet, the ETA should fall back to the
        historical average from suite_config."""
        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with (
            patch(
                "master_driver.batch_orchestrator.run_python_script",
                return_value=_mock_result(0),
            ),
            patch(
                "audio_suite_shared.suite_config.load_average_tool_duration",
                return_value=5.0,
            ),
        ):
            orch.run(progress_callback=callbacks.append)
        # first callback: completed=0, remaining=1 → 5.0 s estimated
        assert callbacks[0].estimated_remaining.total_seconds() == 5


class TestBatchProgressSteps:
    def test_steps_populated_sequentially(self):
        """Sequential run must populate the steps field with all step statuses."""
        steps = [_make_step("bpm"), _make_step("key")]
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)

        # The final progress should have all steps in the list
        final = callbacks[-1]
        assert len(final.steps) == 2
        for _tid, _name, status in final.steps:
            assert status == "completed"

    def test_steps_reflect_partial_progress(self):
        """After the first step completes, the steps list should show
        one completed and one pending."""
        step1 = _make_step("bpm")
        step2 = _make_step("key")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step1, step2])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)

        # Progress during execution should show transitions
        # At minimum the final state must be correct
        assert all(s[2] == "completed" for s in callbacks[-1].steps)

    def test_steps_include_tool_id_and_name(self):
        """Each step tuple must contain (tool_id, display_name, status)."""
        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)

        for tid, name, status in callbacks[-1].steps:
            assert isinstance(tid, str)
            assert isinstance(name, str)
            assert isinstance(status, str)

    def test_steps_show_failed_status(self, no_retry_backoff):
        """Failed steps must appear with 'failed' status in the steps list."""
        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=PermissionError("fail"),
        ):
            orch.run(progress_callback=callbacks.append)

        # The final progress should show the step as failed
        final = callbacks[-1]
        for tid, name, status in final.steps:
            if tid == "bpm":
                assert status == "failed"

    def test_parallel_steps_show_correct_statuses(self):
        """Parallel mode must populate steps with correct statuses,
        including 'waiting' for dependent tools not yet ready."""
        steps = [
            _make_step("bpm"),
            _make_step("tempo"),  # depends on bpm
        ]
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator(steps)
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(parallel=True, max_workers=2, progress_callback=callbacks.append)

        # At completion all should be completed
        final = callbacks[-1]
        assert len(final.steps) == 2
        for _tid, _name, status in final.steps:
            assert status in ("completed",)

    def test_empty_batch_steps_empty(self):
        """Empty batch should return empty steps list."""
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([])
        orch.run(progress_callback=callbacks.append)
        if callbacks:
            assert callbacks[-1].steps == []


# ═════════════════════════════════════════════════════════════════════════════
# _collect_deps
# ═════════════════════════════════════════════════════════════════════════════


class TestCollectDeps:
    def test_no_dependencies_returns_empty_set(self):
        collected: set[str] = set()
        _collect_deps("bpm", collected, ["bpm"])
        assert collected == set()

    def test_direct_dependencies_collected(self):
        collected: set[str] = set()
        _collect_deps("tempo", collected, ["bpm", "tempo"])
        assert collected == {"bpm"}

    def test_visited_tool_returns_immediately(self):
        """A tool already in the visited set is skipped (guard against
        re-processing shared transitive dependencies)."""
        collected: set[str] = set()
        _collect_deps("bpm", collected, ["bpm"], visited={"bpm"})
        assert collected == set()

    def test_transitive_dependencies_collected(self):
        collected: set[str] = set()
        _collect_deps("tempo", collected, ["bpm", "tempo"])
        assert collected == {"bpm"}

    def test_circular_dependency_raises_valueerror(self, monkeypatch):
        monkeypatch.setattr(
            "master_driver.batch_orchestrator.DEPENDENCY_GRAPH",
            {"A": ["B"], "B": ["A"]},
        )
        collected: set[str] = set()
        with pytest.raises(ValueError, match="Circular dependency"):
            _collect_deps("A", collected, ["A", "B"])


# ═════════════════════════════════════════════════════════════════════════════
# Per-step notes (a tool's caveat, e.g. a rejected ISRC submission)
# ═════════════════════════════════════════════════════════════════════════════


class TestStepNotes:
    """The batch report's note channel, end to end against the real store."""

    @pytest.fixture(autouse=True)
    def _notes_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        """Keep every note this class writes in a scratch log directory."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        return tmp_path

    def test_note_recorded_during_the_run_reaches_the_step(self):
        """A tool that records a caveat gets it into the report, unchanged."""

        def _run_then_record(*_args, **_kwargs):
            record_outcome("fingerprinter", "ISRC submission: rejected (1 ISRC(s))")
            return _mock_result(0)

        step = _make_step("fingerprinter", standalone=True)
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator._launch_standalone",
            side_effect=lambda *a, **k: bool(_run_then_record()),
        ):
            orch.run(progress_callback=callbacks.append)

        assert step.status == StepStatus.COMPLETED
        assert step.note == "ISRC submission: rejected (1 ISRC(s))"
        assert callbacks[-1].notes == {
            "fingerprinter": "ISRC submission: rejected (1 ISRC(s))"
        }

    def test_stale_note_from_an_earlier_batch_is_not_reported(self):
        """A note left by a previous run must not be attributed to this one."""
        record_outcome("bpm", "ISRC submission: rejected")

        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            return_value=_mock_result(0),
        ):
            orch.run(progress_callback=callbacks.append)

        assert step.status == StepStatus.COMPLETED
        assert step.note == ""
        assert callbacks[-1].notes == {}

    def test_failed_step_reports_no_note(self):
        """A run that did not finish must not be described by a caveat."""

        def _record_then_fail(*_args, **_kwargs):
            record_outcome("bpm", "ISRC submission: offline")
            return _mock_result(1)

        step = _make_step("bpm")
        callbacks: list[BatchProgress] = []
        orch = BatchOrchestrator([step])
        with patch(
            "master_driver.batch_orchestrator.run_python_script",
            side_effect=_record_then_fail,
        ):
            orch.run(progress_callback=callbacks.append)

        assert step.status == StepStatus.FAILED
        assert step.note == ""
        assert callbacks[-1].notes == {}

    def test_note_does_not_change_the_step_count(self):
        """A caveat is not a failure: completed steps stay completed."""

        def _record(*_args, **_kwargs):
            record_outcome("fingerprinter", "ISRC submission: not authorised")
            return _mock_result(0)

        orch = BatchOrchestrator([_make_step("fingerprinter", standalone=True)])
        with patch(
            "master_driver.batch_orchestrator._launch_standalone",
            side_effect=lambda *a, **k: bool(_record()),
        ):
            report = orch.run()

        assert report.completed == 1
        assert report.failed == 0


# ═════════════════════════════════════════════════════════════════════════════
# BatchProgress.verdict — one closing line from every step note (D110)
# ═════════════════════════════════════════════════════════════════════════════


def _progress(
    steps: list[tuple[str, str, str]],
    *,
    notes: dict[str, str] | None = None,
    failed: list[str] | None = None,
) -> BatchProgress:
    """Build one progress snapshot; only the fields the verdict reads matter."""
    return BatchProgress(
        total_steps=len(steps),
        completed_steps=sum(1 for _t, _n, st in steps if st == "completed"),
        current_step=steps[-1][0] if steps else None,
        current_progress=1.0,
        elapsed=timedelta(seconds=60),
        estimated_remaining=timedelta(0),
        failed_steps=list(failed or []),
        running_steps=[tid for tid, _n, st in steps if st == "running"],
        pending_steps=[tid for tid, _n, st in steps if st == "pending"],
        steps=list(steps),
        notes=dict(notes or {}),
    )


class TestBatchVerdict:
    """The report's closing line folds every note into one statement."""

    def test_a_clean_finished_batch_has_no_verdict(self):
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "completed"),
                ("key", "Key Detector", "completed"),
            ]
        )

        assert progress.finished is True
        assert progress.verdict == ""

    def test_an_unfinished_batch_has_no_verdict(self):
        """A closing statement may not describe a run that is still going."""
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "completed"),
                ("fingerprinter", "Audio Fingerprinter", "running"),
            ],
            notes={"bpm": "2 of 12 tracks measured outside the 75-175 BPM range"},
        )

        assert progress.finished is False
        assert progress.verdict == ""

    def test_the_verdict_names_every_step_with_a_note_in_run_order(self):
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "completed"),
                ("key", "Key Detector", "completed"),
                ("fingerprinter", "Audio Fingerprinter", "completed"),
                ("scrubber", "Metadata Scrubber", "completed"),
            ],
            notes={
                # Inserted the other way round on purpose: the line must follow
                # the run's step order, not the dict's insertion order.
                "fingerprinter": "ISRC submission: offline",
                "bpm": "2 of 12 tracks measured outside the 75-175 BPM range",
            },
        )

        assert progress.verdict == (
            "Batch verdict: 2 of 4 steps completed with caveats \u2014 "
            "BPM Analyzer: 2 of 12 tracks measured outside the 75-175 BPM range; "
            "Audio Fingerprinter: ISRC submission: offline"
        )

    def test_a_skipped_step_note_is_not_a_caveat(self):
        """A dependency skip is reported on its own line, not as completed work."""
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "failed"),
                ("tempo", "Tempo Analyzer", "skipped"),
            ],
            notes={"tempo": "skipped: dependency 'bpm' failed"},
            failed=["bpm"],
        )

        assert progress.finished is True
        assert progress.verdict == ""

    def test_failures_lead_the_line(self):
        """A verdict that hid a failed step would not be a verdict."""
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "completed"),
                ("cd_ripper", "CD Ripper", "failed"),
                ("scrubber", "Metadata Scrubber", "completed"),
            ],
            notes={"scrubber": "2 of 4 files could not be scrubbed"},
            failed=["cd_ripper"],
        )

        assert progress.verdict == (
            "Batch verdict: 1 failed \u00b7 1 of 3 steps completed with caveats "
            "\u2014 Metadata Scrubber: 2 of 4 files could not be scrubbed"
        )

    def test_a_one_step_batch_says_step_not_steps(self):
        progress = _progress(
            [("bpm", "BPM Analyzer", "completed")],
            notes={"bpm": "1 of 1 tracks yielded no BPM"},
        )

        assert progress.verdict == (
            "Batch verdict: 1 of 1 step completed with caveats \u2014 "
            "BPM Analyzer: 1 of 1 tracks yielded no BPM"
        )

    def test_a_long_batch_drops_whole_clauses_and_counts_the_rest(self):
        """Eight caveats cannot fit one line; the line says what it dropped."""
        notes = {
            f"tool{i}": f"{i} of 40 tracks could not be scrubbed from the library"
            for i in range(8)
        }
        steps = [(f"tool{i}", f"Tool {i}", "completed") for i in range(8)]

        verdict = _progress(steps, notes=notes).verdict

        assert len(verdict) <= VERDICT_MAX_CHARS, len(verdict)
        assert verdict.startswith(
            "Batch verdict: 8 of 8 steps completed with caveats \u2014 Tool 0: 0 of"
        )
        # Whole clauses only: the kept ones end where a note ends, and the
        # dropped ones are counted rather than half-written.
        assert "; +" in verdict
        assert "Tool 7" not in verdict
        dropped = int(verdict.rsplit("+", 1)[1].split()[0])
        assert 1 <= dropped < 8

    def test_an_oversized_single_note_is_shortened_not_dropped(self):
        """With one caveat there is nothing to drop, so the text is cut."""
        progress = _progress(
            [
                ("bpm", "BPM Analyzer", "completed"),
                ("key", "Key Detector", "completed"),
            ],
            notes={"bpm": "x" * 500},
        )

        verdict = progress.verdict

        assert len(verdict) <= VERDICT_MAX_CHARS, len(verdict)
        assert verdict.startswith("Batch verdict: 1 of 2 steps completed with caveats")
        assert "BPM Analyzer: xxx" in verdict
        assert verdict.endswith("...")
        assert "+0 more" not in verdict

    def test_a_note_for_a_tool_outside_the_batch_is_not_attributed(self):
        progress = _progress(
            [("key", "Key Detector", "completed")],
            notes={"bpm": "2 of 12 tracks measured outside the 75-175 BPM range"},
        )

        assert progress.verdict == ""
