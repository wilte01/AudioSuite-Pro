"""``audiosuite channels``, driven through the real click group.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from pydub.generators import Sine

from audio_suite_shared.cli_app import cli


def _stereo_wav(path: Path) -> Path:
    left = Sine(440).to_audio_segment(duration=200, volume=-10)
    right = Sine(220).to_audio_segment(duration=200, volume=-10)
    from pydub import AudioSegment

    AudioSegment.from_mono_audiosegments(left, right).export(str(path), format="wav")
    return path


class TestChannelsCommand:
    def test_dry_run_publishes_the_documented_payload(self, tmp_path: Path) -> None:
        _stereo_wav(tmp_path / "song.wav")
        result = CliRunner().invoke(cli, ["channels", str(tmp_path), "--dry", "--json"])
        assert result.exit_code == 0, result.output + str(result.exception)
        # Click's runner merges the tool's stderr progress lines into output;
        # the JSON document starts at the first brace.
        payload = json.loads(result.output[result.output.index("{") :])
        assert payload["tool"] == "channel_tools"
        assert payload["command"] == "channels"
        assert payload["dry_run"] is True
        assert payload["succeeded"] == 1
        assert (tmp_path / "channel_tools_dry_run_log.txt").is_file()

    def test_a_live_run_writes_the_downmix(self, tmp_path: Path) -> None:
        source = _stereo_wav(tmp_path / "song.wav")
        result = CliRunner().invoke(
            cli,
            ["channels", str(tmp_path), "--live", "--operation", "mono_mean"],
        )
        assert result.exit_code == 0, result.output + str(result.exception)
        from pydub import AudioSegment

        assert AudioSegment.from_file(str(source)).channels == 1
        assert (tmp_path / "channel_tools_sync_log.txt").is_file()

    @pytest.mark.parametrize("width", ["-1", "401"])
    def test_a_width_outside_the_range_is_a_usage_error(
        self, tmp_path: Path, width: str
    ) -> None:
        result = CliRunner().invoke(cli, ["channels", str(tmp_path), "--width", width])
        assert result.exit_code == 2
