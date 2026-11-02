"""Tests for the one Trash seam.

The rules under test are the safety rules: the backend is used with an absolute
path, a missing backend refuses instead of deleting, and a backend failure is
reported rather than swallowed.

Changed in 2.4.0: new module (PLAN_duplicate_disposition_2026-11-02.md DD-2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from audio_suite_shared.optional_deps import InstallOutcome
from duplicate_finder.core import trash


class TestAvailability:
    """A missing backend is a refusal, never a fallback."""

    def test_the_declared_package_is_available(self) -> None:
        assert trash.available() is True

    def test_a_missing_backend_is_not_available(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(trash, "_send2trash", None)
        monkeypatch.setattr(trash, "SEND2TRASH_AVAILABLE", False)

        assert trash.available() is False

    def test_a_missing_backend_refuses_and_leaves_the_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(trash, "_send2trash", None)
        target = tmp_path / "song.mp3"
        target.write_bytes(b"audio")

        with pytest.raises(trash.TrashUnavailableError, match="send2trash"):
            trash.move_to_trash(target)

        assert target.read_bytes() == b"audio"


class TestMoveToTrash:
    """The file leaves the library only through the backend."""

    def test_the_backend_receives_the_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        received: list[str] = []
        monkeypatch.setattr(trash, "_send2trash", received.append)
        target = tmp_path / "song.mp3"
        target.write_bytes(b"audio")

        trash.move_to_trash(target)

        assert received == [str(target.resolve())]

    def test_a_backend_failure_is_an_oserror_naming_the_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _fail(_path: str) -> None:
            raise OSError("the Recycle Bin is unavailable")

        monkeypatch.setattr(trash, "_send2trash", _fail)
        target = tmp_path / "song.mp3"
        target.write_bytes(b"audio")

        with pytest.raises(OSError, match="Recycle Bin"):
            trash.move_to_trash(target)

        assert target.exists()


class TestEnsureAvailable:
    """A missing backend is installed into the running interpreter."""

    def test_an_available_backend_installs_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []
        monkeypatch.setattr(
            trash, "ensure", lambda requirement: calls.append(requirement)
        )

        outcome = trash.ensure_available()

        assert outcome.ok is True
        assert calls == []

    def test_a_missing_backend_is_installed_and_reimported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []
        monkeypatch.setattr(trash, "_send2trash", None)
        monkeypatch.setattr(trash, "SEND2TRASH_AVAILABLE", False)

        def _install(requirement: object) -> InstallOutcome:
            calls.append(requirement)
            return InstallOutcome(True, "Recycle Bin support is ready.")

        def _reload() -> None:
            monkeypatch.setattr(trash, "_send2trash", lambda _path: None)
            monkeypatch.setattr(trash, "SEND2TRASH_AVAILABLE", True)

        monkeypatch.setattr(trash, "ensure", _install)

        outcome = trash.ensure_available(reload_backend=_reload)

        assert outcome.ok is True
        assert calls == [trash.SEND2TRASH_REQUIREMENT]
        assert trash.available() is True

    def test_a_failed_install_is_returned_without_claiming_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failure = InstallOutcome(False, "Recycle Bin support could not be installed.")
        monkeypatch.setattr(trash, "_send2trash", None)
        monkeypatch.setattr(trash, "SEND2TRASH_AVAILABLE", False)
        monkeypatch.setattr(trash, "ensure", lambda _requirement: failure)

        assert trash.ensure_available(reload_backend=lambda: None) is failure
