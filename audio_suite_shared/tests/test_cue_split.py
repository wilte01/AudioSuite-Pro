"""
tests/test_cue_split.py — tests for audio_suite_shared/cue_split.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.cue_parser import CueParseError
from audio_suite_shared.cue_split import (
    _clean_meta,
    _ffmpeg_time,
    _safe_filename,
    split_cue_file,
)
from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioFileNotFoundError,
)
from audio_suite_shared.secure_subprocess import validate_arguments

TWO_TRACK_SHEET = """\
PERFORMER "Artist"
TITLE "Album"
FILE "Album.flac" FLAC
  TRACK 01 AUDIO
    TITLE "First"
    INDEX 01 00:00:00
  TRACK 02 AUDIO
    TITLE "Second"
    INDEX 01 03:45:00
"""


@pytest.fixture
def image_file(tmp_path: Path) -> Path:
    image = tmp_path / "Album.flac"
    image.write_bytes(b"not really flac data")
    return image


@pytest.fixture
def cue_file(tmp_path: Path, image_file: Path) -> Path:
    cue = tmp_path / "Album.cue"
    cue.write_text(TWO_TRACK_SHEET, encoding="utf-8")
    return cue


def _ok_proc() -> MagicMock:
    proc = MagicMock()
    proc.returncode = 0
    proc.stderr = ""
    proc.stdout = ""
    return proc


class TestHelpers:
    def test_safe_filename_replaces_illegal_chars(self):
        assert _safe_filename('A:B/C*D"E') == "A_B_C_D_E"

    def test_safe_filename_strips_edges(self):
        assert _safe_filename("  Title  ") == "Title"

    def test_clean_meta_removes_dangerous_chars(self):
        cleaned = _clean_meta('Rock & Roll "Greatest" <Live>')
        assert '"' not in cleaned
        assert "<" not in cleaned
        assert "&" not in cleaned

    def test_clean_meta_preserves_normal_text(self):
        assert _clean_meta("Apostle's Creed") == "Apostle's Creed"

    def test_ffmpeg_time_formats_milliseconds(self):
        assert _ffmpeg_time(0) == "0.000"
        assert _ffmpeg_time(2533) == "2.533"
        assert _ffmpeg_time(225000) == "225.000"


class TestSplitCueFile:
    def test_splits_two_tracks_with_metadata(self, tmp_path: Path, cue_file: Path):
        out_dir = tmp_path / "out"
        calls: list[list[str]] = []
        progress: list[str] = []

        def _fake_run(ffmpeg: str, args: list[str], **kwargs) -> MagicMock:
            calls.append(args)
            proc = MagicMock()
            proc.returncode = 0
            proc.stderr = ""
            return proc

        with patch(
            "audio_suite_shared.cue_split.run_secure_subprocess", side_effect=_fake_run
        ):
            written = split_cue_file(cue_file, out_dir, progress_cb=progress.append)

        assert len(written) == 2
        assert written[0].endswith("01 - First.flac")
        assert written[1].endswith("02 - Second.flac")
        assert progress == ["Track 01: First", "Track 02: Second"]
        assert len(calls) == 2

        first_args = calls[0]
        assert "-i" in first_args
        assert "-ss" in first_args
        # First track started at 0 → -to is the second track's 03:45 (225 s)
        assert first_args.index("-ss") < first_args.index("-i")
        first_args_str = " ".join(first_args)
        assert "225.000" in first_args_str  # -to for track 1
        assert "title=First" in first_args_str
        assert "artist=Artist" in first_args_str
        assert "album=Album" in first_args_str
        assert "track=01" in first_args_str
        assert "-map_metadata" in first_args_str and "-1" in first_args_str

        second_args_str = " ".join(calls[1])
        assert "225.000" in second_args_str  # -ss for track 2
        assert "-to" not in second_args_str  # last track runs to EOF

    def test_args_are_validation_safe(self, tmp_path: Path, cue_file: Path):
        """Arguments handed to run_secure_subprocess must pass its validator."""
        captured: list[list[str]] = []

        def _fake_run(ffmpeg: str, args: list[str], **kwargs) -> MagicMock:
            captured.append(args)
            validate_arguments(args)
            return _ok_proc()

        with patch(
            "audio_suite_shared.cue_split.run_secure_subprocess", side_effect=_fake_run
        ):
            split_cue_file(cue_file, tmp_path / "out")

        assert captured, "no ffmpeg invocation recorded"

    def test_missing_index01_raises(self, tmp_path: Path, image_file: Path):
        cue = tmp_path / "no_index.cue"
        cue.write_text(
            'FILE "Album.flac" FLAC\n  TRACK 01 AUDIO\n    TITLE "No Index"\n',
            encoding="utf-8",
        )
        with patch("audio_suite_shared.cue_split.run_secure_subprocess"):
            with pytest.raises(ValueError, match="INDEX 01"):
                split_cue_file(cue, tmp_path / "out")

    def test_missing_image_raises(self, tmp_path: Path):
        cue = tmp_path / "missing.cue"
        cue.write_text(
            'FILE "Nope.flac" FLAC\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        with pytest.raises(AudioFileNotFoundError):
            split_cue_file(cue, tmp_path / "out")

    def test_unsupported_image_format_raises(self, tmp_path: Path):
        image = tmp_path / "Album.wma"
        image.write_bytes(b"wma data")
        cue = tmp_path / "wma.cue"
        cue.write_text(
            'FILE "Album.wma" WMA\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="not a supported split target"):
            split_cue_file(cue, tmp_path / "out")

    def test_sheet_with_no_tracks_raises(self, tmp_path: Path, image_file: Path):
        cue = tmp_path / "empty.cue"
        cue.write_text('FILE "Album.flac" FLAC\n', encoding="utf-8")
        with pytest.raises(ValueError, match="no FILE entries with tracks"):
            split_cue_file(cue, tmp_path / "out")

    def test_sheet_with_no_files_raises(self, tmp_path: Path):
        cue = tmp_path / "bare.cue"
        cue.write_text('TITLE "Album"\n', encoding="utf-8")
        with pytest.raises(ValueError, match="no FILE entries with tracks"):
            split_cue_file(cue, tmp_path / "out")

    def test_ffmpeg_failure_raises_external_tool_error(
        self, tmp_path: Path, cue_file: Path
    ):
        proc = MagicMock()
        proc.returncode = 1
        proc.stderr = "Error: invalid data found"

        with patch(
            "audio_suite_shared.cue_split.run_secure_subprocess", return_value=proc
        ):
            with pytest.raises(
                AudioExternalToolError, match="Failed to split track 01"
            ):
                split_cue_file(cue_file, tmp_path / "out")

    def test_malformed_sheet_raises_parse_error(self, tmp_path: Path):
        cue = tmp_path / "bad.cue"
        cue.write_text("TRACK 01 AUDIO\n", encoding="utf-8")
        with pytest.raises(CueParseError):
            split_cue_file(cue, tmp_path / "out")

    def test_relative_image_resolved_from_cue_dir(self, tmp_path: Path):
        """A FILE reference relative to the CUE sheet must resolve even when
        the working directory is somewhere else entirely."""
        sub = tmp_path / "sub"
        sub.mkdir()
        image = sub / "Album.flac"
        image.write_bytes(b"data")
        cue = sub / "Album.cue"
        cue.write_text(
            'FILE "Album.flac" FLAC\n  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n',
            encoding="utf-8",
        )
        captured: list[list[str]] = []

        def _fake_run(ffmpeg: str, args: list[str], **kwargs) -> MagicMock:
            captured.append(args)
            return _ok_proc()

        with patch(
            "audio_suite_shared.cue_split.run_secure_subprocess", side_effect=_fake_run
        ):
            written = split_cue_file(cue, tmp_path / "out")
        assert captured
        assert str(image) in " ".join(captured[0])
        assert written[0].endswith("01 - Track 01.flac")

    def test_output_directory_is_created(self, tmp_path: Path, cue_file: Path):
        out_dir = tmp_path / "deep" / "nested" / "out"
        with patch(
            "audio_suite_shared.cue_split.run_secure_subprocess",
            return_value=_ok_proc(),
        ):
            split_cue_file(cue_file, out_dir)
        assert out_dir.is_dir()
