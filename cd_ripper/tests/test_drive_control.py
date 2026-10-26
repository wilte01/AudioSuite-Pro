"""Tests for cd_ripper.core.drive_control — tray eject and file reveal.

Both helpers exist so the results tab contains no subprocess call of its own
(audit R-08, plan C3). The platform branches are driven by patching
``sys.platform`` and never ``os.name``: patching ``os.name`` makes ``pathlib``
build a ``PosixPath`` on a Windows host, which measures a machine that exists
nowhere. The MCI call is a fake ``ctypes.windll`` because a test must never
open a real tray.

Changed in 2.1.4: new suite for the module added by plan C3.
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    validate_executable,
)
from cd_ripper.core import drive_control


@pytest.fixture()
def mci(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Run as Windows with a recording stand-in for ``mciSendStringW``.

    Returns:
        The mock that ``eject_drive`` calls, already succeeding (code 0).
    """
    windll = MagicMock()
    windll.winmm.mciSendStringW.return_value = 0
    monkeypatch.setattr(ctypes, "windll", windll, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    return windll.winmm.mciSendStringW


class TestEjectWindows:
    """The tray opens through MCI: a fixed command, no process, no shell."""

    def test_command_is_the_validated_letter(self, mci: MagicMock) -> None:
        drive_control.eject_drive("D:")
        mci.assert_called_once_with("set D: door open", None, 0, None)

    @pytest.mark.parametrize("drive", ["D", "D:", "D:\\", " d: "])
    def test_every_designator_form_produces_the_same_command(
        self, mci: MagicMock, drive: str
    ) -> None:
        drive_control.eject_drive(drive)
        assert mci.call_args.args[0] == "set D: door open"

    def test_no_external_program_runs(self, mci: MagicMock) -> None:
        """The old path spawned PowerShell; this one spawns nothing."""
        with patch.object(drive_control, "run_secure_subprocess") as secure:
            drive_control.eject_drive("D:")
        secure.assert_not_called()

    @pytest.mark.parametrize(
        "drive", ["", "DD", "D:extra", "\\\\server\\share", "; rm -rf /"]
    )
    def test_a_non_designator_is_refused_before_anything_runs(
        self, mci: MagicMock, drive: str
    ) -> None:
        with pytest.raises(AudioSuiteError, match="Not a drive designator"):
            drive_control.eject_drive(drive)
        mci.assert_not_called()

    def test_a_refused_request_is_reported_with_its_code(self, mci: MagicMock) -> None:
        mci.return_value = 266  # MCIERR_CANNOT_LOAD_DRIVER
        with pytest.raises(AudioSuiteError, match="MCI error 266"):
            drive_control.eject_drive("D:")


class TestEjectPosix:
    def test_device_is_ejected_through_the_wrapper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        with patch.object(drive_control, "run_secure_subprocess") as secure:
            drive_control.eject_drive("/dev/sr0")
        secure.assert_called_once_with(
            "eject", ["/dev/sr0"], capture_output=True, check=False
        )

    @pytest.mark.parametrize("drive", ["sr0", "/etc/passwd", "/dev/../etc", ""])
    def test_a_non_device_path_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, drive: str
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        with patch.object(drive_control, "run_secure_subprocess") as secure:
            with pytest.raises(AudioSuiteError, match="Not a CD device path"):
                drive_control.eject_drive(drive)
        secure.assert_not_called()


class TestReveal:
    def test_windows_selects_the_file_in_explorer(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "win32")
        target = "C:\\music\\track 01.flac"
        with patch.object(drive_control, "run_secure_subprocess") as secure:
            drive_control.reveal_in_file_manager(target)
        secure.assert_called_once_with(
            "explorer.exe", [f"/select,{target}"], capture_output=True, check=False
        )
        # One argument in a list, not a command string: explorer's switch wants
        # the path attached to /select, and a string would invite a shell.
        args = secure.call_args.args[1]
        assert isinstance(args, list)
        assert len(args) == 1
        assert "shell" not in secure.call_args.kwargs

    def test_posix_opens_the_containing_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        with patch.object(drive_control, "run_secure_subprocess") as secure:
            drive_control.reveal_in_file_manager("/music/album/track.flac")
        secure.assert_called_once_with(
            "xdg-open", ["/music/album"], capture_output=True, check=False
        )
        assert "shell" not in secure.call_args.kwargs


class TestAllowlist:
    """The two new executables are allowed; a shell is still not."""

    @pytest.mark.parametrize("exe", ["explorer", "explorer.exe", "eject"])
    def test_drive_control_executables_are_allowed(self, exe: str) -> None:
        assert validate_executable(exe) is True

    @pytest.mark.parametrize("exe", ["powershell", "powershell.exe", "pwsh", "cmd.exe"])
    def test_shells_stay_out_of_the_allowlist(self, exe: str) -> None:
        with pytest.raises(SubprocessSecurityError, match="not allowed"):
            validate_executable(exe)


def test_module_is_display_free() -> None:
    """No Tk import: these argv must be assertable without a display."""
    text = Path(drive_control.__file__ or "").read_text(encoding="utf-8")
    assert "tkinter" not in text
    assert "messagebox" not in text
