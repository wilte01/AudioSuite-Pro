"""Tests for audio_suite_shared.doctor_cli.

Changed in 1.4.0: locks the package-mapping report, the tool-impact list, and
the non-zero exit that makes ``audiosuite doctor`` usable as a pre-flight gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from audio_suite_shared import (
    cli_app,  # noqa: F401  (registers the commands)
    doctor_cli,
)
from audio_suite_shared.cli_base import cli
from audio_suite_shared.doctor_cli import (
    DoctorReport,
    PackageStatus,
    checkout_packages,
    collect_report,
    render_report,
)


class TestCheckoutPackages:
    def test_finds_packages_and_skips_non_packages(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "__init__.py").write_text("", encoding="utf-8")
        (tmp_path / "utilities").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")

        assert checkout_packages(tmp_path) == ["alpha", "beta"]

    def test_the_real_checkout_scan_is_non_empty(self) -> None:
        """A scan that resolves nothing would pass vacuously."""
        pyproject = doctor_cli.find_pyproject()
        assert pyproject is not None
        names = checkout_packages(pyproject.parent)
        assert names, "the checkout scan found no first-party packages"
        assert "audio_suite_shared" in names


class TestResolvePackage:
    def test_a_finder_that_raises_is_reported_as_missing(self, monkeypatch) -> None:
        def _boom(_name: str):
            raise ModuleNotFoundError(
                "No module named 'spectral_viewer'", name="spectral_viewer"
            )

        monkeypatch.setattr(doctor_cli.importlib.util, "find_spec", _boom)
        status = doctor_cli._resolve_package("spectral_viewer", Path.cwd())
        assert status.state == "missing"

    def test_an_installed_copy_outside_the_checkout_is_flagged(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        root = tmp_path / "checkout"
        elsewhere = tmp_path / "site-packages" / "bpm_analyzer"
        elsewhere.mkdir(parents=True)
        (elsewhere / "__init__.py").write_text("", encoding="utf-8")

        fake_spec = type("Spec", (), {"origin": str(elsewhere / "__init__.py")})()
        monkeypatch.setattr(
            doctor_cli.importlib.util, "find_spec", lambda _name: fake_spec
        )

        status = doctor_cli._resolve_package("bpm_analyzer", root)
        assert status.state == "elsewhere"
        assert status.location is not None
        assert "site-packages" in status.location


class TestCollectReport:
    def test_the_live_install_is_healthy(self) -> None:
        if doctor_cli.installed_version() is None:
            pytest.skip("audiosuite-pro is not installed in this interpreter")
        report = collect_report()
        assert report.checkout_root is not None
        assert report.packages, "the report contains no packages"
        assert report.installed is not None
        assert report.broken_packages == []
        assert report.healthy is True

    def test_a_missing_package_is_named_with_the_command_it_breaks(self) -> None:
        def resolve(name: str, root: Path) -> PackageStatus:
            if name == "spectral_viewer":
                return PackageStatus(name=name, state="missing")
            return PackageStatus(
                name=name, state="ok", location=str(root / name / "__init__.py")
            )

        report = collect_report(resolve=resolve)

        assert report.healthy is False
        assert [status.name for status in report.broken_packages] == ["spectral_viewer"]
        text = render_report(report)
        assert "[MISSING] spectral_viewer" in text
        assert "`audiosuite spectrogram`" in text

    def test_a_package_from_another_install_is_reported(self) -> None:
        def resolve(name: str, root: Path) -> PackageStatus:
            if name == "bpm_analyzer":
                return PackageStatus(
                    name=name,
                    state="elsewhere",
                    location=str(root.parent / "site-packages" / name),
                )
            return PackageStatus(name=name, state="ok")

        text = render_report(collect_report(resolve=resolve))

        assert "[ELSEWHERE] bpm_analyzer" in text
        assert "resolves outside the checkout" in text
        assert "`audiosuite bpm`" in text

    def test_a_shared_package_failure_does_not_claim_a_command(self) -> None:
        def resolve(name: str, root: Path) -> PackageStatus:
            if name == "master_driver":
                return PackageStatus(name=name, state="missing")
            return PackageStatus(name=name, state="ok")

        text = render_report(collect_report(resolve=resolve))

        assert "master_driver" in text
        assert "GUI or shared code only" in text

    def test_no_checkout_is_a_structural_problem(self, monkeypatch) -> None:
        monkeypatch.setattr(doctor_cli, "find_pyproject", lambda: None)
        report = collect_report()
        assert report.checkout_root is None
        assert report.healthy is False
        assert "not a source checkout" in render_report(report)

    def test_an_empty_scan_fails_loudly(self, monkeypatch, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[project]\nversion = '1.4.0'\n", encoding="utf-8")
        monkeypatch.setattr(doctor_cli, "find_pyproject", lambda: pyproject)
        monkeypatch.setattr(doctor_cli, "checkout_packages", lambda _root: [])
        report = collect_report()
        assert report.healthy is False
        assert "scan is broken" in render_report(report)

    def test_a_command_that_failed_to_register_is_listed(self, monkeypatch) -> None:
        monkeypatch.setattr(
            doctor_cli,
            "_unregistered_commands",
            lambda: (("Audio Fingerprinter", "fingerprint"),),
        )
        report = collect_report()

        assert report.healthy is False
        text = render_report(report)
        assert "`audiosuite fingerprint`" in text
        assert "did not register" in text

    def test_a_version_gap_fails_even_when_every_package_maps(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(doctor_cli, "installed_version", lambda: "1.0.0")
        report = collect_report()
        assert report.broken_packages == []
        assert report.healthy is False
        text = render_report(report)
        assert "STALE" in text
        assert "uv sync --frozen --all-extras" in text


class TestDoctorCommand:
    def test_healthy_install_exits_zero(self) -> None:
        result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 0, result.output
        assert "AudioSuite-Pro doctor" in result.output
        assert "Tools a stale install would break: none" in result.output

    def test_a_broken_report_exits_one_and_shows_the_fix(self, monkeypatch) -> None:
        report = DoctorReport(
            checkout_root=Path("C:/AudioSuite-Pro"),
            declared="1.4.0",
            installed="1.4.0",
            editable=True,
            packages=(
                PackageStatus(
                    name="spectral_viewer",
                    state="missing",
                    commands=("spectrogram",),
                ),
            ),
        )
        monkeypatch.setattr(doctor_cli, "collect_report", lambda: report)
        result = CliRunner().invoke(cli, ["doctor"])
        assert result.exit_code == 1
        assert "spectral_viewer" in result.output
        assert "uv sync --frozen --all-extras" in result.output

    def test_command_help_is_documented(self) -> None:
        result = CliRunner().invoke(cli, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "maps every package" in result.output

    def test_the_tool_impact_section_is_always_present(self) -> None:
        packages = tuple(
            PackageStatus(name=name, state="ok") for name in ("alpha", "beta")
        )
        report = DoctorReport(
            checkout_root=Path("C:/AudioSuite-Pro"),
            declared="1.4.0",
            installed="1.4.0",
            editable=True,
            packages=packages,
        )
        assert "Tools a stale install would break" in render_report(report)
