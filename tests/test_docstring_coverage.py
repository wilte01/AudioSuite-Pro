"""Lock the shared package's public API documentation (PLAN D98).

``audio_suite_shared`` is what every tool imports, so its docstrings are the
API reference a tool author reads. The audit lives in
``utilities/docstring_report.py``; this module is the lock that keeps the
scoped set closed, and it proves the audit can fail.

Scope, deliberately: the module docstring, top-level public functions and
classes, and public methods of public classes. Property setters are excluded
(they restate their getter) and so are nested helpers (they are not reachable
from outside). ``audio_fingerprinter/core/models.py`` and
``master_driver/state/app_state.py`` join the scan because they are the two
largest model surfaces a UI or CLI consumer reads; the rest of the tree is
not swept, so the lock stays a reviewable one-file-per-module change.

Changed in 1.4.1: initial version, the D98 documentation lock.
Changed in 1.4.1: the method rule and the two model modules; the report's
setter exclusion is asserted here so it cannot widen unnoticed.
"""

from __future__ import annotations

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED = REPO_ROOT / "audio_suite_shared"

#: The two model modules D98 named as the largest gaps outside the package.
MODELS = (
    REPO_ROOT / "audio_fingerprinter" / "core" / "models.py",
    REPO_ROOT / "master_driver" / "state" / "app_state.py",
)

#: Public definitions allowed to stay undocumented, name -> reason. Empty: the
#: D98 scope closed every gap in the shared package, so an entry here is a
#: deliberate exception and needs the reason that justifies it.
ALLOWLIST: dict[str, str] = {}


def _load_report() -> ModuleType:
    """Import ``utilities/docstring_report.py`` by path (it is not a package)."""
    spec = spec_from_file_location(
        "docstring_report_locked", REPO_ROOT / "utilities" / "docstring_report.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    # A dataclass resolves its annotations through ``sys.modules`` while the
    # module body runs, so it must be registered before exec_module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def report() -> ModuleType:
    """The audit module, imported once for the whole module."""
    return _load_report()


def _files(report: ModuleType) -> list[Path]:
    """Return the scannable files of the locked scope."""
    files: list[Path] = report.scanned_files([SHARED, *MODELS])
    return files


def _gaps(report: ModuleType) -> list[Any]:
    """Return every gap in the shared package."""
    return [gap for path in _files(report) for gap in report.gaps_in(path)]


def _write(path: Path, text: str) -> Path:
    """Write *text* to *path* as UTF-8 and return the path."""
    path.write_text(text, encoding="utf-8")
    return path


class TestTheSharedPackageIsDocumented:
    """Every public definition the package exports has a docstring."""

    def test_no_public_definition_is_undocumented(self, report: ModuleType) -> None:
        unexpected = [
            f"{Path(gap.path).name}:{gap.line} {gap.kind} {gap.name}"
            for gap in _gaps(report)
            if gap.name not in ALLOWLIST
        ]

        assert not unexpected, (
            "Public definitions without a docstring; document them, or add the "
            f"name to ALLOWLIST with the reason: {unexpected}"
        )

    def test_the_scan_found_a_real_surface(self, report: ModuleType) -> None:
        """An empty scan would pass every assertion above, so prove it is not."""
        files = _files(report)
        symbols = sum(len(report.public_symbols(path)) for path in files)

        assert len(files) >= 40, f"only {len(files)} files scanned under {SHARED}"
        assert symbols >= 100, f"only {symbols} public symbols discovered"
        assert {path.resolve() for path in MODELS} <= {p.resolve() for p in files}

    def test_every_allowlisted_name_is_explained_and_still_missing(
        self, report: ModuleType
    ) -> None:
        missing = {gap.name for gap in _gaps(report)}

        for name, reason in ALLOWLIST.items():
            assert reason.strip(), f"{name}: an allowlist entry needs a reason"
            assert name in missing, (
                f"{name}: allowlisted but no longer undocumented; remove the entry"
            )


class TestTheReportCanFail:
    """The audit flags what it exists to flag, on a module written for the test."""

    def test_it_flags_a_missing_function_and_module_docstring(
        self, report: ModuleType, tmp_path: Path
    ) -> None:
        module = _write(tmp_path / "sample.py", "def public_function():\n    pass\n")

        gaps = report.gaps_in(module)

        assert [(gap.kind, gap.name) for gap in gaps] == [
            ("module", "sample"),
            ("function", "public_function"),
        ]

    def test_it_flags_a_missing_class_docstring(
        self, report: ModuleType, tmp_path: Path
    ) -> None:
        module = _write(
            tmp_path / "sample.py",
            '"""Documented."""\n\n\nclass Service:\n    pass\n',
        )

        gaps = report.gaps_in(module)

        assert [(gap.kind, gap.name) for gap in gaps] == [("class", "Service")]

    def test_it_flags_a_missing_method_docstring(
        self, report: ModuleType, tmp_path: Path
    ) -> None:
        """A public method is part of the surface, so it needs its own words."""
        module = _write(
            tmp_path / "sample.py",
            '"""Documented."""\n\n\nclass Service:\n    """Documented."""\n\n'
            "    def run(self) -> None:\n        pass\n\n"
            "    def _hidden(self) -> None:\n        pass\n",
        )

        gaps = report.gaps_in(module)

        assert [(gap.kind, gap.name) for gap in gaps] == [("method", "Service.run")]

    def test_a_property_setter_is_not_its_own_gap(
        self, report: ModuleType, tmp_path: Path
    ) -> None:
        """The setter restates its getter, so only the getter carries words."""
        module = _write(
            tmp_path / "sample.py",
            '"""Documented."""\n\n\nclass Service:\n    """Documented."""\n\n'
            "    @property\n    def enabled(self) -> bool:\n"
            '        """Return whether the service is on."""\n        return True\n\n'
            "    @enabled.setter\n    def enabled(self, value: bool) -> None:\n"
            "        self._enabled = value\n",
        )

        assert report.gaps_in(module) == []
        assert "Service.enabled" in report.public_symbols(module)

    def test_a_documented_module_is_clean(
        self, report: ModuleType, tmp_path: Path
    ) -> None:
        module = _write(
            tmp_path / "sample.py",
            '"""Documented."""\n\n\ndef _private():\n    pass\n\n\n'
            'def public_function():\n    """Documented."""\n',
        )

        assert report.gaps_in(module) == []
        assert report.public_symbols(module) == ["sample", "public_function"]

    def test_the_cli_exits_one_when_a_gap_exists(
        self, report: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / "sample.py", "def undocumented():\n    pass\n")

        code = report.main(["--path", str(tmp_path)])

        captured = capsys.readouterr()
        assert code == 1
        assert "[MISSING]" in captured.out
        assert "missing docstring" in captured.out

    def test_a_missing_path_is_an_error_not_an_empty_pass(
        self, report: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = report.main(["--path", str(tmp_path / "nope")])

        assert code == 2
        assert "[ERROR]" in capsys.readouterr().err
