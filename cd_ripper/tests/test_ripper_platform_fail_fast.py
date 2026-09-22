"""
Regression tests: cd_ripper must fail fast with a clear error on
non-Windows platforms instead of crashing on a bare AttributeError deep
inside ctypes.windll.

These were written against a code-read finding (not an execution
failure originally reported by the user), then verified to fail against
the pre-fix code and pass against the fix, per project convention.
"""

import sys

import pytest

from audio_suite_shared.exceptions import AudioExternalToolError
from cd_ripper.core import disc, ripper


def test_open_device_raises_clear_error_on_non_windows(monkeypatch):
    """On a non-Windows platform, _open_device must raise a clear,
    early RuntimeError -- not an AttributeError from ctypes.windll not
    existing."""
    monkeypatch.setattr(sys, "platform", "linux")
    with pytest.raises(AudioExternalToolError, match="only supported on Windows"):
        ripper._open_device("D")


def test_read_toc_raises_clear_error_on_non_windows(monkeypatch):
    """read_toc touches ctypes.windll directly (before ever calling
    _open_device), so it needs its own guard -- this pins that down."""
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(AudioExternalToolError, match="only supported on Windows"):
        ripper.read_toc("D", log_cb=lambda *_: None)


def test_open_device_does_not_touch_ctypes_windll_on_non_windows(monkeypatch):
    """Belt-and-braces: confirm the guard fires *before* any ctypes.windll
    attribute access, by removing ctypes.windll entirely (simulating a
    real non-Windows interpreter, not the test suite's own MagicMock
    stub) and confirming we still get the clean RuntimeError rather than
    an AttributeError."""
    import ctypes

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delattr(ctypes, "windll", raising=False)
    with pytest.raises(AudioExternalToolError, match="only supported on Windows"):
        ripper._open_device("D")


def test_list_cd_drives_returns_empty_on_non_windows(monkeypatch):
    """disc.list_cd_drives must not hand the UI fabricated /dev/cdrom
    paths that extraction can never act on."""
    monkeypatch.setattr(disc.os, "name", "posix")
    assert disc.list_cd_drives() == []


def test_platform_supported_reflects_os(monkeypatch):
    monkeypatch.setattr(disc.os, "name", "posix")
    assert disc.platform_supported() is False
    monkeypatch.setattr(disc.os, "name", "nt")
    assert disc.platform_supported() is True
