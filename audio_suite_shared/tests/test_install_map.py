"""Tests for audio_suite_shared.install_map.

Changed in 1.4.1: added with the module — the resolver that ``audiosuite
doctor`` and the CLI's staleness warning both read (PLAN D94).
"""

from __future__ import annotations

import importlib.metadata as metadata
from pathlib import Path

from audio_suite_shared import install_map
from audio_suite_shared.install_map import (
    checkout_packages,
    editable_install,
    packages_outside_checkout,
    resolve_package,
)


def _fake_spec(origin: str | None) -> object:
    return type("Spec", (), {"origin": origin})()


def _make_package(root: Path, name: str) -> Path:
    (root / name).mkdir(parents=True)
    init = root / name / "__init__.py"
    init.write_text("", encoding="utf-8")
    return init


class TestCheckoutPackages:
    def test_finds_packages_and_skips_non_packages(self, tmp_path: Path) -> None:
        for name in ("alpha", "beta"):
            _make_package(tmp_path, name)
        (tmp_path / "utilities").mkdir()
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "__init__.py").write_text("", encoding="utf-8")

        assert checkout_packages(tmp_path) == ["alpha", "beta"]

    def test_the_real_checkout_scan_is_non_empty(self) -> None:
        """A scan that resolves nothing would pass vacuously."""
        root = install_map.checkout_root()
        assert root is not None
        names = checkout_packages(root)
        assert names, "the checkout scan found no first-party packages"
        assert "audio_suite_shared" in names


class TestResolvePackage:
    def test_a_package_inside_the_checkout_is_ok(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        root = tmp_path / "checkout"
        init = _make_package(root, "bpm_analyzer")
        monkeypatch.setattr(
            install_map.importlib.util, "find_spec", lambda _name: _fake_spec(str(init))
        )

        status = resolve_package("bpm_analyzer", root)

        assert status.state == "ok"
        assert status.location == str(init.resolve())

    def test_a_finder_that_raises_is_reported_as_missing(self, monkeypatch) -> None:
        def _boom(_name: str):
            raise ModuleNotFoundError(
                "No module named 'spectral_viewer'", name="spectral_viewer"
            )

        monkeypatch.setattr(install_map.importlib.util, "find_spec", _boom)
        status = resolve_package("spectral_viewer", Path.cwd())
        assert status.state == "missing"

    def test_no_spec_at_all_is_missing(self, monkeypatch) -> None:
        monkeypatch.setattr(install_map.importlib.util, "find_spec", lambda _name: None)
        assert resolve_package("spectral_viewer", Path.cwd()).state == "missing"

    def test_an_installed_copy_outside_the_checkout_is_flagged(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        root = tmp_path / "checkout"
        elsewhere = tmp_path / "site-packages" / "bpm_analyzer"
        elsewhere.mkdir(parents=True)
        init = elsewhere / "__init__.py"
        init.write_text("", encoding="utf-8")

        monkeypatch.setattr(
            install_map.importlib.util, "find_spec", lambda _name: _fake_spec(str(init))
        )

        status = resolve_package("bpm_analyzer", root)
        assert status.state == "elsewhere"
        assert status.location is not None
        assert "site-packages" in status.location

    def test_a_namespace_package_counts_as_mapped(self, monkeypatch) -> None:
        """A spec without an origin maps directories, not a foreign copy."""
        monkeypatch.setattr(
            install_map.importlib.util, "find_spec", lambda _name: _fake_spec(None)
        )
        assert resolve_package("audio_suite_shared", Path.cwd()).state == "ok"


class TestEditableInstall:
    def test_the_editable_finder_is_detected(self, monkeypatch) -> None:
        distribution = type(
            "Distribution",
            (),
            {"files": [Path("__editable__.audiosuite_pro-1.4.1.pth")]},
        )()
        monkeypatch.setattr(
            install_map.metadata, "distribution", lambda _name: distribution
        )
        assert editable_install() is True

    def test_a_regular_install_is_not_editable(self, monkeypatch) -> None:
        distribution = type(
            "Distribution", (), {"files": [Path("audiosuite/__init__.py")]}
        )()
        monkeypatch.setattr(
            install_map.metadata, "distribution", lambda _name: distribution
        )
        assert editable_install() is False

    def test_a_missing_distribution_is_not_editable(self, monkeypatch) -> None:
        def _missing(name: str):
            raise metadata.PackageNotFoundError(name)

        monkeypatch.setattr(install_map.metadata, "distribution", _missing)
        assert editable_install() is False


class TestPackagesOutsideCheckout:
    def _root(self, tmp_path: Path) -> Path:
        root = tmp_path / "checkout"
        for name in ("bpm_analyzer", "spectral_viewer"):
            _make_package(root, name)
        return root

    def test_only_packages_from_another_tree_are_reported(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        root = self._root(tmp_path)
        foreign = tmp_path / "site-packages" / "bpm_analyzer" / "__init__.py"
        foreign.parent.mkdir(parents=True)
        foreign.write_text("", encoding="utf-8")

        def find_spec(name: str) -> object:
            if name == "bpm_analyzer":
                return _fake_spec(str(foreign))
            return _fake_spec(str(root / name / "__init__.py"))

        monkeypatch.setattr(install_map.importlib.util, "find_spec", find_spec)

        outside = packages_outside_checkout(root)

        assert [status.name for status in outside] == ["bpm_analyzer"]
        assert outside[0].state == "elsewhere"
        assert outside[0].location is not None
        assert "site-packages" in outside[0].location

    def test_a_missing_package_is_a_different_diagnosis(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        """Registration already names a missing tool; this scan is about origin."""
        root = self._root(tmp_path)
        monkeypatch.setattr(install_map.importlib.util, "find_spec", lambda _name: None)
        assert packages_outside_checkout(root) == []

    def test_a_mapped_checkout_reports_nothing(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        root = self._root(tmp_path)
        monkeypatch.setattr(
            install_map.importlib.util,
            "find_spec",
            lambda name: _fake_spec(str(root / name / "__init__.py")),
        )
        assert packages_outside_checkout(root) == []

    def test_no_checkout_reports_nothing(self, monkeypatch) -> None:
        monkeypatch.setattr(install_map, "checkout_root", lambda: None)
        assert packages_outside_checkout() == []
