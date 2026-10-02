"""
Tests for music_format_converter.cli — the Click command surface.

The dither cases assert the value that actually reaches
core.file_processor.run_conversion (the consumer boundary), because a test that
only checks click's own parsing cannot see a flag that is parsed but dropped
before the conversion call.
"""

from unittest.mock import patch

from click.testing import CliRunner

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
