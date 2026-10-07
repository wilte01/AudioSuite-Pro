"""Tests for replaygain_analyzer/cli.py — the ``audiosuite replaygain`` command.

Audit M4 (2026-10-06): the click CLI accepted any float for
``--target-lufs`` while the argparse path (``utils/cli_args.py:58``),
``app.py:280`` and the GUI validate against ``VALID_TARGET_LUFS_VALUES``.
This module locks the click seam: a non-preset target fails fast with exit 2
and the shared message, and a permitted target runs through to the tool's
normal empty-directory outcome with no validation error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from replaygain_analyzer.cli import replaygain


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTargetLufsValidation:
    """``--target-lufs`` must be validated by the click option (audit M4)."""

    def test_rejects_non_preset_target(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(replaygain, [str(tmp_path), "--target-lufs", "999"])
        assert result.exit_code == 2, result.output
        assert "Target LUFS must be one of" in result.output

    def test_permitted_target_reaches_the_run(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-14 is a permitted preset: validation passes and the command runs
        to its empty-directory outcome (exit 0, no audio files reported)."""
        result = runner.invoke(replaygain, [str(tmp_path), "--target-lufs", "-14"])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output
        assert "No audio files found in the selected directory." in result.output

    def test_default_target_is_permitted(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Omitting the flag must not trip the validator."""
        result = runner.invoke(replaygain, [str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output


class TestTargetLufsDefault:
    """D4 (iteration 9): the click default must match the GUI
    (``app.py:54``, ``-16.0``) and argparse (``utils/cli_args.py:40``)
    defaults, so no entry point silently rewrites another's target."""

    def test_click_target_lufs_default_is_minus_16(self) -> None:
        param = next(p for p in replaygain.params if "--target-lufs" in p.opts)
        assert param.default == -16.0
