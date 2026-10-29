"""Tests for audio_normalizer/cli.py — the ``audiosuite normalise`` command.

Audit M4 (2026-10-06): the click CLI accepted any float for
``--target-lufs`` while the argparse path (``utils/cli_args.py:61``) and the
GUI validate against ``VALID_TARGET_LUFS_VALUES``.  This module locks the
click seam: a non-preset target fails fast with exit 2 and the shared
message, and a permitted target runs through to the tool's normal
empty-directory outcome with no validation error.

Changed in 2.1.7: covers ``--tp``/``--lra`` reaching the loudnorm filter, and the
default path still sending -1.5 dBTP / 11 LU.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from audio_normalizer.cli import normalise


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestTargetLufsValidation:
    """``--target-lufs`` must be validated by the click option (audit M4)."""

    def test_rejects_non_preset_target(self, runner: CliRunner, tmp_path: Path) -> None:
        result = runner.invoke(normalise, [str(tmp_path), "--target-lufs", "999"])
        assert result.exit_code == 2, result.output
        assert "Target LUFS must be one of" in result.output

    def test_permitted_target_reaches_the_run(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """-14 is a permitted preset: validation passes and the command runs
        to its empty-directory outcome (exit 0, no audio files reported)."""
        result = runner.invoke(normalise, [str(tmp_path), "--target-lufs", "-14"])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output
        assert "No supported audio files found in selected directory." in result.output

    def test_default_target_is_permitted(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Omitting the flag must not trip the validator."""
        result = runner.invoke(normalise, [str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Target LUFS must be one of" not in result.output


class TestDeliveryTargetOptions:
    """F-09: ``--tp`` and ``--lra`` reach the run and are range-validated."""

    def test_targets_are_forwarded(self, runner: CliRunner, tmp_path: Path) -> None:
        from unittest.mock import patch

        with patch(
            "audio_normalizer.core.file_processor.run_parallel_process"
        ) as mock_run:
            result = runner.invoke(
                normalise,
                [
                    str(tmp_path),
                    "--tp",
                    "-1.0",
                    "--lra",
                    "7",
                ],
            )

        assert result.exit_code == 0, result.output
        _args, kwargs = mock_run.call_args
        assert kwargs["true_peak"] == -1.0
        assert kwargs["lra"] == 7.0

    def test_defaults_reach_the_run_unchanged(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        from unittest.mock import patch

        with patch(
            "audio_normalizer.core.file_processor.run_parallel_process"
        ) as mock_run:
            result = runner.invoke(normalise, [str(tmp_path)])

        assert result.exit_code == 0, result.output
        _args, kwargs = mock_run.call_args
        assert kwargs["true_peak"] == -1.5
        assert kwargs["lra"] == 11.0

    @pytest.mark.parametrize("value", ["1.0", "-10.0", "0.5"])
    def test_ceiling_outside_range_is_rejected(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        result = runner.invoke(normalise, [str(tmp_path), "--tp", value])
        assert result.exit_code == 2, result.output

    @pytest.mark.parametrize("value", ["0.5", "25"])
    def test_lra_outside_range_is_rejected(
        self, runner: CliRunner, tmp_path: Path, value: str
    ) -> None:
        result = runner.invoke(normalise, [str(tmp_path), "--lra", value])
        assert result.exit_code == 2, result.output
