"""
Tests for album_art_sync.utils.cli_args

Covers:
    - validate_args: folder path, embed size, min dimension and threshold checks
    - parse: happy path argument assignment (order-independent flags)
    - parse: invalid folder path exits with errors printed to stderr
      (regression — previously exited silently with no message anywhere)
"""

import pytest

from album_art_sync.config.settings import ALBUM_MATCH_THRESHOLD, MIN_ART_DIMENSION
from album_art_sync.utils.cli_args import ArtArgs, parse, validate_args

# ── validate_args ─────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_default_args_return_no_errors(self):
        assert validate_args(ArtArgs()) == []

    def test_valid_directory_returns_no_errors(self, tmp_path):
        args = ArtArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_nonexistent_folder_path_returns_error(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        args = ArtArgs(folder_path=str(missing))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_instead_of_directory_returns_error(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        args = ArtArgs(folder_path=str(file_path))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    @pytest.mark.parametrize("size", ["600", "800", "1000", "1200"])
    def test_valid_embed_size_returns_no_errors(self, size):
        args = ArtArgs(embed_size=size)
        assert validate_args(args) == []

    @pytest.mark.parametrize("size", ["500", "999", "2000"])
    def test_invalid_embed_size_returns_error(self, size):
        args = ArtArgs(embed_size=size)
        errors = validate_args(args)
        assert any("Embed size must be one of" in e for e in errors)

    def test_non_numeric_embed_size_returns_error(self):
        args = ArtArgs(embed_size="abc")
        errors = validate_args(args)
        assert any("Embed size must be numeric" in e for e in errors)

    def test_empty_embed_size_is_not_validated(self):
        args = ArtArgs(embed_size="")
        assert validate_args(args) == []

    def test_valid_min_dimension_returns_no_errors(self):
        args = ArtArgs(min_art_dimension=800)
        assert validate_args(args) == []

    def test_min_dimension_below_range_returns_error(self):
        args = ArtArgs(min_art_dimension=100)
        errors = validate_args(args)
        assert any("Min dimension must be between 200 and 2000" in e for e in errors)

    def test_min_dimension_above_range_returns_error(self):
        args = ArtArgs(min_art_dimension=3000)
        errors = validate_args(args)
        assert any("Min dimension must be between 200 and 2000" in e for e in errors)

    def test_valid_match_threshold_returns_no_errors(self):
        args = ArtArgs(album_match_threshold=0.75)
        assert validate_args(args) == []

    def test_match_threshold_zero_returns_error(self):
        args = ArtArgs(album_match_threshold=0.0)
        errors = validate_args(args)
        assert any("Match threshold must be between 0.0 and 1.0" in e for e in errors)

    def test_match_threshold_above_one_returns_error(self):
        args = ArtArgs(album_match_threshold=1.1)
        errors = validate_args(args)
        assert any("Match threshold must be between 0.0 and 1.0" in e for e in errors)


# ── parse — happy path ────────────────────────────────────────────────────────


class TestParseHappyPath:
    def test_no_args_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""
        assert args.embed_size == "800"
        assert args.purge is True
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.min_art_dimension == MIN_ART_DIMENSION
        assert args.album_match_threshold == ALBUM_MATCH_THRESHOLD

    def test_min_dimension_flag_captures_value(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--min-dimension", "600"])
        assert args.min_art_dimension == 600

    def test_match_threshold_flag_captures_value(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--match-threshold", "0.90"])
        assert args.album_match_threshold == 0.90

    def test_flags_combined_in_full_driver_vector(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--live",
                "--start",
                "--end",
                "--embed-size",
                "1000",
                "--min-dimension",
                "400",
                "--match-threshold",
                "0.70",
                "--purge",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.embed_size == "1000"
        assert args.min_art_dimension == 400
        assert args.album_match_threshold == 0.70
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True

    def test_non_numeric_min_dimension_raises_systemexit(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "--min-dimension", "big"])
        captured = capsys.readouterr()
        assert "Min dimension must be numeric" in captured.err

    def test_non_numeric_match_threshold_raises_systemexit(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "--match-threshold", "high"])
        captured = capsys.readouterr()
        assert "Match threshold must be numeric" in captured.err

    def test_out_of_range_min_dimension_raises_systemexit(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "--min-dimension", "50"])
        captured = capsys.readouterr()
        assert "between 200 and 2000" in captured.err

    def test_folder_path_set_from_argv_1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_live_flag_sets_live_mode_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry"])
        assert args.live_mode is False

    def test_start_and_end_flags(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start", "--end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_no_purge_flag_disables_purge(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--no-purge"])
        assert args.purge is False

    def test_purge_enabled_by_default(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.purge is True

    def test_embed_size_flag_captures_value(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--embed-size", "1000"])
        assert args.embed_size == "1000"

    def test_flags_are_order_independent_after_folder(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "--embed-size", "1200", "--no-purge", "--start"]
        )
        assert args.folder_path == str(tmp_path)
        assert args.embed_size == "1200"
        assert args.purge is False
        assert args.auto_start is True


# ── parse — invalid folder path (regression) ──────────────────────────────────


class TestParseInvalidFolderPath:
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
        assert "Album Art Sync:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


# ── was_launched_from_driver + display-only driver flags ─────────────────────


class TestWasLaunchedFromDriver:
    def test_true_when_argv_has_arguments(self):
        from album_art_sync.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver(["script.py", "C:/music"]) is True

    def test_false_for_bare_argv(self):
        from album_art_sync.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver(["script.py"]) is False

    def test_false_for_empty_argv(self):
        from album_art_sync.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver([]) is False


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = ArtArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--dry",
                "--start",
                "--end",
                "--embed-size",
                "1000",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.embed_size == "1000"

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
