"""
Tests for album_genre_tagger.utils.cli_args
Covers parse() argument mapping and validate_args() error detection.
"""

import pytest

from album_genre_tagger.utils.cli_args import (
    GenreTaggerArgs,
    parse,
    validate_args,
)

# ═════════════════════════════════════════════════════════════════════════════
# validate_args
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateArgs:
    def test_no_errors_for_default_args(self):
        args = GenreTaggerArgs()
        assert validate_args(args) == []

    def test_no_errors_for_valid_existing_folder(self, tmp_path):
        args = GenreTaggerArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_error_for_nonexistent_folder(self, tmp_path):
        args = GenreTaggerArgs(folder_path=str(tmp_path / "missing"))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_error_for_file_path_not_directory(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        args = GenreTaggerArgs(folder_path=str(f))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_error_for_coverage_below_zero(self):
        args = GenreTaggerArgs(min_coverage=-1)
        errors = validate_args(args)
        assert any("Coverage" in e for e in errors)

    def test_error_for_coverage_above_100(self):
        args = GenreTaggerArgs(min_coverage=101)
        errors = validate_args(args)
        assert any("Coverage" in e for e in errors)

    def test_no_error_for_coverage_at_boundaries(self):
        assert validate_args(GenreTaggerArgs(min_coverage=0)) == []
        assert validate_args(GenreTaggerArgs(min_coverage=100)) == []


# ═════════════════════════════════════════════════════════════════════════════
# parse — no arguments
# ═════════════════════════════════════════════════════════════════════════════


class TestParseNoArgs:
    def test_returns_default_args_when_only_program_name(self):
        args = parse(["prog"])
        assert args.folder_path == ""
        assert args.min_coverage == 50
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_returns_genretaggerargs_instance(self):
        args = parse(["prog"])
        assert isinstance(args, GenreTaggerArgs)


# ═════════════════════════════════════════════════════════════════════════════
# parse — positional folder path
# ═════════════════════════════════════════════════════════════════════════════


class TestParseFolderPath:
    def test_folder_path_set_from_argv1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# parse — mode flags (argv[2])
# ═════════════════════════════════════════════════════════════════════════════


class TestParseModeFlags:
    def test_live_flag_sets_live_mode_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry"])
        assert args.live_mode is False


# ═════════════════════════════════════════════════════════════════════════════
# parse — auto-start / auto-end flags
# ═════════════════════════════════════════════════════════════════════════════


class TestParseAutoFlags:
    def test_start_flag_sets_auto_start_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry", "--start"])
        assert args.auto_start is True

    def test_no_start_flag_sets_auto_start_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry", "--no-start"])
        assert args.auto_start is False

    def test_end_flag_sets_auto_end_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry", "--start", "--end"])
        assert args.auto_end is True

    def test_no_end_flag_sets_auto_end_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry", "--start", "--no-end"])
        assert args.auto_end is False


# ═════════════════════════════════════════════════════════════════════════════
# parse — --coverage named pair
# ═════════════════════════════════════════════════════════════════════════════


class TestParseCoverage:
    def test_coverage_flag_sets_min_coverage(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage", "75"]
        )
        assert args.min_coverage == 75

    def test_coverage_zero_accepted(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage", "0"]
        )
        assert args.min_coverage == 0

    def test_coverage_100_accepted(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage", "100"]
        )
        assert args.min_coverage == 100

    def test_non_integer_coverage_leaves_default(self, tmp_path):
        """Non-integer coverage keeps default (50) and emits a warning."""
        args = parse(
            ["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage", "abc"]
        )
        assert args.min_coverage == 50

    def test_non_integer_coverage_emits_warning(self, tmp_path, caplog):
        """parse() logs a WARNING when --coverage cannot be converted to int."""
        import logging

        with caplog.at_level(
            logging.WARNING, logger="album_genre_tagger.utils.cli_args"
        ):
            parse(
                [
                    "prog",
                    str(tmp_path),
                    "--dry",
                    "--start",
                    "--end",
                    "--coverage",
                    "abc",
                ]
            )
        assert any("abc" in record.message for record in caplog.records)


# ═════════════════════════════════════════════════════════════════════════════
# parse — named-pair loop starts at argv[5], not argv[4]
# ═════════════════════════════════════════════════════════════════════════════


class TestParseLoopStart:
    def test_end_flag_at_argv4_not_mistaken_for_coverage(self, tmp_path):
        """argv[4] ('--end') must not be re-visited by the named-pair loop."""
        args = parse(
            [
                "prog",
                str(tmp_path),  # argv[1]
                "--dry",  # argv[2]
                "--start",  # argv[3]
                "--end",  # argv[4] — positional; loop must start at argv[5]
                "--coverage",
                "70",
            ]
        )
        assert args.auto_end is True
        assert args.min_coverage == 70

    def test_full_handshake_layout(self, tmp_path):
        """Verify every positional slot maps correctly with no placeholder gaps."""
        args = parse(
            [
                "prog",
                str(tmp_path),  # argv[1] — folder path
                "--live",  # argv[2] — mode
                "--start",  # argv[3] — auto-start
                "--end",  # argv[4] — auto-end
                "--coverage",
                "80",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.min_coverage == 80


# ═════════════════════════════════════════════════════════════════════════════
# parse — invalid args trigger SystemExit
# ═════════════════════════════════════════════════════════════════════════════


class TestParseNamedPairLoopRobustness:
    """The named-pair loop (argv[5+]) was fully exercised for the happy path
    but never for a malformed or unrecognized trailing flag. These document
    that parse() degrades gracefully (keeps the default rather than raising
    an unhandled IndexError/crash) instead of asserting that untested."""

    def test_dangling_coverage_flag_with_no_value_keeps_default(self, tmp_path):
        """'--coverage' as the very last token (no value follows) must not
        raise IndexError; min_coverage should fall back to the default."""
        args = parse(["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage"])
        assert args.min_coverage == 50

    def test_unrecognized_named_flag_does_not_break_subsequent_parsing(self, tmp_path):
        """An unknown flag/value pair ahead of --coverage must be skipped
        token-by-token without disrupting the real --coverage pair after it."""
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--dry",
                "--start",
                "--end",
                "--foo",
                "bar",
                "--coverage",
                "60",
            ]
        )
        assert args.min_coverage == 60


class TestParseInvalidArgs:
    def test_nonexistent_folder_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path / "missing")])

    def test_out_of_range_coverage_raises_system_exit(self, tmp_path):
        with pytest.raises(SystemExit):
            parse(
                [
                    "prog",
                    str(tmp_path),
                    "--dry",
                    "--start",
                    "--end",
                    "--coverage",
                    "999",
                ]
            )


class TestParseInvalidFolderPath:
    """Regression: parse() used to discard validation errors and exit
    silently with SystemExit(1). Errors must now reach stderr."""

    def test_nonexistent_folder_raises_systemexit(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])

    def test_nonexistent_folder_prints_error_to_stderr(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert str(missing) in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_error_message_prefixed_with_tool_name(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "Album Genre Tagger:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


# ═════════════════════════════════════════════════════════════════════════════
# ═════════════════════════════════════════════════════════════════════════════


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = GenreTaggerArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_parse_defaults_when_flags_absent(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--dry", "--start", "--end", "--coverage", "70"]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed_after_named_pairs(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--dry",
                "--start",
                "--end",
                "--coverage",
                "60",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.min_coverage == 60

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--live",
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False
