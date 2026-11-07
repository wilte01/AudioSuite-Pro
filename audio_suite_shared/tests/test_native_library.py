"""Tests for native_library — one way to load a library the suite ships.

Changed in 2.5.0: new module. The CD Ripper launcher used to locate
``discid.dll`` through the suite-root resolver and hand it to ``ctypes`` itself;
the pair lives here now, and these cases hold the two outcomes the launcher
test could only witness through its own source text: an absent library and one
that cannot load are both reported False, never raised.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import native_library, suite_paths


@pytest.fixture
def library_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the suite root at a temp tree, so no case reads the checkout."""
    monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(tmp_path))
    return tmp_path


class TestLoadShippedLibrary:
    """The four outcomes a caller can see."""

    def test_loads_the_copy_at_the_suite_root(
        self, library_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The installed copy is the one handed to ctypes."""
        library = library_root / "discid.dll"
        library.write_bytes(b"MZ")
        loader = MagicMock(return_value=object())
        monkeypatch.setattr(native_library.ctypes, "CDLL", loader)

        assert native_library.load_shipped_library("discid.dll") is True
        loader.assert_called_once_with(str(library))

    def test_an_absent_library_is_not_an_error(
        self, library_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A machine without the native library still starts the tool."""
        loader = MagicMock()
        monkeypatch.setattr(native_library.ctypes, "CDLL", loader)

        assert native_library.load_shipped_library("discid.dll") is False
        loader.assert_not_called()

    def test_a_library_that_cannot_load_is_witnessed_and_survived(
        self,
        library_root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A wrong-architecture or truncated file is logged, never raised."""
        (library_root / "discid.dll").write_bytes(b"MZ")
        monkeypatch.setattr(
            native_library.ctypes,
            "CDLL",
            MagicMock(side_effect=OSError("bad image")),
        )

        with caplog.at_level(logging.DEBUG):
            assert native_library.load_shipped_library("discid.dll") is False

        assert "could not load" in caplog.text.lower()

    def test_the_working_directory_cannot_choose_the_library(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A checkout renamed and launched from elsewhere still loads its copy."""
        root = tmp_path / "renamed-checkout"
        root.mkdir()
        installed = root / "discid.dll"
        installed.write_bytes(b"MZ")
        elsewhere = tmp_path / "started-from-here"
        elsewhere.mkdir()
        monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(root))
        monkeypatch.chdir(elsewhere)
        loader = MagicMock()
        monkeypatch.setattr(native_library.ctypes, "CDLL", loader)

        assert native_library.load_shipped_library("discid.dll") is True
        loader.assert_called_once_with(str(installed))
