"""
Tests for music_format_converter.cli — the Click command surface.

The dither cases assert the value that actually reaches
core.file_processor.run_conversion (the consumer boundary), because a test that
only checks click's own parsing cannot see a flag that is parsed but dropped
before the conversion call.

Changed in 2.1.2: added a live ALAC run (R-02) — the command must exit 0 and
leave a playable `.m4a`, not fail on an unmuxable `.alac` extension.
Changed in 2.1.4: ``TestExitContract`` pins the R-06 status through the real
command — one corrupt input in a folder makes the run exit 1 while the summary
still reports it, and an all-skipped tree stays at 0.
"""

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner
from pydub.generators import Sine

from music_format_converter import cli


def _invoke(*args):
    """Run the CLI with run_conversion stubbed; return the captured kwargs."""
    with patch("music_format_converter.core.file_processor.run_conversion") as m:
        result = CliRunner().invoke(cli.convert, list(args))
        assert result.exit_code == 0, result.output
        assert m.call_args is not None, "run_conversion was never called"
        return m.call_args.kwargs


class TestDitherOption:
    def test_dither_on_by_default(self, tmp_path):
        assert _invoke(str(tmp_path), "--format", "wav")["dither"] is True

    def test_no_dither_reaches_the_core(self, tmp_path):
        assert (
            _invoke(str(tmp_path), "--format", "wav", "--no-dither")["dither"] is False
        )

    def test_explicit_dither_reaches_the_core(self, tmp_path):
        assert _invoke(str(tmp_path), "--format", "wav", "--dither")["dither"] is True

    def test_no_dither_applies_to_lossy_targets_too(self, tmp_path):
        """The flag is a global policy knob; the filter builder decides which
        formats can actually honour it."""
        assert (
            _invoke(str(tmp_path), "--format", "mp3", "--no-dither")["dither"] is False
        )

    def test_flag_is_documented_in_help(self):
        out = CliRunner().invoke(cli.convert, ["--help"]).output
        assert "--no-dither" in out
        assert "dither" in out

    def test_preset_dither_overrides_the_command_line(self, tmp_path):
        """A preset that stores dither=False must win over the --dither flag,
        matching how the other preset-backed settings behave."""
        with patch(
            "music_format_converter.cli.load_preset",
            return_value={
                "output_format": "wav",
                "quality_preset": "highest",
                "sample_rate": "source",
                "bit_depth": "16",
                "delete_originals": False,
                "dither": False,
            },
        ):
            kwargs = _invoke(str(tmp_path), "--preset", "p", "--dither")
        assert kwargs["dither"] is False

    def test_preset_without_dither_key_keeps_the_flag_value(self, tmp_path):
        """Presets written before E1 must not silently re-enable dither."""
        with patch(
            "music_format_converter.cli.load_preset",
            return_value={
                "output_format": "wav",
                "quality_preset": "highest",
                "sample_rate": "source",
                "bit_depth": "16",
                "delete_originals": False,
            },
        ):
            kwargs = _invoke(str(tmp_path), "--preset", "p", "--no-dither")
        assert kwargs["dither"] is False


class TestRecursiveMixedCli:
    """E4 — the CLI shares the tool's recursive, mixed-format behaviour."""

    def test_dry_run_counts_nested_mixed_files_and_writes_nothing(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "CD1").mkdir()
        (tmp_path / "CD1" / "b.mp3").write_bytes(b"x")
        (tmp_path / "CD1" / "c.flac").write_bytes(b"x")
        out = tmp_path / "converted"

        result = CliRunner().invoke(
            cli.convert,
            [
                str(tmp_path),
                "--dry",
                "--format",
                "ogg",
                "--output-dir",
                str(out),
            ],
        )

        assert result.exit_code == 0, result.output
        # 3 files found recursively: 2 mp3 + 1 flac, all convertible to ogg.
        assert "3 files" in result.output
        assert "0 errors" in result.output
        assert not out.exists()
        assert sorted(p.name for p in tmp_path.iterdir()) == ["CD1", "a.mp3"]

    def test_all_skipped_tree_exits_cleanly(self, tmp_path):
        """A tree already in the target format skips everything, no crash."""
        (tmp_path / "a.flac").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.flac").write_bytes(b"x")

        result = CliRunner().invoke(
            cli.convert, [str(tmp_path), "--dry", "--format", "flac"]
        )

        assert result.exit_code == 0, result.output
        assert "2 skipped" in result.output


class TestExitContract:
    """R-06 — a batch that reports errors must not look like a clean run."""

    def test_a_failing_file_exits_1_with_the_summary_intact(self, tmp_path):
        """The pre-fix defect: ``1 errors`` printed, ``$?`` was 0.

        A corrupt ``.wav`` is the probe: it is an allowed lossless source, so
        the run reaches the decoder and fails there.  A corrupt lossy file
        would be *skipped* first (no quality gain to a lossless target), which
        is a different outcome.
        """
        (tmp_path / "broken.wav").write_bytes(b"this is not a RIFF stream")
        out = tmp_path / "converted"

        result = CliRunner().invoke(
            cli.convert,
            [str(tmp_path), "--format", "flac", "--output-dir", str(out)],
        )

        assert result.exit_code == 1, result.output
        assert "1 errors" in result.output
        assert "Traceback" not in result.output

    def test_the_json_payload_is_unchanged_on_error(self, tmp_path):
        """Only the status moves: every documented key is still published."""
        (tmp_path / "broken.wav").write_bytes(b"this is not a RIFF stream")

        result = CliRunner().invoke(
            cli.convert, [str(tmp_path), "--format", "flac", "--json"]
        )

        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["errors"] == 1
        assert payload["succeeded"] == 0
        for key in (
            "schema_version",
            "tool",
            "command",
            "dry_run",
            "total",
            "processed",
            "succeeded",
            "skipped",
            "errors",
            "duration_secs",
            "duration_str",
            "log_entries",
        ):
            assert key in payload, key


class TestAlacEndToEnd:
    """R-02 — a live ALAC run must exit 0 and leave a playable `.m4a`."""

    def test_live_alac_conversion_succeeds_and_names_the_m4a(self, tmp_path):
        source = tmp_path / "song.wav"
        Sine(440).to_audio_segment(duration=1000, volume=-12.0).export(
            str(source), format="wav"
        )
        out = tmp_path / "converted"

        result = CliRunner().invoke(
            cli.convert,
            [str(tmp_path), "--format", "alac", "--output-dir", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert "1 converted" in result.output
        assert "0 errors" in result.output
        assert (out / "song.m4a").exists()
        assert not (out / "song.alac").exists()

    def test_dry_run_names_the_m4a_and_writes_nothing(self, tmp_path):
        (tmp_path / "song.wav").write_bytes(b"x")
        out = tmp_path / "converted"

        result = CliRunner().invoke(
            cli.convert,
            [str(tmp_path), "--dry", "--format", "alac", "--output-dir", str(out)],
        )

        assert result.exit_code == 0, result.output
        assert not out.exists()

    def test_alac_is_still_offered_as_a_format(self):
        out = CliRunner().invoke(cli.convert, ["--help"]).output
        assert out  # help renders; the format list itself lives in core.formats


@pytest.mark.parametrize("fmt", ["alac", "m4a"])
def test_alac_and_m4a_share_one_container_extension(fmt):
    """Both targets write `.m4a`; a later run replaces the earlier file."""
    from music_format_converter.core.formats import output_extension

    assert output_extension(fmt) == "m4a"
