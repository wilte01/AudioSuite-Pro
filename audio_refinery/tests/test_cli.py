"""Tests for audio_refinery/cli.py — the ``audiosuite refine`` command.

Audit M4 (2026-10-06): the click CLI accepted any float for
``--target-lufs`` while the argparse path (``utils/cli_args.py:300``),
``utils/settings.py`` and the GUI validate against
``VALID_TARGET_LUFS_VALUES``.  This module locks the click seam: a
non-preset target fails fast with exit 2 and the shared message, and a
permitted target runs through to the tool's normal empty-directory outcome
with no validation error.

Changed in 1.1.0: added TestEffectFlagsReachConfig for the six
Sprint 1 refine effect flags.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from audio_refinery.cli import refine


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTargetLufsValidation:
    """``--target-lufs`` must be validated by the click option (audit M4)."""

    def test_rejects_non_preset_target(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(refine, [str(tmp_path), "--target-lufs", "999"])
        assert result.exit_code == 2, result.output
        assert "Target LUFS must be one of" in result.output

    def test_permitted_target_reaches_the_run(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-16 is a permitted preset: validation passes and the command runs
        to its empty-directory outcome (exit 0, no audio files reported)."""
        result = runner.invoke(refine, [str(tmp_path), "--target-lufs", "-16"])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output
        assert "No supported audio files found in the selected directory." in (
            result.output
        )

    def test_default_target_is_permitted(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Omitting the flag must not trip the validator."""
        result = runner.invoke(refine, [str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output


class TestEffectFlagsReachConfig:
    """D13: Sprint 1 effect flags must reach EnhanceParams via the pipeline."""

    @staticmethod
    def _enhance_params(runner: CliRunner, tmp_path: Path, *extra: str) -> object:
        from audio_refinery.core import file_processor

        with patch.object(file_processor, "run_pipeline") as mock_run:
            result = runner.invoke(refine, [str(tmp_path), *extra])
        assert mock_run.call_count == 1, (
            f"run_pipeline was called {mock_run.call_count} times: {result.output}"
        )
        config = mock_run.call_args.kwargs["config"]
        return config.enhance_params

    def test_effect_flags_set_enhance_params(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        params = self._enhance_params(
            runner,
            tmp_path,
            "--reverse",
            "--phaser",
            "--flanger",
            "--chorus",
            "--karaoke",
            "--karaoke-strength",
            "0.25",
        )
        assert params.reverse is True
        assert params.phaser is True
        assert params.flanger is True
        assert params.chorus is True
        assert params.karaoke is True
        assert params.karaoke_strength == pytest.approx(0.25)

    def test_effects_default_off(self, runner: CliRunner, tmp_path: Path) -> None:
        params = self._enhance_params(runner, tmp_path)
        assert params.reverse is False
        assert params.phaser is False
        assert params.flanger is False
        assert params.chorus is False
        assert params.karaoke is False
        assert params.karaoke_strength == pytest.approx(1.0)

    def test_karaoke_strength_out_of_range_rejected(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        result = runner.invoke(refine, [str(tmp_path), "--karaoke-strength", "2.0"])
        assert result.exit_code == 2, result.output
