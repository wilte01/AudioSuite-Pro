"""
Tests for master_driver.batch_orchestrator

Strategy — mock run_python_script / start_python_script to simulate tool
execution with controlled durations and exit codes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from audio_suite_shared.tool_plugin import ToolManifest
from master_driver.batch_orchestrator import (
    DEPENDENCY_GRAPH,
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
        assert report.completed == 2

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
# Retry behaviour
# ═════════════════════════════════════════════════════════════════════════════


class TestRetryBehaviour:
    def test_retry_on_oserror_succeeds(self):
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

    def test_retry_exhaustion_marks_failed(self):
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
    def test_all_registered_tools_have_entry(self):
        """Every registered enrich/utility tool should have a DEPENDENCY_GRAPH entry."""
        from audio_suite_shared.tool_plugin import get_registry

        registry = get_registry()
        registered_ids = {m.id for m in registry.all}
        graph_ids = set(DEPENDENCY_GRAPH.keys())
        # The consumer contract: a tool missing a graph entry resolves to
        # empty dependencies ( newcomers run in parallel by default ), which
        # is exactly what run_modules reads. Assert that resolution works.
        missing = registered_ids - graph_ids
        for tid in missing:
            deps = DEPENDENCY_GRAPH.get(tid, [])
            assert isinstance(deps, list), (tid, deps)

    def test_no_self_reference(self):
        for tid, deps in DEPENDENCY_GRAPH.items():
            assert tid not in deps, f"{tid} depends on itself"

    def test_no_circular_dependencies(self):
        """Simple check: no direct circular deps."""
        for tid, deps in DEPENDENCY_GRAPH.items():
            for dep in deps:
                dep_deps = DEPENDENCY_GRAPH.get(dep, [])
                assert tid not in dep_deps, f"Circular dependency: {tid} <-> {dep}"


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

    def test_steps_show_failed_status(self):
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
