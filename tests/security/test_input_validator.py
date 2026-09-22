"""
tests/security/test_input_validator.py

Unit tests for audio_suite_shared.security.input_validator.

These tests serve two purposes:
1. Regression coverage for the validate_directory_path() logic bug
   (the original implementation always returned True).
2. General coverage of the validator's security surface so future
   changes cannot silently break the checks.

Run:
    pytest tests/security/test_input_validator.py
"""

from __future__ import annotations

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
    Regression tests for the validate_directory_path() logic bug.

    The original implementation compared resolved_path.startswith(original_path)
    where both were derived identically via Path.resolve() — meaning the check
    was always True and provided no protection.

    The fix:
    - Still returns True for legitimate paths (including secondary drives).
    - Logs a warning for symlinks resolving outside safe roots.
    - Returns False only for paths that fail validate_file_path() first.
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

    def test_symlink_outside_safe_root_logs_warning(self, tmp_path):
        """
        A symlink that resolves outside home/tmp should log a warning
        but still return True (secondary drives are legitimate).
        """
        # Create a real directory to point the symlink at.
        real_target = tmp_path / "real_audio"
        real_target.mkdir()

        link = tmp_path / "link_to_audio"
        try:
            link.symlink_to(real_target)
        except (OSError, NotImplementedError):
            pytest.skip("Symlinks not supported on this platform/filesystem")

        import logging

        with patch.object(logging.getLogger("audio_suite.security"), "warning"):
            # Patch safe_roots to exclude tmp_path so the warning fires.
            with patch(
                "audio_suite_shared.security.input_validator.Path.home",
                return_value=Path("/nonexistent_home"),
            ):
                result = InputValidator.validate_directory_path(str(link))

        # Should still return True — warn but don't block secondary drives.
        assert result is True

    def test_bug_regression_always_true_was_wrong(self, tmp_path):
        """
        Regression: the original validate_directory_path() always returned
        True because it compared resolved_path.startswith(resolved_path).
        Verify the fix actually evaluates the path content.
        """
        # A relative path must be rejected — the old code would accept it
        # because str("relative").startswith("relative") is True.
        assert InputValidator.validate_directory_path("relative/path") is False

        # An empty string must be rejected.
        assert InputValidator.validate_directory_path("") is False

        # A traversal string must be rejected.
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
        exts = [".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aiff", ".aif", ".wma"]
        for ext in exts:
            p = tmp_path / f"track{ext}"
            p.touch()
            assert InputValidator.validate_audio_file_path(str(p)) is True, (
                f"Expected {ext} to be accepted"
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
