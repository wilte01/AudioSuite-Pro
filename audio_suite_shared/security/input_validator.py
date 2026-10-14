r"""
input_validator.py — Secure input validation and sanitisation utilities.

Changed in 1.0.1: added tilde (~) to SAFE_PATH_PATTERN to allow Windows
short username paths (e.g., C:\Users\RUNNER~1\AppData\Local\Temp).
Changed in 1.0.1: changed docstring to raw string (r"") to avoid unicode
escape error with backslashes in Windows path example.

Provides validation for file paths, user inputs, and other potentially
dangerous data to prevent injection attacks and security vulnerabilities.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS

logger = logging.getLogger(f"audio_suite.{__name__}")


class InputValidator:
    """Validates and sanitises user inputs for security."""

    # Allowed characters for file paths.
    SAFE_PATH_PATTERN = re.compile(r"^[a-zA-Z0-9_\-./\\: ,\'&!+()#~]+$")

    # The audio extensions this validator accepts. Derived from the suite's
    # single declared source of truth (audio_suite_shared.audio_formats) so a
    # newly supported format cannot drift out of the security gate.
    AUDIO_EXTENSIONS = frozenset(SUPPORTED_EXTENSIONS)

    # Dangerous patterns to block.
    DANGEROUS_PATTERNS = [
        r"\\\.\.\\|/\.\./|^\\\.\.| /\.\.|\\\.\.$|/\.\.$",  # directory traversal
        r'[<>"|?*]',  # invalid filename chars
        r"COM[1-9]|LPT[1-9]",  # reserved device names (anywhere in path)
    ]

    # Reserved Windows device names — checked per path component.
    _RESERVED_NAMES = frozenset(
        {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    )

    # Maximum allowed path length, platform-dependent.
    # Windows MAX_PATH is 260; Linux/macOS PATH_MAX is 4096.
    MAX_PATH_LENGTH = 260 if os.name == "nt" else 4096
    MAX_INPUT_LENGTH = 100

    @classmethod
    def validate_file_path(cls, file_path: str) -> bool:
        """
        Validate a file path for security vulnerabilities.

        Args:
            file_path: File path to validate.

        Returns:
            True if the path is safe, False otherwise.
        """
        if not file_path or not isinstance(file_path, str):
            return False

        # Reject dangerous patterns.
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return False

        # Reject reserved Windows device names in any path component.
        for part in Path(file_path).parts:
            if part.upper().rstrip(".") in cls._RESERVED_NAMES:
                return False

        # Reject characters outside the safe set.
        if not cls.SAFE_PATH_PATTERN.match(file_path):
            return False

        try:
            path = Path(file_path)
            if not path.is_absolute():
                return False

            if len(str(path)) > cls.MAX_PATH_LENGTH:
                return False

            # Additional Windows-specific reserved-name checks.
            if os.name == "nt":
                for part in path.parts:
                    for pattern in cls.DANGEROUS_PATTERNS:
                        if re.fullmatch(pattern, part, re.IGNORECASE):
                            return False

        except (OSError, ValueError):
            return False

        return True

    @classmethod
    def sanitize_input(cls, input_str: str, max_length: Optional[int] = None) -> str:
        """
        Sanitise user input by removing dangerous characters.

        Args:
            input_str:  Input string to sanitise.
            max_length: Maximum allowed length (defaults to MAX_INPUT_LENGTH).

        Returns:
            Sanitised string.
        """
        if not input_str or not isinstance(input_str, str):
            return ""

        if max_length is None:
            max_length = cls.MAX_INPUT_LENGTH

        # Remove dangerous characters (keep single quotes — valid in filenames).
        sanitised = re.sub(r'[<>"&]', "", input_str)
        # Remove control characters.
        sanitised = re.sub(r"[\x00-\x1f\x7f]", "", sanitised)
        # Enforce maximum length, then strip whitespace.
        return sanitised[:max_length].strip()

    @classmethod
    def validate_tag_value(cls, value: str, max_length: int = 4096) -> bool:
        """
        Validate a freeform audio tag value.

        Allows every Unicode code point except the C0 control range (other
        than tab, newline and carriage return) and DEL, plus values up to
        *max_length* code points. C1 control code points (U+0080–U+009F) are
        permitted, since tag metadata routinely carries non-Latin scripts.

        Rejects disallowed characters and over-length values without
        altering the caller's string.

        Args:
            value: Tag value to validate.
            max_length: Maximum number of Unicode code points.

        Returns:
            True if the value is safe to store in an audio tag.
        """
        if not isinstance(value, str) or len(value) > max_length:
            return False
        return not any(
            (ord(char) < 32 and char not in "\t\n\r") or ord(char) == 127
            for char in value
        )

    @classmethod
    def validate_directory_path(cls, dir_path: str) -> bool:
        """
        Validate a directory path for security vulnerabilities.

        In addition to the checks in validate_file_path, this method detects
        a path that traverses a symlink (or Windows junction) and whose real
        target lies outside the user's home directory and the system temp
        directory.  Such paths are permitted with a logged warning rather than
        hard-blocked, because legitimate audio libraries on secondary drives
        (e.g. D:\\Music) would otherwise be rejected.

        A symlink is detected by comparing the *filesystem-resolved* path
        against the *lexically normalised* absolute path.  ``resolve()``
        follows links and normalises the on-disk casing; ``abspath`` +
        ``normpath`` only collapses ``.``/``..`` textually.  A difference
        between the two therefore means at least one component was a link.
        Both sides go through ``os.path.normcase`` so a plain directory whose
        declared casing differs from the on-disk casing is not misreported as
        a symlink on Windows.

        Args:
            dir_path: Directory path to validate.

        Returns:
            True if the path is considered safe, False otherwise.
        """
        if not cls.validate_file_path(dir_path):
            return False

        try:
            declared = Path(dir_path)
            resolved = declared.resolve()

            # If the resolved path does not exist yet that is fine —
            # the caller may be about to create it.
            if not resolved.exists():
                return True

            # Detect symlinks that redirect outside expected locations.
            if cls._traverses_symlink(declared, resolved):
                # The path involved at least one symlink.
                safe_roots = (
                    Path.home(),
                    Path(tempfile.gettempdir()),
                )
                in_safe_root = any(
                    resolved == r or resolved.is_relative_to(r) for r in safe_roots
                )
                if not in_safe_root:
                    logger.warning(
                        "Directory symlink resolves outside safe roots: %s -> %s",
                        dir_path,
                        resolved,
                    )
                    # Warn but allow — secondary drives are legitimate.

        except (OSError, ValueError):
            return False

        return True

    @staticmethod
    def _traverses_symlink(declared: Path, resolved: Path) -> bool:
        """
        Report whether *declared* reaches *resolved* via a symlink.

        Args:
            declared: The path exactly as the caller supplied it.
            resolved: The same path after ``Path.resolve()``.

        Returns:
            True if resolving the path changed it, which can only happen when
            a symlink or junction was traversed. The comparison is
            case-insensitive on platforms where casing is not significant, so
            a real directory declared with different casing is not flagged.
        """
        lexical = Path(os.path.normpath(os.path.abspath(declared)))
        return os.path.normcase(str(lexical)) != os.path.normcase(str(resolved))

    @classmethod
    def validate_filename(cls, filename: str) -> bool:
        """
        Validate an individual filename (not a full path).

        Args:
            filename: Filename to validate.

        Returns:
            True if the filename is safe, False otherwise.
        """
        if not filename or not isinstance(filename, str):
            return False

        for pattern in cls.DANGEROUS_PATTERNS:
            if re.search(pattern, filename, re.IGNORECASE):
                return False

        safe_filename_pattern = re.compile(r"^[a-zA-Z0-9_\-\. ]+$")
        if not safe_filename_pattern.match(filename):
            return False

        if len(filename) > 255:
            return False

        name_without_ext = os.path.splitext(filename)[0]
        for pattern in cls.DANGEROUS_PATTERNS:
            if re.fullmatch(pattern, name_without_ext, re.IGNORECASE):
                return False

        # Check reserved Windows device names
        if name_without_ext.upper().rstrip(".") in cls._RESERVED_NAMES:
            return False

        return True

    @classmethod
    def sanitize_api_input(cls, input_str: str) -> str:
        """
        Sanitise input specifically for API calls.

        Args:
            input_str: Raw API input string.

        Returns:
            Sanitised string safe for inclusion in an API request.
        """
        if not input_str or not isinstance(input_str, str):
            return ""

        sanitised = re.sub(r'[<>"\'&;]', "", input_str)
        sanitised = re.sub(r"[\x00-\x1f\x7f]", "", sanitised)
        return sanitised[:200].strip()

    @classmethod
    def validate_audio_file_path(cls, file_path: str) -> bool:
        """
        Validate an audio file path specifically.

        Checks that the path passes general security validation, carries an
        extension from ``InputValidator.AUDIO_EXTENSIONS`` (derived from the
        suite's declared ``SUPPORTED_EXTENSIONS``), and refers to an existing
        regular file.

        Args:
            file_path: Audio file path to validate.

        Returns:
            True if the path is safe and points to an audio file.
        """
        if not cls.validate_file_path(file_path):
            return False

        try:
            path = Path(file_path)
            if path.suffix.lower() not in cls.AUDIO_EXTENSIONS:
                return False

            return path.exists() and path.is_file()

        except (OSError, ValueError):
            return False
