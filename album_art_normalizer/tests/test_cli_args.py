"""
Tests for album_art_normalizer.utils.cli_args
Covers: parse(), AlbumArtNormalizerArgs dataclass,
was_launched_from_driver() and the display-only driver flags.
"""

import pytest

from album_art_normalizer.utils.cli_args import (
    AlbumArtNormalizerArgs,
    parse,
)

# ═════════════════════════════════════════════════════════════════════════════
# parse / defaults
# ═════════════════════════════════════════════════════════════════════════════


class TestParseDefaults:
    def test_bare_argv_returns_defaults(self):
        args = parse(["prog"])
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_empty_argv_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""

    def test_returns_album_art_normalizer_args_instance(self):
        args = parse(["prog"])
        assert isinstance(args, AlbumArtNormalizerArgs)


# ═════════════════════════════════════════════════════════════════════════════
# parse / positional
# ═════════════════════════════════════════════════════════════════════════════


class TestParsePositional:
    def test_folder_path_from_argv1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# parse / mode flags
# ═════════════════════════════════════════════════════════════════════════════


class TestParseModeFlags:
    def test_dry_flag(self, tmp_path):
        assert parse(["prog", str(tmp_path), "--dry"]).live_mode is False

    def test_live_flag(self, tmp_path):
        assert parse(["prog", str(tmp_path), "--live"]).live_mode is True

    def test_legacy_ignored_positional_still_parses_flags(self, tmp_path):
        """Backward compat: driver emits [path, '0', --live, ...]."""
        args = parse(["prog", str(tmp_path), "0", "--live"])
        assert args.live_mode is True
        assert args.folder_path == str(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# parse / start / end flags
# ═════════════════════════════════════════════════════════════════════════════


class TestParseStartEndFlags:
    def test_start_and_end(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start", "--end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_no_start_no_end(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--start", "--end", "--no-start", "--no-end"]
        )
        assert args.auto_start is False
        assert args.auto_end is False


# ═════════════════════════════════════════════════════════════════════════════
# driver display flags
# ═════════════════════════════════════════════════════════════════════════════


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = AlbumArtNormalizerArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry", "--clear-logs", "--parallel-run"])
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--live", "--no-clear-logs", "--no-parallel-run"]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False


# ═════════════════════════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════════════════════════════════


class TestFolderValidation:
    """Regression: a bad Master Driver handshake used to reach the GUI
    unchallenged; it must now exit cleanly with the reason on stderr."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc_info:
            parse(["prog", "/totally/nonexistent/path/xyz"])
        assert exc_info.value.code == 1

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "/totally/nonexistent/path/xyz" in captured.err

    def test_error_message_prefixed_with_tool_name(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "Album Art Normalizer:" in captured.err

    def test_file_instead_of_directory_raises_systemexit(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_valid_folder_parses_without_output(self, tmp_path, capsys):
        result = parse(["prog", str(tmp_path)])
        captured = capsys.readouterr()
        assert result.folder_path == str(tmp_path)
        assert captured.out == ""
        assert captured.err == ""

    def test_empty_folder_stays_legal(self, capsys):
        """Double-click / GUI-only launches pass no folder — must not exit."""
        result = parse(["prog"])
        captured = capsys.readouterr()
        assert result.folder_path == ""
        assert captured.err == ""


# ═════════════════════════════════════════════════════════════════════════════
# parse / --size (G2.5)
# ═════════════════════════════════════════════════════════════════════════════


class TestParseSize:
    """G2.5: the driver's ``--size <n>`` must be consumed by the parser."""

    def test_size_parsed_from_driver_argv(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--live",
                "--start",
                "--end",
                "--size",
                "800",
            ]
        )
        assert args.size == "800"
        assert args.folder_path == str(tmp_path)

    def test_size_absent_by_default(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.size == ""

    def test_size_without_value_is_ignored(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--size"])
        assert args.size == ""
