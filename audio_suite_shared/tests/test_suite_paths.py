"""Tests for suite_paths — the suite's one installation-root resolver.

Changed in 2.5.0: locks the four rule labels ``doctor`` prints beside the root,
so a report cannot name a rule the resolver does not choose.
Changed in 2.5.0: new module. The suite root had no shared implementation, so
each caller derived it from its own ``__file__`` and the Help button walked up
from the working directory looking for a folder named ``AudioSuite-Pro``
(plan D-44).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from audio_suite_shared import suite_paths


@pytest.fixture(autouse=True)
def _no_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's own ``AUDIOSUITE_ROOT`` out of every case."""
    monkeypatch.delenv(suite_paths.SUITE_ROOT_ENV, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)


class TestSuiteRoot:
    """The four sources, in order."""

    def test_the_override_names_the_root_outright(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A portable install can say where it lives, and wins over all else."""
        monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(tmp_path))
        assert suite_paths.suite_root() == tmp_path.resolve()

    def test_a_one_file_build_answers_with_its_unpack_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``sys._MEIPASS`` is where the bundle actually put the shipped files."""
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        assert suite_paths.suite_root() == tmp_path.resolve()

    def test_a_one_folder_build_answers_with_the_executables_directory(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Frozen without a unpack directory: the root is beside the executable."""
        executable = tmp_path / "dist" / "AudioSuite.exe"
        executable.parent.mkdir()
        executable.write_bytes(b"MZ")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(executable), raising=False)
        assert suite_paths.suite_root() == executable.parent.resolve()

    def test_a_source_checkout_answers_with_the_repository_root(self) -> None:
        """The developer case: this module sits one level below the root."""
        root = suite_paths.suite_root()
        assert (root / "pyproject.toml").is_file()
        assert (root / "audio_suite_shared" / "suite_paths.py").is_file()

    def test_the_working_directory_cannot_change_the_answer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The defect this replaced: ``open_help`` read ``Path.cwd()``.

        A folder that is not named after the project, started in, must still
        resolve the same installation - that is what a shortcut in another
        directory and a renamed checkout both do.
        """
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        before = suite_paths.suite_root()
        elsewhere = tmp_path / "somewhere-else"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        assert Path.cwd() != before
        assert suite_paths.suite_root() == before


class TestSuitePath:
    """``suite_path`` is the root joined to the components a caller names."""

    def test_it_joins_onto_the_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(tmp_path))
        assert suite_paths.suite_path("logs", "tool.log") == (
            tmp_path.resolve() / "logs" / "tool.log"
        )

    def test_the_committed_fpcalc_is_found_through_it(self) -> None:
        """The product file the Fingerprinter ships, not just a joined string."""
        shipped = suite_paths.suite_path("fpcalc.exe")
        assert shipped.is_file(), f"missing committed {shipped}"

    def test_a_missing_file_is_reported_as_missing_not_invented(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(tmp_path))
        assert not suite_paths.suite_path("absent.dll").exists()


class TestRootSource:
    """The label naming *which* rule answered, which ``doctor`` prints."""

    def test_the_override_names_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(suite_paths.SUITE_ROOT_ENV, str(tmp_path))

        root, source = suite_paths.suite_root_source()

        assert root == tmp_path.resolve()
        assert source == suite_paths.ROOT_SOURCE_ENV

    def test_the_bundle_names_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        root, source = suite_paths.suite_root_source()

        assert root == tmp_path.resolve()
        assert source == suite_paths.ROOT_SOURCE_BUNDLE

    def test_the_frozen_executable_names_itself(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executable = tmp_path / "AudioSuite.exe"
        executable.write_bytes(b"MZ")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "executable", str(executable), raising=False)

        root, source = suite_paths.suite_root_source()

        assert root == executable.parent.resolve()
        assert source == suite_paths.ROOT_SOURCE_FROZEN

    def test_the_checkout_names_itself(self) -> None:
        root, source = suite_paths.suite_root_source()

        assert source == suite_paths.ROOT_SOURCE_CHECKOUT
        assert root == suite_paths.suite_root()

    def test_suite_root_still_answers_the_path_alone(self) -> None:
        """Every existing caller keeps the plain return type."""
        assert isinstance(suite_paths.suite_root(), Path)
