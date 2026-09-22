"""
Tests for metadata_scrubber.utils.cli_args
Gap: no tests existed for CLI argument parsing and validation.
"""

import pytest

from metadata_scrubber.utils.cli_args import (
    ScrubberArgs,
    parse,
    validate_args,
    was_launched_from_driver,
)


class TestScrubberArgsDefaults:
    def test_all_defaults(self):
        args = ScrubberArgs()
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.preserve_lyrics is True
        assert args.preserve_album_artist is True
        assert args.preserve_embedded_art is True


class TestParse:
    def test_empty_argv_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_folder_path_extracted(self, tmp_path):
        folder = str(tmp_path)
        args = parse(["ignored", folder])
        assert args.folder_path == folder

    def test_live_mode_flag(self, tmp_path):
        args = parse(["ignored", str(tmp_path), "ignored", "--live"])
        assert args.live_mode is True

    def test_dry_mode_default(self, tmp_path):
        args = parse(["ignored", str(tmp_path)])
        assert args.live_mode is False

    def test_auto_start_flag(self, tmp_path):
        args = parse(["ignored", str(tmp_path), "ignored", "ignored", "--start"])
        assert args.auto_start is True

    def test_auto_end_flag(self, tmp_path):
        args = parse(
            ["ignored", str(tmp_path), "ignored", "ignored", "ignored", "--end"]
        )
        assert args.auto_end is True

    def test_no_preserve_lyrics(self, tmp_path):
        folder = str(tmp_path)
        args = parse(
            ["ignored", folder, "ignored", "ignored", "ignored", "--no-preserve-lyrics"]
        )
        assert args.preserve_lyrics is False

    def test_preserve_lyrics_default(self, tmp_path):
        args = parse(["ignored", str(tmp_path)])
        assert args.preserve_lyrics is True

    def test_no_preserve_album_artist(self, tmp_path):
        folder = str(tmp_path)
        args = parse(
            [
                "ignored",
                folder,
                "ignored",
                "ignored",
                "ignored",
                "--no-preserve-album-artist",
            ]
        )
        assert args.preserve_album_artist is False

    def test_no_preserve_embedded_art(self, tmp_path):
        folder = str(tmp_path)
        args = parse(
            [
                "ignored",
                folder,
                "ignored",
                "ignored",
                "ignored",
                "--no-preserve-embedded-art",
            ]
        )
        assert args.preserve_embedded_art is False

    def test_all_flags_combined(self, tmp_path):
        folder = str(tmp_path)
        argv = [
            "ignored",
            folder,
            "--live",
            "--start",
            "--end",
            "--no-preserve-lyrics",
            "--no-preserve-album-artist",
            "--no-preserve-embedded-art",
        ]
        args = parse(argv)
        assert args.folder_path == folder
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.preserve_lyrics is False
        assert args.preserve_album_artist is False
        assert args.preserve_embedded_art is False


class TestWasLaunchedFromDriver:
    """Driver launches always carry CLI args; standalone starts do not."""

    def test_no_args_means_standalone(self):
        assert was_launched_from_driver(["Metadata_Scrubber.pyw"]) is False

    def test_any_argument_means_driven(self):
        assert was_launched_from_driver(["Metadata_Scrubber.pyw", "D:/Music"]) is True

    def test_flag_only_argv_means_driven(self):
        assert was_launched_from_driver(["prog", "--start", "--end"]) is True

    def test_defaults_to_sys_argv(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["prog"])
        assert was_launched_from_driver() is False
        monkeypatch.setattr("sys.argv", ["prog", "D:/Music"])
        assert was_launched_from_driver() is True


class TestValidateArgs:
    def test_no_folder_path_passes(self):
        args = ScrubberArgs()
        errors = validate_args(args)
        assert errors == []

    def test_valid_folder_path_passes(self, tmp_path):
        args = ScrubberArgs(folder_path=str(tmp_path))
        errors = validate_args(args)
        assert errors == []

    def test_nonexistent_path_returns_error(self):
        args = ScrubberArgs(folder_path="/no/such/path")
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0].lower()

    def test_file_path_returns_error(self, tmp_path):
        file_path = tmp_path / "file.txt"
        file_path.write_bytes(b"x")
        args = ScrubberArgs(folder_path=str(file_path))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0].lower()


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
        assert "Metadata Scrubber:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


class TestDriverDisplayFlags:
    """Clear Logs / Parallel handshake flags are display-only state."""

    def test_flags_absent_by_default(self):
        args = parse(["prog"])
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--clear-logs", "--parallel-run"])
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--no-clear-logs", "--no-parallel-run"])
        assert args.clear_logs is False
        assert args.parallel_run is False
