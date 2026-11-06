"""Tests for the capture-time lock in ``utilities/capture_guide_shots.py``.

The lock exists because a figure's silent failure mode is a filler that changes
nothing: the window is still a real one, the grab still succeeds, and the guide
ships an idle Processing tab under a "part-way through a run" caption, or one
tool's status lines under another tool's caption.  No compile, lint or type
check can see either, so the capture reads the filled tab back and refuses a
figure that is empty, carries another tool's declared line, or carries a status
token only another tool publishes.

These tests hold the lock for every tool that declares a run, so a registry that
loses one tool's lines, or a lock that only works for the tool it was written
against, fails here.

Changed in 2.5.0: initial version - the lock and its vocabulary registry, held
for every declaring tool.
"""

from __future__ import annotations

import re

import pytest

from utilities import capture_guide_shots as capture

#: Every tool whose figures carry declared status lines. ReplayGain Analyzer is
#: absent: a healthy run publishes empty display lines, so its figure is the
#: worker grid rather than a per-file list, and the lock leaves it alone.
DECLARED_RUNS = [
    pytest.param(tool_id, run, id=tool_id)
    for tool_id, run in sorted(capture.SAMPLE_RUNS.items())
    if capture.DECLARED_LINES.get(tool_id)
]


def _line_owned_only_by(exclude: str) -> tuple[str, str]:
    """Return one declared line that only a tool other than ``exclude`` owns."""
    for tool_id, lines in sorted(capture.DECLARED_LINES.items()):
        if tool_id == exclude:
            continue
        for line in sorted(lines):
            if capture._LINE_OWNERS.get(line) == frozenset({tool_id}):
                return tool_id, line
    raise AssertionError(f"no exclusively-owned line in the registry besides {exclude}")


def _token_owned_only_by(exclude: str) -> tuple[str, str]:
    """Return one status token that only a tool other than ``exclude`` publishes."""
    for token, owners in sorted(capture.TOKEN_OWNERS.items()):
        if len(owners) != 1:
            continue
        (tool_id,) = owners
        if tool_id != exclude:
            return tool_id, token
    raise AssertionError(f"no exclusive status token in the registry besides {exclude}")


class TestTheVocabulary:
    """The registry the lock compares a figure against is populated."""

    def test_cover_every_tool_that_declares_a_run(self) -> None:
        assert DECLARED_RUNS, "no tool declares sample lines"

    def test_every_tool_with_a_run_declares_lines(self) -> None:
        assert capture.DECLARED_LINES, "no tool declares sample lines"

        for tool_id, lines in capture.DECLARED_LINES.items():
            if tool_id == "replaygain_analyzer":
                # A healthy ReplayGain run publishes empty display lines; its
                # figure is the worker grid, not a per-file list.
                assert lines == frozenset()
                continue
            assert lines, f"{tool_id} declares an empty sample run"

    def test_bpm_analyzer_lines_are_registered_without_a_sample_run(self) -> None:
        assert "bpm_analyzer" in capture.DECLARED_LINES
        assert "bpm_analyzer" not in capture.SAMPLE_RUNS

    def test_an_exclusive_token_names_the_one_tool_that_publishes_it(self) -> None:
        assert capture.TOKEN_OWNERS["FINGERPRINT"] == frozenset({"duplicate_finder"})

    def test_a_shared_token_names_every_tool_that_publishes_it(self) -> None:
        assert len(capture.TOKEN_OWNERS["DRY RUN"]) > 1


class TestEveryDeclaredFiguresRun:
    """A filled Processing figure must be that tool's run, and only that run."""

    @pytest.mark.parametrize(("tool_id", "run"), DECLARED_RUNS)
    def test_the_tools_own_lines_pass(
        self, tool_id: str, run: capture.SampleRun
    ) -> None:
        capture._check_sample_content(tool_id, run, list(run.lines))

    @pytest.mark.parametrize(("tool_id", "run"), DECLARED_RUNS)
    def test_an_empty_figure_fails(self, tool_id: str, run: capture.SampleRun) -> None:
        with pytest.raises(RuntimeError, match="still empty"):
            capture._check_sample_content(tool_id, run, [])

    @pytest.mark.parametrize(("tool_id", "run"), DECLARED_RUNS)
    def test_another_tools_declared_line_fails(
        self, tool_id: str, run: capture.SampleRun
    ) -> None:
        other, foreign = _line_owned_only_by(tool_id)

        with pytest.raises(RuntimeError, match=other):
            capture._check_sample_content(tool_id, run, [*run.lines, foreign])

    @pytest.mark.parametrize(("tool_id", "run"), DECLARED_RUNS)
    def test_another_tools_status_token_fails(
        self, tool_id: str, run: capture.SampleRun
    ) -> None:
        other, token = _token_owned_only_by(tool_id)
        shown = [*run.lines, f"[{token}] 99 - Sample Track.flac"]

        with pytest.raises(RuntimeError, match=re.escape(f"[{token}]")):
            capture._check_sample_content(tool_id, run, shown)

    @pytest.mark.parametrize(("tool_id", "run"), DECLARED_RUNS)
    def test_a_figure_with_no_run_lines_fails(
        self, tool_id: str, run: capture.SampleRun
    ) -> None:
        with pytest.raises(RuntimeError, match="not this tool's sample run"):
            capture._check_sample_content(tool_id, run, ["Processing..."])

    def test_a_run_without_lines_is_left_alone(self) -> None:
        empty_run = capture.SampleRun(status="Measuring loudness...", lines=())

        capture._check_sample_content("replaygain_analyzer", empty_run, [])
