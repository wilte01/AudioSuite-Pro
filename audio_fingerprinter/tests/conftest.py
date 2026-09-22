"""
Shared test fixtures for audio_fingerprinter/tests.

tk_root itself lives in the repo-root conftest.py (P5 consolidation); this
file only carries the package's private fixtures.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Generator
from pathlib import Path
from queue import Queue
from tkinter import StringVar
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Yield a temporary directory, cleaned up after the test."""
    d = Path(tempfile.mkdtemp(prefix="fp_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fake_audio_dir(temp_dir: Path) -> Path:
    """Yield a directory containing a dummy MP3 file (zero bytes)."""
    (temp_dir / "track1.mp3").write_bytes(b"\x00" * 100)
    (temp_dir / "track2.flac").write_bytes(b"\x00" * 100)
    return temp_dir


@pytest.fixture
def fake_fpcalc(temp_dir: Path) -> Path:
    """Create a fake fpcalc executable on disk so resolve_fpcalc can find it."""
    exe = temp_dir / "fpcalc.exe"
    exe.write_bytes(b"\x00")
    return exe


@pytest.fixture
def fake_fpcalc_path(temp_dir: Path) -> str:
    """Return the string path of a fake fpcalc.exe on disk."""
    exe = temp_dir / "fpcalc.exe"
    exe.write_bytes(b"\x00")
    return str(exe)


@pytest.fixture
def mock_slot_vars() -> list[MagicMock]:
    """Return 3 mock thread-safe slot variables."""
    return [MagicMock(spec=StringVar) for _ in range(3)]


@pytest.fixture
def mock_slot_queue() -> Queue[int]:
    """Return a slot queue pre-filled with indices 0-2."""
    q: Queue[int] = Queue()
    for i in range(3):
        q.put(i)
    return q


@pytest.fixture
def mock_callbacks() -> dict[str, MagicMock]:
    """Return standard mock callbacks: on_progress, on_complete, on_error."""
    return {
        "on_progress": MagicMock(),
        "on_complete": MagicMock(),
        "on_error": MagicMock(),
    }


@pytest.fixture
def patched_generate_fingerprint():
    """Patch generate_fingerprint to return a deterministic Fingerprint."""
    fake = MagicMock()
    fake.duration = 60.0
    fake.fingerprint = (
        "AQADtImSRImSNIkSNY0SN4mTREmTRImSRImSRImSRImSRImSRImSRImSRImSRImSRIkSJ0mTJEmS"
    )
    with patch(
        "audio_fingerprinter.core.file_processor.generate_fingerprint",
        return_value=fake,
    ) as m:
        yield m


@pytest.fixture
def patched_resolve_fpcalc(tmp_path: Path):
    """Patch resolve_fpcalc to return a fake path without checking disk."""
    fake_path = str(tmp_path / "fpcalc.exe")
    with patch(
        "audio_fingerprinter.core.file_processor.resolve_fpcalc",
        return_value=fake_path,
    ) as m:
        yield m


@pytest.fixture
def patched_key_manager():
    """Patch api_key_store.load_api_key and get_key_manager."""
    with (
        patch(
            "audio_fingerprinter.utils.api_key.load_api_key",
            return_value="test_api_key_12345",
        ),
        patch(
            "audio_fingerprinter.utils.api_key.save_api_key",
        ),
        patch(
            "audio_fingerprinter.utils.api_key.get_key_manager",
        ),
    ):
        yield
