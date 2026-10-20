"""Tests for audio_suite_shared.runtime_check.

Changed in 1.4.0: locks the stale-install warning and the missing-module
guidance that points at ``uv run audiosuite``.
Changed in 1.4.1: locks the same-version origin scan and the once-per-process
gate that keeps a repeated command from repeating the warning (PLAN D94).
"""

from __future__ import annotations

import importlib.metadata as metadata

import pytest

from audio_suite_shared import runtime_check
from audio_suite_shared.install_map import PackageStatus


@pytest.fixture(autouse=True)
def _reset_warning_gate():
    """The warning is process-wide, so each test starts with it unseen."""
    runtime_check.reset_warning_state()
    yield
    runtime_check.reset_warning_state()


class TestInstalledVersion:
    def test_returns_the_distribution_version(self, monkeypatch) -> None:
        monkeypatch.setattr(runtime_check.metadata, "version", lambda _name: "1.4.0")
        assert runtime_check.installed_version() == "1.4.0"

    def test_returns_none_when_not_installed(self, monkeypatch) -> None:
        def _missing(_name: str) -> str:
            raise metadata.PackageNotFoundError(_name)

        monkeypatch.setattr(runtime_check.metadata, "version", _missing)
        assert runtime_check.installed_version() is None


class TestCheckoutVersion:
    def test_returns_the_declared_version(self, monkeypatch) -> None:
        monkeypatch.setattr(runtime_check, "declared_version", lambda: "1.4.0")
        assert runtime_check.checkout_version() == "1.4.0"

    @pytest.mark.parametrize("error", [RuntimeError("no version"), ValueError("bad")])
    def test_returns_none_when_the_manifest_is_unreadable(
        self, monkeypatch, error: Exception
    ) -> None:
        def _boom() -> str:
            raise error

        monkeypatch.setattr(runtime_check, "declared_version", _boom)
        assert runtime_check.checkout_version() is None


class TestStaleInstallWarning:
    def test_matching_versions_of_a_mapped_checkout_warn_about_nothing(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: "1.4.0")
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: "1.4.0")
        monkeypatch.setattr(runtime_check, "packages_outside_checkout", lambda: [])
        assert runtime_check.stale_install_warning() is None

    @pytest.mark.parametrize(
        "installed,checkout",
        [(None, "1.4.0"), ("1.4.0", None), (None, None)],
    )
    def test_unknown_versions_warn_about_nothing(
        self, monkeypatch, installed: str | None, checkout: str | None
    ) -> None:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: installed)
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: checkout)
        assert runtime_check.stale_install_warning() is None

    def test_mismatch_names_both_versions_and_the_locked_runtime(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: "1.0.0")
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: "1.4.0")
        warning = runtime_check.stale_install_warning()
        assert warning is not None
        assert "1.0.0" in warning
        assert "1.4.0" in warning
        assert runtime_check.LOCKED_RUNTIME in warning
        assert runtime_check.SYNC_COMMAND in warning

    def test_the_version_gap_skips_the_origin_scan(self, monkeypatch) -> None:
        """The cheap comparison answers the common failure on its own."""
        monkeypatch.setattr(runtime_check, "installed_version", lambda: "1.0.0")
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: "1.4.0")
        scans: list[int] = []
        monkeypatch.setattr(
            runtime_check,
            "packages_outside_checkout",
            lambda: scans.append(1) or [],
        )

        assert runtime_check.stale_install_warning() is not None
        assert scans == []

    def test_the_warning_is_emitted_once_per_process(self, monkeypatch) -> None:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: "1.0.0")
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: "1.4.0")

        assert runtime_check.stale_install_warning() is not None
        assert runtime_check.stale_install_warning() is None

        runtime_check.reset_warning_state()
        assert runtime_check.stale_install_warning() is not None


class TestSameVersionOriginScan:
    """A matching version can still be an install built from another tree."""

    @staticmethod
    def _matching(monkeypatch, names: list[str]) -> None:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: "1.4.1")
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: "1.4.1")
        monkeypatch.setattr(
            runtime_check,
            "packages_outside_checkout",
            lambda: [
                PackageStatus(
                    name=name, state="elsewhere", location=f"C:/python/{name}"
                )
                for name in names
            ],
        )

    def test_a_matching_version_is_stale_when_a_package_resolves_elsewhere(
        self, monkeypatch
    ) -> None:
        self._matching(monkeypatch, ["audio_fingerprinter"])

        warning = runtime_check.stale_install_warning()

        assert warning is not None
        assert "audio_fingerprinter" in warning
        assert "resolve outside" in warning
        assert "audiosuite doctor" in warning
        assert runtime_check.LOCKED_RUNTIME in warning
        assert runtime_check.SYNC_COMMAND in warning

    def test_a_matching_mapped_checkout_stays_silent(self, monkeypatch) -> None:
        self._matching(monkeypatch, [])
        assert runtime_check.stale_install_warning() is None

    def test_many_foreign_packages_are_summarised(self, monkeypatch) -> None:
        """A non-editable install maps every package; the warning stays short."""
        self._matching(monkeypatch, [f"pkg_{index}" for index in range(9)])

        warning = runtime_check.stale_install_warning()

        assert warning is not None
        for named in ("pkg_0", "pkg_5"):
            assert named in warning
        assert "and 3 more" in warning
        assert "pkg_8" not in warning


class TestMissingModulesMessage:
    def _message(
        self,
        monkeypatch,
        missing: list[str],
        installed: str | None,
        checkout: str | None,
    ) -> str:
        monkeypatch.setattr(runtime_check, "installed_version", lambda: installed)
        monkeypatch.setattr(runtime_check, "checkout_version", lambda: checkout)
        return runtime_check.missing_modules_message(missing)

    def test_names_every_missing_module_and_the_fix(self, monkeypatch) -> None:
        message = self._message(
            monkeypatch, ["audio_fingerprinter", "spectral_viewer"], "1.0.0", "1.4.0"
        )
        assert "audio_fingerprinter" in message
        assert "spectral_viewer" in message
        assert "audiosuite doctor" in message
        assert runtime_check.LOCKED_RUNTIME in message
        assert runtime_check.SYNC_COMMAND in message

    def test_stale_install_explains_the_version_gap(self, monkeypatch) -> None:
        message = self._message(monkeypatch, ["audio_fingerprinter"], "1.0.0", "1.4.0")
        assert "1.0.0" in message
        assert "1.4.0" in message
        assert "predates" in message

    def test_matching_versions_do_not_invent_a_gap(self, monkeypatch) -> None:
        message = self._message(monkeypatch, ["audio_fingerprinter"], "1.4.0", "1.4.0")
        assert "predates" not in message
        assert runtime_check.LOCKED_RUNTIME in message

    def test_duplicate_names_are_listed_once(self, monkeypatch) -> None:
        message = self._message(
            monkeypatch, ["bpm_analyzer", "bpm_analyzer"], "1.4.0", "1.4.0"
        )
        assert message.count("bpm_analyzer") == 1
