"""
tests/security/test_input_validator.py

Unit tests for audio_suite_shared.security.input_validator.

General coverage of the validator's security surface so future changes cannot
silently break the checks.

Run:
    pytest tests/security/test_input_validator.py
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from audio_suite_shared.security.input_validator import InputValidator

# ===========================================================================
# validate_file_path
# ===========================================================================


class TestValidateFilePath:
    def test_valid_absolute_path_accepted(self, tmp_path):
        p = tmp_path / "track.mp3"
        p.touch()
        assert InputValidator.validate_file_path(str(p)) is True

    def test_relative_path_rejected(self):
        assert InputValidator.validate_file_path("relative/path.mp3") is False

    def test_empty_string_rejected(self):
        assert InputValidator.validate_file_path("") is False

    def test_none_rejected(self):
        assert InputValidator.validate_file_path(None) is False

    def test_directory_traversal_rejected(self, tmp_path):
        traversal = str(tmp_path / ".." / "etc" / "passwd")
        assert InputValidator.validate_file_path(traversal) is False

    def test_path_exceeding_max_length_rejected(self, tmp_path):
        long_name = "a" * 300
        p = str(tmp_path / long_name)
        assert InputValidator.validate_file_path(p) is False

    @pytest.mark.skipif(os.name != "nt", reason="Windows reserved names only")
    def test_reserved_windows_name_rejected(self, tmp_path):
        p = str(tmp_path / "CON")
        assert InputValidator.validate_file_path(p) is False

    def test_angle_brackets_rejected(self, tmp_path):
        p = str(tmp_path / "<script>.mp3")
        assert InputValidator.validate_file_path(p) is False

    @pytest.mark.skipif(os.name != "nt", reason="Windows-style path")
    def test_hash_in_path_accepted(self, tmp_path):
        p = str(tmp_path / "2022 - NOW #1s_ 70 Years of the Official Singles Chart")
        assert InputValidator.validate_file_path(p) is True


# ===========================================================================
# validate_directory_path  — regression tests for the fixed bug
# ===========================================================================


class TestValidateDirectoryPath:
    """
    Coverage for validate_directory_path().

    The current implementation rejects only what validate_file_path() rejects
    (relative paths, traversal, unsafe characters) and additionally *warns*
    when a path traverses a symlink whose target sits outside the home and
    temp roots.  A non-existent path is allowed because the caller may be
    about to create it.
    """

    def test_existing_directory_accepted(self, tmp_path):
        assert InputValidator.validate_directory_path(str(tmp_path)) is True

    def test_non_existent_path_returns_true(self, tmp_path):
        # Not-yet-created directories are allowed — caller may create them.
        p = str(tmp_path / "new_output_folder")
        assert InputValidator.validate_directory_path(p) is True

    def test_empty_string_rejected(self):
        assert InputValidator.validate_directory_path("") is False

    def test_none_rejected(self):
        assert InputValidator.validate_directory_path(None) is False

    def test_directory_traversal_rejected(self, tmp_path):
        traversal = str(tmp_path / ".." / "etc")
        assert InputValidator.validate_directory_path(traversal) is False

    def test_relative_path_rejected(self):
        assert InputValidator.validate_directory_path("Music/Albums") is False

    @pytest.mark.skipif(os.name != "nt", reason="Windows-style path")
    def test_hash_in_album_folder_name_accepted(self, tmp_path):
        p = str(
            tmp_path
            / "Various Artists"
            / "2022 - NOW #1s_ 70 Years of the Official Singles Chart"
        )
        assert InputValidator.validate_directory_path(p) is True

    def test_home_subdirectory_accepted(self):
        home_music = str(Path.home() / "Music")
        # May or may not exist — both should be accepted.
        result = InputValidator.validate_directory_path(home_music)
        assert result is True

    def test_temp_directory_accepted(self):
        tmp = tempfile.gettempdir()
        assert InputValidator.validate_directory_path(tmp) is True

    def test_symlink_outside_safe_root_logs_warning(self, tmp_path, caplog):
        """
        A symlink that resolves outside home/tmp logs a warning but is still
        permitted (secondary drives are legitimate).

        The branch is exercised through a simulated link so the assertion holds
        on hosts where creating a symlink requires privileges.
        """
        # Pin the safe roots away from the resolved target.
        safe_home = tmp_path / "fake_home"
        safe_tmp = tmp_path / "fake_tmp"
        safe_home.mkdir()
        safe_tmp.mkdir()
        target = tmp_path / "secondary_drive"
        target.mkdir()
        link = tmp_path / "link_to_audio"
        link.mkdir()

        original_resolve = Path.resolve

        def _resolve(self, *args, **kwargs):
            return target if self == link else original_resolve(self, *args, **kwargs)

        with (
            patch.object(Path, "home", classmethod(lambda _cls: safe_home)),
            patch("tempfile.gettempdir", return_value=str(safe_tmp)),
            patch.object(Path, "resolve", _resolve),
            caplog.at_level(logging.WARNING),
        ):
            result = InputValidator.validate_directory_path(str(link))

        # Should still return True — warn but don't block secondary drives.
        assert result is True
        assert "Directory symlink resolves outside safe roots" in caplog.text
        assert str(target) in caplog.text

    def test_validation_is_not_vacuous(self, tmp_path):
        """
        validate_directory_path() must actually reject unsafe paths: a relative
        path, an empty string and a traversal string are all refused.
        """
        assert InputValidator.validate_directory_path("relative/path") is False
        assert InputValidator.validate_directory_path("") is False
        assert InputValidator.validate_directory_path("../../../etc") is False


# ===========================================================================
# sanitize_input
# ===========================================================================


class TestSanitizeInput:
    def test_strips_angle_brackets(self):
        result = InputValidator.sanitize_input("<script>alert(1)</script>")
        assert "<" not in result
        assert ">" not in result

    def test_strips_quotes(self):
        result = InputValidator.sanitize_input('it\'s a "test"')
        assert '"' not in result
        assert "'" in result  # single quotes are valid in filenames

    def test_strips_ampersand(self):
        result = InputValidator.sanitize_input("cats & dogs")
        assert "&" not in result

    def test_strips_control_characters(self):
        result = InputValidator.sanitize_input("hello\x00world\x1f")
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_enforces_max_length(self):
        long_input = "a" * 200
        result = InputValidator.sanitize_input(long_input, max_length=50)
        assert len(result) <= 50

    def test_empty_string_returns_empty(self):
        assert InputValidator.sanitize_input("") == ""

    def test_none_returns_empty(self):
        assert InputValidator.sanitize_input(None) == ""

    def test_normal_text_preserved(self):
        result = InputValidator.sanitize_input("Normal album name 2024")
        assert result == "Normal album name 2024"


# ===========================================================================
# validate_filename
# ===========================================================================


class TestValidateFilename:
    def test_valid_audio_filename_accepted(self):
        assert InputValidator.validate_filename("01 - Track One.flac") is True

    def test_empty_rejected(self):
        assert InputValidator.validate_filename("") is False

    def test_directory_traversal_rejected(self):
        assert InputValidator.validate_filename("../secret.txt") is False

    def test_filename_too_long_rejected(self):
        assert InputValidator.validate_filename("a" * 300) is False

    def test_null_byte_rejected(self):
        assert InputValidator.validate_filename("track\x00.mp3") is False

    @pytest.mark.skipif(os.name != "nt", reason="Windows reserved names only")
    def test_windows_reserved_name_without_ext_rejected(self):
        assert InputValidator.validate_filename("NUL.mp3") is False


# ===========================================================================
# validate_audio_file_path
# ===========================================================================


class TestValidateAudioFilePath:
    def test_existing_mp3_accepted(self, tmp_path):
        p = tmp_path / "track.mp3"
        p.touch()
        assert InputValidator.validate_audio_file_path(str(p)) is True

    def test_existing_flac_accepted(self, tmp_path):
        p = tmp_path / "album.flac"
        p.touch()
        assert InputValidator.validate_audio_file_path(str(p)) is True

    def test_txt_file_rejected(self, tmp_path):
        p = tmp_path / "notes.txt"
        p.touch()
        assert InputValidator.validate_audio_file_path(str(p)) is False

    def test_non_existent_file_rejected(self, tmp_path):
        p = tmp_path / "missing.mp3"
        assert InputValidator.validate_audio_file_path(str(p)) is False

    def test_directory_rejected(self, tmp_path):
        assert InputValidator.validate_audio_file_path(str(tmp_path)) is False

    def test_all_allowed_extensions(self, tmp_path):
        """The accepted set tracks audio_formats.SUPPORTED_EXTENSIONS exactly."""
        from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS

        for ext in SUPPORTED_EXTENSIONS:
            p = tmp_path / f"track{ext}"
            p.touch()
            assert InputValidator.validate_audio_file_path(str(p)) is True, (
                f"Expected {ext} to be accepted"
            )

        for ext in (".wma", ".txt"):
            p = tmp_path / f"track{ext}"
            p.touch()
            assert InputValidator.validate_audio_file_path(str(p)) is False, (
                f"Expected {ext} to be rejected"
            )


# ===========================================================================
# sanitize_api_input
# ===========================================================================


class TestSanitizeApiInput:
    def test_strips_semicolons(self):
        result = InputValidator.sanitize_api_input("value; DROP TABLE users;")
        assert ";" not in result

    def test_enforces_200_char_limit(self):
        result = InputValidator.sanitize_api_input("x" * 300)
        assert len(result) <= 200

    def test_none_returns_empty(self):
        assert InputValidator.sanitize_api_input(None) == ""

    def test_clean_string_preserved(self):
        s = "Pink Floyd The Wall 1979"
        assert InputValidator.sanitize_api_input(s) == s
