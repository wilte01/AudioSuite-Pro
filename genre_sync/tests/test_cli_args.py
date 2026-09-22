"""
Tests for genre_sync.utils.cli_args
Covers: GenreSyncArgs, validate_args(), parse()
"""

import pytest

from genre_sync.utils.cli_args import (
    GenreSyncArgs,
    parse,
    validate_args,
)

# ── validate_args ─────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_no_folder_path_returns_no_errors(self):
        args = GenreSyncArgs()
        assert validate_args(args) == []

    def test_valid_existing_directory_returns_no_errors(self, tmp_path):
        args = GenreSyncArgs()
        args.folder_path = str(tmp_path)
        assert validate_args(args) == []

    def test_nonexistent_path_returns_error(self):
        args = GenreSyncArgs()
        args.folder_path = "/does/not/exist/at/all"
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_instead_of_directory_returns_error(self, tmp_path):
        file_path = tmp_path / "test.txt"
        file_path.write_text("x")
        args = GenreSyncArgs()
        args.folder_path = str(file_path)
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_returns_list_type(self):
        args = GenreSyncArgs()
        result = validate_args(args)
        assert isinstance(result, list)

    def test_error_message_contains_bad_path(self):
        args = GenreSyncArgs()
        args.folder_path = "/bad/path"
        errors = validate_args(args)
        assert "/bad/path" in errors[0]


# ── parse ─────────────────────────────────────────────────────────────────────


class TestParse:
    def test_no_args_returns_empty_args(self):
        result = parse(["program"])
        assert result.folder_path is None or result.folder_path == ""

    def test_folder_path_set_from_argv_1(self, tmp_path):
        result = parse(["program", str(tmp_path)])
        assert result.folder_path == str(tmp_path)

    def test_live_flag_sets_live_mode_true(self, tmp_path):
        result = parse(["program", str(tmp_path), "ignored", "--live"])
        assert result.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        result = parse(["program", str(tmp_path), "ignored", "--dry"])
        assert result.live_mode is False

    def test_start_flag_sets_auto_start_true(self, tmp_path):
        result = parse(["program", str(tmp_path), "ignored", "--live", "--start"])
        assert result.auto_start is True

    def test_no_start_flag_sets_auto_start_false(self, tmp_path):
        result = parse(["program", str(tmp_path), "ignored", "--live", "--no-start"])
        assert result.auto_start is False

    def test_end_flag_sets_auto_end_true(self, tmp_path):
        result = parse(
            ["program", str(tmp_path), "ignored", "--live", "--start", "--end"]
        )
        assert result.auto_end is True

    def test_no_end_flag_sets_auto_end_false(self, tmp_path):
        result = parse(
            ["program", str(tmp_path), "ignored", "--live", "--start", "--no-end"]
        )
        assert result.auto_end is False

    def test_returns_genre_sync_args_instance(self, tmp_path):
        result = parse(["program", str(tmp_path)])
        assert isinstance(result, GenreSyncArgs)

    def test_nonexistent_folder_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse(["program", "/totally/nonexistent/path/xyz"])

    def test_file_path_instead_of_dir_raises_system_exit(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(SystemExit):
            parse(["program", str(f)])

    def test_insufficient_argv_returns_default_args(self):
        result = parse(["program"])
        # Should not raise; folder_path should be falsy
        assert not result.folder_path

    def test_default_flags_are_false(self):
        result = parse(["program"])
        assert result.live_mode is False
        assert result.auto_start is False
        assert result.auto_end is False

    def test_folder_only_keeps_default_flags(self, tmp_path):
        result = parse(["program", str(tmp_path)])
        assert result.folder_path == str(tmp_path)
        assert result.live_mode is False
        assert result.auto_start is False
        assert result.auto_end is False

    def test_parse_uses_sys_argv_when_none(self):
        import sys

        saved = sys.argv
        try:
            sys.argv = ["program"]
            result = parse()
            assert not result.folder_path
        finally:
            sys.argv = saved


class TestParseInvalidFolderPath:
    """Regression: parse() used to discard validation errors and exit
    silently with SystemExit(1). Errors must now reach stderr."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit):
            parse(["program", "/totally/nonexistent/path/xyz"])

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            parse(["program", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "/totally/nonexistent/path/xyz" in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["program", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_error_message_prefixed_with_tool_name(self, capsys):
        with pytest.raises(SystemExit):
            parse(["program", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "Genre Sync:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, capsys):
        with pytest.raises(SystemExit):
            parse(["program", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert captured.out == ""


# ═════════════════════════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════════════════════════════════


class TestDriverDisplayFlags:
    """argv[6]/argv[7] carry display-only Clear Logs / Parallel state."""

    def test_flags_default_false(self):
        args = GenreSyncArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_parse_defaults_when_flags_absent(self, tmp_path):
        args = parse(["prog", str(tmp_path), "0", "--dry", "--start", "--end"])
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--live",
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_partial_trailing_flags(self, tmp_path):
        """Only argv[6] present — argv[7] absent keeps default."""
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--no-start",
                "--no-end",
                "--clear-logs",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is False
