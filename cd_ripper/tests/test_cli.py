"""
tests/test_cli.py
Tests for cd_ripper/cli.py — the click command that drives a RipSession
and formats the results.

RipSession and get_quality_options are lazily imported inside the command,
so they are patched at their source modules. The fake session marks itself
done by invoking the session_done_cb during start(), unblocking the
command's done_event.wait().

Run with:
    pytest tests/test_cli.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

import cd_ripper.cli  # noqa: F401  (registers @cli.command on the group)
from audio_suite_shared.cli_base import cli
from cd_ripper.core import metadata_resolver, ripper


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _fake_session_factory(captured: dict[str, Any]) -> MagicMock:
    """Return a callable that builds a self-completing fake RipSession."""

    def _build(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        session = MagicMock()

        def _start() -> None:
            kwargs["log_cb"]("starting rip")
            kwargs["progress_cb"](1, 50, "processing")
            kwargs["track_done_cb"](1, True, "/out/a.flac", "done")
            kwargs["session_done_cb"]()

        session.start.side_effect = _start
        return session

    return _build


class TestCdRipDryRun:
    def test_dry_run_prints_settings_and_skips_rip(self, runner: CliRunner) -> None:
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory({})
        ) as session_cls:
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--dry"]
            )
        assert result.exit_code == 0
        assert "DRY RUN" in result.output
        assert "Drive" in result.output
        session_cls.assert_not_called()

    def test_dry_run_shows_all_tracks_label(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["cd-rip", "D:", "--output-dir", "/out", "--dry", "--tracks", "1,2"]
        )
        assert result.exit_code == 0
        assert "1,2" in result.output


class TestQualityOptions:
    def test_quality_resolves_codec_args(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with (
            patch.object(
                metadata_resolver,
                "get_quality_options",
                return_value={"v0": "--vbr 0"},
            ),
            patch.object(
                ripper, "RipSession", side_effect=_fake_session_factory(captured)
            ),
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--quality", "v0"]
            )
        assert result.exit_code == 0
        assert captured["quality_args"] == "--vbr 0"

    def test_quality_opts_none_leaves_codec_args_none(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with (
            patch.object(metadata_resolver, "get_quality_options", return_value=None),
            patch.object(
                ripper, "RipSession", side_effect=_fake_session_factory(captured)
            ),
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--quality", "v0"]
            )
        assert result.exit_code == 0
        assert captured["quality_args"] is None

    def test_quality_key_missing_leaves_codec_args_none(
        self, runner: CliRunner
    ) -> None:
        captured: dict[str, Any] = {}
        with (
            patch.object(
                metadata_resolver,
                "get_quality_options",
                return_value={"v9": "x"},
            ),
            patch.object(
                ripper, "RipSession", side_effect=_fake_session_factory(captured)
            ),
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--quality", "v0"]
            )
        assert result.exit_code == 0
        assert captured["quality_args"] is None


class TestFormatResolution:
    """The CLI --format Choice is lowercase ('wav', 'opus'); the session and
    quality presets are keyed by display name. Regression: RipSession used to
    receive the raw lowercase value and KeyError on FORMAT_OPTIONS lookup for
    every format (tests mocked RipSession so it went unnoticed)."""

    def test_lowercase_format_resolves_to_display_key(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--format", "wav"]
            )
        assert result.exit_code == 0
        assert captured["fmt"] == "WAV"

    def test_opus_lowercase_resolves_to_display_key(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--format", "opus"]
            )
        assert result.exit_code == 0
        assert captured["fmt"] == "Opus"

    def test_quality_lookup_uses_display_key(self, runner: CliRunner) -> None:
        """get_quality_options is case-sensitive, so a lowercase --format must
        be resolved to the display key before the preset lookup."""
        captured: dict[str, Any] = {}
        with (
            patch.object(
                metadata_resolver,
                "get_quality_options",
                return_value={"Default": ["-c:a", "pcm_s16le"]},
            ) as goq,
            patch.object(
                ripper, "RipSession", side_effect=_fake_session_factory(captured)
            ),
        ):
            result = runner.invoke(
                cli,
                [
                    "cd-rip",
                    "D:",
                    "--output-dir",
                    "/out",
                    "--format",
                    "wav",
                    "--quality",
                    "Default",
                ],
            )
        assert result.exit_code == 0
        goq.assert_called_once_with("WAV")
        assert captured["quality_args"] == ["-c:a", "pcm_s16le"]

    def test_dry_run_accepts_wav_format(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["cd-rip", "D:", "--output-dir", "/out", "--dry", "--format", "wav"]
        )
        assert result.exit_code == 0
        assert "wav" in result.output


class TestTracksParsing:
    def test_valid_tracks_build_track_list(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--tracks", "1,3"]
            )
        assert result.exit_code == 0
        assert captured["tracks"] == [{"number": 1}, {"number": 3}]

    def test_no_tracks_means_all(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(cli, ["cd-rip", "D:", "--output-dir", "/out"])
        assert result.exit_code == 0
        assert captured["tracks"] == []

    def test_all_invalid_tracks_aborts(self, runner: CliRunner) -> None:
        with patch.object(ripper, "RipSession") as session_cls:
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--tracks", "abc,!!"]
            )
        assert "No valid track numbers" in result.output
        session_cls.assert_not_called()


class TestRipOutput:
    def test_runs_rip_session_and_prints_text_summary(self, runner: CliRunner) -> None:
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory({})
        ) as session_cls:
            result = runner.invoke(cli, ["cd-rip", "D:", "--output-dir", "/out"])
        assert result.exit_code == 0
        assert "Rip session complete" in result.output
        session_cls.assert_called_once()

    def test_json_output_prints_structured_result(self, runner: CliRunner) -> None:
        with patch.object(ripper, "RipSession", side_effect=_fake_session_factory({})):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--json"]
            )
        assert result.exit_code == 0
        assert '"drive": "D:"' in result.output
        assert '"format": "flac"' in result.output
        assert '"tracks": "all"' in result.output


class TestVerifyOption:
    def test_default_passes_twice(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(cli, ["cd-rip", "D:", "--output-dir", "/out"])
        assert result.exit_code == 0
        assert captured["verify_mode"] == "twice"

    @pytest.mark.parametrize("mode", ["off", "twice", "accuraterip"])
    def test_explicit_mode_passes_through(self, runner, mode) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--verify", mode]
            )
        assert result.exit_code == 0
        assert captured["verify_mode"] == mode

    def test_invalid_choice_is_rejected(self, runner: CliRunner) -> None:
        with patch.object(ripper, "RipSession") as session_cls:
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--verify", "banana"]
            )
        assert result.exit_code == 2
        session_cls.assert_not_called()

    def test_dry_run_announces_verify_mode(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli,
            ["cd-rip", "D:", "--output-dir", "/out", "--dry", "--verify", "off"],
        )
        assert result.exit_code == 0
        assert "Verify" in result.output

    def test_json_output_includes_verify_field(self, runner: CliRunner) -> None:
        with patch.object(ripper, "RipSession", side_effect=_fake_session_factory({})):
            result = runner.invoke(
                cli,
                [
                    "cd-rip",
                    "D:",
                    "--output-dir",
                    "/out",
                    "--json",
                    "--verify",
                    "accuraterip",
                ],
            )
        assert result.exit_code == 0
        assert '"verify": "accuraterip"' in result.output


class TestCueFlag:
    def test_default_passes_write_cue_false(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(cli, ["cd-rip", "D:", "--output-dir", "/out"])
        assert result.exit_code == 0
        assert captured["write_cue"] is False

    def test_cue_flag_passes_write_cue_true(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--cue"]
            )
        assert result.exit_code == 0
        assert captured["write_cue"] is True

    def test_no_cue_flag_passes_write_cue_false(self, runner: CliRunner) -> None:
        captured: dict[str, Any] = {}
        with patch.object(
            ripper, "RipSession", side_effect=_fake_session_factory(captured)
        ):
            result = runner.invoke(
                cli, ["cd-rip", "D:", "--output-dir", "/out", "--no-cue"]
            )
        assert result.exit_code == 0
        assert captured["write_cue"] is False

    def test_dry_run_announces_cue_sheet(self, runner: CliRunner) -> None:
        result = runner.invoke(
            cli, ["cd-rip", "D:", "--output-dir", "/out", "--dry", "--cue"]
        )
        assert result.exit_code == 0
        assert "CUE sheet" in result.output


class TestOutputDirRequirement:
    """--output-dir became conditionally required: mandatory for ripping,
    optional for --detect-read-offset."""

    def test_missing_output_dir_on_rip_path_is_usage_error(
        self, runner: CliRunner
    ) -> None:
        with patch.object(ripper, "RipSession") as session_cls:
            result = runner.invoke(cli, ["cd-rip", "D:"])
        assert result.exit_code == 2
        assert "--output-dir" in result.output
        session_cls.assert_not_called()


class TestDetectReadOffsetFlag:
    """--detect-read-offset: TOC -> disc ids -> DB lookup -> sweep -> persist.

    The CLI delegates to the shared ``run_read_offset_detection`` pipeline
    (imported inside the command), so it is patched at its source module —
    the AGENTS.md mock-target rule. Pipeline-level behaviour (normalisation,
    lookup failures, unanimity) is covered in test_offset_detect.py.
    """

    def _run(self, runner, mock_value=None, mock_raises=None, argv=None):
        from cd_ripper.core import offset_detect

        with patch.object(
            offset_detect,
            "run_read_offset_detection",
            return_value=mock_value,
            side_effect=mock_raises,
        ) as run:
            result = runner.invoke(cli, argv)
        return result, run

    def test_success_prints_result(self, runner: CliRunner) -> None:
        result, run = self._run(
            runner, mock_value=6, argv=["cd-rip", "D:", "--detect-read-offset"]
        )
        assert result.exit_code == 0
        assert "Read offset measured: +6 frames" in result.output
        run.assert_called_once()

    def test_success_json_output(self, runner: CliRunner) -> None:
        result, _ = self._run(
            runner,
            mock_value=6,
            argv=["cd-rip", "D:", "--detect-read-offset", "--json"],
        )
        assert result.exit_code == 0
        assert '"read_offset_frames": 6' in result.output

    def test_detection_failure_exits_nonzero_with_message(
        self, runner: CliRunner
    ) -> None:
        from cd_ripper.core.offset_detect import ReadOffsetDetectionError

        result, _ = self._run(
            runner,
            mock_raises=ReadOffsetDetectionError(
                "AccurateRip lookup failed: disc has no entry"
            ),
            argv=["cd-rip", "D:", "--detect-read-offset"],
        )
        assert result.exit_code == 1
        assert "AccurateRip lookup failed" in result.output

    def test_device_error_exits_nonzero_with_message(self, runner: CliRunner) -> None:
        from audio_suite_shared.exceptions import AudioIOError

        result, _ = self._run(
            runner,
            mock_raises=AudioIOError("Cannot open CD device (Win32 error 2)"),
            argv=["cd-rip", "D:", "--detect-read-offset"],
        )
        assert result.exit_code == 1
        assert "Cannot open CD device" in result.output

    def test_detection_does_not_need_output_dir(self, runner: CliRunner) -> None:
        # --dry is ignored on the detection path; detection runs regardless.
        result, _ = self._run(
            runner,
            mock_value=6,
            argv=["cd-rip", "D:", "--detect-read-offset", "--dry"],
        )
        assert result.exit_code == 0

    def test_rip_session_not_started_for_detection(self, runner: CliRunner) -> None:
        with patch.object(ripper, "RipSession") as session_cls:
            result, _ = self._run(
                runner,
                mock_value=6,
                argv=["cd-rip", "D:", "--detect-read-offset"],
            )
        assert result.exit_code == 0
        session_cls.assert_not_called()
