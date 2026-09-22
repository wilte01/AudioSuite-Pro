"""
Pytest fixtures for audio_suite_shared testing.

Provides reusable fixtures for testing BaseFileProcessor and other shared components.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.file_processor_base import BaseFileProcessor


@pytest.fixture
def temp_directory() -> Generator[Path, None, None]:
    """Create a temporary directory for testing.

    Yields:
        Path to temporary directory
    """
    temp_dir = tempfile.mkdtemp(prefix="audio_suite_test_")
    yield Path(temp_dir)
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def sample_audio_files(temp_directory: Path) -> Path:
    """Create sample audio files in temp directory.

    Creates dummy audio files with various extensions for testing.

    Returns:
        Path to directory containing sample files
    """
    # Create sample files with different extensions
    extensions = [".mp3", ".flac", ".ogg", ".m4a", ".wav", ".txt", ".jpg"]
    for i, ext in enumerate(extensions):
        file_path = temp_directory / f"sample_{i}{ext}"
        file_path.write_bytes(b"dummy audio data")

    # Create a subdirectory with more files
    subdir = temp_directory / "subfolder"
    subdir.mkdir()
    for i in range(3):
        file_path = subdir / f"sub_sample_{i}.mp3"
        file_path.write_bytes(b"dummy audio data")

    return temp_directory


@pytest.fixture
def mock_processor() -> Generator[BaseFileProcessor, None, None]:
    """Create a BaseFileProcessor instance with mocked dependencies.

    Yields the processor while patches are still active.
    """
    with (
        patch(
            "audio_suite_shared.file_processor_base.get_resource_manager"
        ) as mock_resource,
        patch("audio_suite_shared.file_processor_base.track_thread"),
        patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
    ):
        mock_resource.return_value = MagicMock()

        processor = BaseFileProcessor(max_workers=2, operation_type="test_operation")
        yield processor


@pytest.fixture
def mock_callbacks() -> dict[str, Callable]:
    """Create mock callback functions for testing.

    Returns:
        Dictionary containing mock progress, complete, and error callbacks
    """
    return {
        "on_progress": MagicMock(),
        "on_complete": MagicMock(),
        "on_error": MagicMock(),
    }


@pytest.fixture
def empty_directory(temp_directory: Path) -> Path:
    """Create an empty directory for testing edge cases.

    Returns:
        Path to empty directory
    """
    return temp_directory


@pytest.fixture
def permission_denied_directory() -> Generator[Path, None, None]:
    """Create a directory with restricted permissions for testing error handling.

    Yields:
        Path to restricted directory
    """
    temp_dir = tempfile.mkdtemp(prefix="audio_suite_restricted_")
    os.chmod(temp_dir, 0o000)  # No permissions
    yield Path(temp_dir)
    os.chmod(temp_dir, 0o755)  # Restore permissions for cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def large_file_directory(temp_directory: Path) -> Path:
    """Create a directory with many files for testing scalability.

    Returns:
        Path to directory with 100+ files
    """
    for i in range(105):
        file_path = temp_directory / f"file_{i:03d}.mp3"
        file_path.write_bytes(b"dummy data")
    return temp_directory


@pytest.fixture
def processor_with_results(mock_processor: BaseFileProcessor) -> BaseFileProcessor:
    """Create a processor configured to track results.

    Returns:
        BaseFileProcessor with result tracking enabled
    """
    mock_processor.results: list[dict] = []
    return mock_processor


@pytest.fixture
def mock_thread_pool() -> Generator[MagicMock, None, None]:
    """Mock ThreadPoolExecutor for controlled testing.

    Yields:
        Mock ThreadPoolExecutor class
    """
    with patch(
        "audio_suite_shared.file_processor_base.ThreadPoolExecutor"
    ) as mock_executor:
        mock_instance = MagicMock()
        mock_executor.return_value = mock_instance
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        yield mock_instance


@pytest.fixture
def sample_file_extensions() -> tuple[str, ...]:
    """Provide standard audio file extensions.

    Returns:
        Tuple of common audio file extensions
    """
    return (".mp3", ".flac", ".ogg", ".m4a", ".opus", ".wav", ".aiff")


@pytest.fixture(scope="session")
def tk_root() -> None:
    """Single session-scoped Tk root — never destroyed to avoid Tcl corruption
    on platforms where creating a second Tk instance after destroying the first
    fails (Windows Python 3.14+)."""
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    return root  # keep alive for entire session


@pytest.fixture
def mock_time() -> Generator[MagicMock, None, None]:
    """Mock time.time() for consistent timing tests.

    Yields:
        Mock time function
    """
    with patch("audio_suite_shared.file_processor_base.time") as mock_t:
        mock_t.time.side_effect = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        mock_t.sleep = MagicMock()
        yield mock_t


@pytest.fixture(scope="session")
def test_suite_root() -> Path:
    """Provide the root path of the test suite.

    Returns:
        Path to audio_suite_shared directory
    """
    return Path(__file__).parent.parent
