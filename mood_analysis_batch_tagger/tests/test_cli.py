"""test_cli.py — tests for mood_analysis_batch_tagger.cli.mood_analysis_batch_cli.

run_batch is imported inside the command body, so the mock must be applied to
the source module (batch_analysis_engine), not the importing cli module.

Changed in 2.1.4: the command now applies the shared exit contract (PLAN D9), so
the cases that report ``errors=1`` assert exit 1 with the summary still printed,
and ``TestExitContract`` pins the clean and all-skipped cases at 0.
"""

from __future__ import annotations

import json
import queue
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

from click.testing import CliRunner

# Importing the tool CLI module executes the @cli.command() decorator,
# registering "mood-analysis-batch" on the shared group.
import mood_analysis_batch_tagger.cli  # noqa: F401, E402
from audio_suite_shared.cli_base import cli

ENGINE = "mood_analysis_batch_tagger.core.batch_analysis_engine"


def _enqueue_done(
    out_queue: queue.Queue[object],
    tagged: int = 5,
    skipped: int = 2,
    errors: int = 1,
    folders: int = 1,
    log_path: str = "",
) -> None:
    out_queue.put(("done", tagged, skipped, errors, folders, log_path))


class _FakeRunBatch:
    """Drop-in replacement for run_batch recording kwargs and posting done."""

    def __init__(self, **done_kwargs: object) -> None:
        self._done_kwargs = done_kwargs
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        _enqueue_done(kwargs["out_queue"], **self._done_kwargs)  # type: ignore[arg-type]
        return None


class TestMoodAnalysisBatchCliJson:
    def test_json_output_reports_summary(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch(
            tagged=5, skipped=2, errors=1, folders=1, log_path="runs/a.log"
        )
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--json"],
            )

        # One file failed, so the run is not a shell success (R-06) - and the
        # document it printed is still the full, unchanged payload.
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["tagged"] == 5
        assert payload["skipped"] == 2
        assert payload["errors"] == 1
        assert payload["folders"] == 1
        assert payload["log_path"] == "runs/a.log"

    def test_json_passes_live_and_duration(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch()
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--live", "--duration", "60"],
            )
        assert fake.calls[0]["live"] is True
        assert fake.calls[0]["analysis_duration"] == 60

    def test_json_passes_parallel_and_workers(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch()
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--parallel", "--workers", "8"],
            )
        assert fake.calls[0]["parallel_mode"] is True
        assert fake.calls[0]["max_workers"] == 8


class TestMoodAnalysisBatchCliText:
    def test_text_output_reports_counts(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch(tagged=5, skipped=2, errors=1, folders=1)
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--text"],
            )

        assert result.exit_code == 1
        assert "Folders scanned: 1" in result.output
        assert "Files tagged:    5" in result.output
        assert "Files skipped:   2" in result.output
        assert "Errors:          1" in result.output

    def test_text_output_includes_log_path(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch(log_path="runs/a.log")
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--text"],
            )
        assert "Log: runs/a.log" in result.output

    def test_text_output_omits_log_when_empty(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch(log_path="")
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli,
                ["mood-analysis-batch", str(tmp_path), "--text"],
            )
        assert "Log:" not in result.output


class TestMoodAnalysisBatchCliLiveFlag:
    def test_live_flag_passes_live_true(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch()
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            runner.invoke(cli, ["mood-analysis-batch", str(tmp_path), "--live"])
        assert fake.calls[0]["live"] is True

    def test_default_is_live_true(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch()
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            runner.invoke(cli, ["mood-analysis-batch", str(tmp_path)])
        assert fake.calls[0]["live"] is True

    def test_dry_run_flag_passes_live_false(self, tmp_path) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch()
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            runner.invoke(cli, ["mood-analysis-batch", str(tmp_path), "--dry"])
        assert fake.calls[0]["live"] is False


CLI = "mood_analysis_batch_tagger.cli"


class TestMoodAnalysisBatchCliUndoBatch:
    """Regression: the CLI command must wrap run_batch in an active ``tag_edit``
    undo batch so writes auto-snapshot, matching the GUI path."""

    def test_cli_run_opens_active_undo_batch(self, tmp_path: Any) -> None:
        from audio_suite_shared.batch_undo import (
            active_batch as real_active_batch,
        )
        from audio_suite_shared.batch_undo import (
            get_active_batch_id,
        )

        runner = CliRunner()
        db_path = tmp_path / "undo.db"
        entered_ids: list[str] = []

        @contextmanager
        def _tracked_batch(tool_name: str, operation_type: str) -> Iterator[str]:
            with real_active_batch(
                tool_name, operation_type, db_path=db_path
            ) as batch_id:
                entered_ids.append(batch_id)
                yield batch_id

        def _fake_run_batch(**kwargs: object) -> None:
            # Executes inside the ``with active_batch(...)`` block on the CLI
            # thread.  The undo-batch machinery must already be live.
            assert get_active_batch_id() is not None, (
                "no active undo batch during CLI run"
            )
            _enqueue_done(
                kwargs["out_queue"],  # type: ignore[arg-type]
                tagged=3,
                skipped=0,
                errors=0,
            )

        with (
            patch(f"{CLI}.active_batch", side_effect=_tracked_batch),
            patch(f"{ENGINE}.run_batch", side_effect=_fake_run_batch),
        ):
            result = runner.invoke(
                cli, ["mood-analysis-batch", str(tmp_path), "--live"]
            )

        assert result.exit_code == 0
        assert len(entered_ids) == 1, "active_batch should be entered exactly once"


class TestExitContract:
    """R-06: the shell status mirrors the ``errors`` the payload reports."""

    def test_a_clean_run_exits_0(self, tmp_path: Any) -> None:
        runner = CliRunner()
        fake = _FakeRunBatch(tagged=4, skipped=0, errors=0)
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli, ["mood-analysis-batch", str(tmp_path), "--json"]
            )

        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["errors"] == 0

    def test_an_all_skipped_run_exits_0(self, tmp_path: Any) -> None:
        """Nothing tagged because nothing had audio to analyse is not a failure."""
        runner = CliRunner()
        fake = _FakeRunBatch(tagged=0, skipped=4, errors=0)
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli, ["mood-analysis-batch", str(tmp_path), "--json"]
            )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["skipped"] == 4
        assert payload["errors"] == 0

    def test_errors_exit_1_after_the_summary_is_printed(self, tmp_path: Any) -> None:
        """The count a user reads and the status a script sees must agree."""
        runner = CliRunner()
        fake = _FakeRunBatch(tagged=1, skipped=0, errors=2)
        with patch(f"{ENGINE}.run_batch", side_effect=fake):
            result = runner.invoke(
                cli, ["mood-analysis-batch", str(tmp_path), "--text"]
            )

        assert result.exit_code == 1
        assert "Errors:          2" in result.output
