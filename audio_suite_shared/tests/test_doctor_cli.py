"""Tests for audio_suite_shared.doctor_cli.

Changed in 1.4.0: locks the package-mapping report, the tool-impact list, and
the non-zero exit that makes ``audiosuite doctor`` usable as a pre-flight gate.
Changed in 1.4.1: locks the ``--json`` payload, including the core-count
mapping that keeps ``succeeded`` at 0 on a broken install (PLAN D93).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from audio_suite_shared import (
    cli_app,  # noqa: F401  (registers the commands)
    doctor_cli,
)
from audio_suite_shared.cli_base import cli
from audio_suite_shared.cli_schema import validate_payload
from audio_suite_shared.doctor_cli import (
    DoctorReport,
    PackageStatus,
    checkout_packages,
    collect_report,
    doctor_payload,
    render_report,
)


def _broken_report() -> DoctorReport:
    """Return a report with one healthy package and every failure kind.

    It has a missing package, a version that matches (so the failure is the
    mapping, not staleness) and a command that failed to register, which is the
    shape a partially broken install actually produces.
    """
    return DoctorReport(
        checkout_root=Path("C:/AudioSuite-Pro"),
        declared="1.4.0",
        installed="1.4.0",
        editable=True,
        packages=(
            PackageStatus(
                name="bpm_analyzer",
                state="ok",
                location="C:/AudioSuite-Pro/bpm_analyzer/__init__.py",
                commands=("bpm",),
            ),
            PackageStatus(
                name="spectral_viewer", state="missing", commands=("spectrogram",)
            ),
        ),
        unregistered=(("Audio Fingerprinter", "fingerprint"),),
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


class TestDoctorPayload:
    """The ``--json`` document reports the same findings as the text report."""

    def test_the_payload_is_schema_valid(self) -> None:
        payload = doctor_payload(_broken_report(), duration_secs=0.008)

        assert validate_payload("doctor", payload) == []
        assert payload["tool"] == payload["command"] == "doctor"
        assert payload["dry_run"] is False

    def test_packages_are_the_cores_items_not_the_report_lines(self) -> None:
        """``total`` is the package count, so ``processed`` means the same."""
        payload = doctor_payload(_broken_report(), duration_secs=1.0)

        assert payload["total"] == payload["processed"] == 2
        assert payload["skipped"] == 0
        assert payload["errors"] == 1
        assert payload["succeeded"] == 1
        assert payload["mapped"] == 1

    def test_the_diagnosis_is_carried_by_declared_extras(self) -> None:
        payload = doctor_payload(_broken_report(), duration_secs=0.0)

        assert payload["healthy"] is False
        assert payload["checkout_version"] == "1.4.0"
        assert payload["installed_version"] == "1.4.0"
        assert payload["editable"] is True
        assert payload["problems"] == []
        assert payload["packages"] == [
            {
                "name": "bpm_analyzer",
                "status": "ok",
                "origin": "C:/AudioSuite-Pro/bpm_analyzer/__init__.py",
                "commands": ["bpm"],
            },
            {
                "name": "spectral_viewer",
                "status": "missing",
                "origin": None,
                "commands": ["spectrogram"],
            },
        ]
        assert payload["missing_commands"] == [
            {"tool": "Audio Fingerprinter", "command": "fingerprint"}
        ]

    def test_a_structural_problem_counts_once_and_never_goes_negative(self) -> None:
        report = DoctorReport(
            checkout_root=None,
            declared="1.4.0",
            installed=None,
            editable=False,
            packages=(),
            problems=("no pyproject.toml found, so this is not a source checkout",),
        )

        payload = doctor_payload(report, duration_secs=0.0)

        assert validate_payload("doctor", payload) == []
        assert payload["total"] == payload["processed"] == 0
        assert payload["errors"] == 1
        assert payload["succeeded"] == 0
        assert payload["problems"] == [report.problems[0]]
        assert payload["mapped"] == 0


class TestDoctorJsonCommand:
    """``doctor --json`` publishes one document and keeps its exit status."""

    def test_a_healthy_install_exits_zero(self) -> None:
        if doctor_cli.installed_version() is None:
            pytest.skip("audiosuite-pro is not installed in this interpreter")

        result = CliRunner().invoke(cli, ["doctor", "--json"])

        assert result.exit_code == 0, result.stderr
        payload = json.loads(result.stdout)
        assert validate_payload("doctor", payload) == []
        assert payload["healthy"] is True
        assert payload["total"] > 0, "the package scan found nothing"
        assert payload["mapped"] == payload["total"]
        assert payload["errors"] == 0

    def test_a_broken_install_exits_one_with_exactly_one_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(doctor_cli, "collect_report", _broken_report)

        result = CliRunner().invoke(cli, ["doctor", "--json"])

        assert result.exit_code == 1
        # A second document would break every consumer that parses stdout; the
        # ``SystemExit`` must not be intercepted into an error payload as well.
        assert result.stdout.count('"schema_version"') == 1
        payload = json.loads(result.stdout)
        assert validate_payload("doctor", payload) == []
        assert payload["healthy"] is False
        assert payload["errors"] == 1
        assert payload["missing_commands"] == [
            {"tool": "Audio Fingerprinter", "command": "fingerprint"}
        ]

    def test_a_version_gap_fails_the_verdict_not_the_package_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale install is unhealthy with zero findings, so the verdict
        cannot be inferred from the counters alone."""
        monkeypatch.setattr(doctor_cli, "installed_version", lambda: "1.0.0")

        result = CliRunner().invoke(cli, ["doctor", "--json"])

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert validate_payload("doctor", payload) == []
        assert payload["installed_version"] == "1.0.0"
        assert payload["errors"] == 0
        assert payload["succeeded"] == payload["total"]
        assert payload["healthy"] is False

    def test_the_human_report_moves_to_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(doctor_cli, "collect_report", _broken_report)

        result = CliRunner().invoke(cli, ["doctor", "--json"])

        assert "AudioSuite-Pro doctor" in result.stderr
        assert "[MISSING] spectral_viewer" in result.stderr
        assert "AudioSuite-Pro doctor" not in result.stdout

    def test_text_mode_prints_the_report_and_no_document(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(doctor_cli, "collect_report", _broken_report)

        result = CliRunner().invoke(cli, ["doctor"])

        assert result.exit_code == 1
        assert "[MISSING] spectral_viewer" in result.stdout
        assert '"schema_version"' not in result.stdout

    def test_json_then_text_is_text_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The last of the shared pair wins, exactly as Click parses it."""
        monkeypatch.setattr(doctor_cli, "collect_report", _broken_report)

        result = CliRunner().invoke(cli, ["doctor", "--json", "--text"])

        assert result.exit_code == 1
        assert '"schema_version"' not in result.stdout
