"""PEP 561 marker and downstream-consumer locks (WP-10 C-I6).

A ``py.typed`` file tells a type checker that a package's own annotations are
authoritative instead of treating every import as ``Any``. The marker alone
proves nothing, so this module locks the three things that make the claim
true: the file exists and is empty, a built wheel carries it, and a consumer
outside the package really sees the annotations.

The wheel check builds one from a staging copy of the packaging inputs, because
the claim is about the artefact and not about the source tree. It does not rest
on the ``package-data`` entry: setuptools already copies ``py.typed`` on its own
(measured during 2.4.3 - a wheel built with the entry removed still carried
it), so that entry states intent while this build proves the outcome. That entry
is now checked in both directions too (``TestThePackageDataMatchesThePackage``):
a name it declares but the package root lacks ships nothing, and a data file in
the root that it does not name never ships. The
consumer check has a negative control on purpose. A mypy run that passes
because the fixture imports nothing meaningful would be indistinguishable from
one that passes because the annotations are gone, so the control mutates a
single ``assert_type`` and requires mypy to reject it.

Changed in 2.4.3: added for WP-10 C-I6.

Changed in 2.6.0: the packaging suggestions S-2, S-4 and S-5 are worked here.
The wheel's contents are type-checked as an install (with a negative control
that removes a module from it), the sdist is read for the same package data,
and the wheel is asserted to carry no build artefacts - each by the artefact's
contents, never by the filter or the declaration that was meant to produce it.
"""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_DIR = REPO_ROOT / "audio_suite_shared"
MARKER = PACKAGE_DIR / "py.typed"
CONSUMER = REPO_ROOT / "typing_consumer" / "consumer.py"

#: The one assertion the negative control flips. Kept as a constant so a
#: reworded fixture fails the control loudly instead of silently proving
#: nothing (``str.replace`` on a missing needle is a no-op).
_DISCRIMINATING_ASSERTION = "assert_type(load_last_directory(), str)"
_MUTATED_ASSERTION = "assert_type(load_last_directory(), int)"


def _run_mypy(path: Path) -> subprocess.CompletedProcess[str]:
    """Type-check one file with the repository's own mypy configuration.

    Args:
        path: The file to check.

    Returns:
        The completed process; the caller decides what a pass means.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(REPO_ROOT / "pyproject.toml"),
            "--no-incremental",
            str(path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        # The fixture may live outside the repository (the control does), so
        # the shared package is resolved through the search path rather than
        # through the file's own directory.
        env={**os.environ, "MYPYPATH": str(REPO_ROOT)},
        timeout=300,
    )


#: ``setuptools.build_meta`` reads ``./pyproject.toml``, so the build runs with
#: the staging copy as its working directory and writes into the given folder.
_BUILD_WHEEL_SCRIPT = (
    "import sys\n"
    "from setuptools import build_meta\n"
    "print(build_meta.build_wheel(sys.argv[1]))\n"
)


def _stage_inputs(tmp_path: Path) -> Path:
    """Copy the files the build reads into a throwaway staging tree.

    Only the project metadata, its readme and licence, and the package under
    test: copying the whole checkout would build every sibling package for one
    assertion.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The staging directory the build runs in.
    """
    staging = tmp_path / "staging"
    staging.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO_ROOT / name, staging / name)
    shutil.copytree(
        PACKAGE_DIR,
        staging / "audio_suite_shared",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    return staging


#: The sdist is assembled by different include rules than the wheel, so it is
#: built and read separately rather than inferred from the wheel's contents.
_BUILD_SDIST_SCRIPT = (
    "import sys\n"
    "from setuptools import build_meta\n"
    "print(build_meta.build_sdist(sys.argv[1]))\n"
)


def _build_sdist(tmp_path: Path) -> Path:
    """Build an sdist from the same staging copy the wheel uses.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The single ``.tar.gz`` the build produced.
    """
    staging = _stage_inputs(tmp_path)
    out = tmp_path / "dist_sdist"
    out.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", _BUILD_SDIST_SCRIPT, str(out)],
        cwd=staging,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    archives = sorted(out.glob("*.tar.gz"))
    assert len(archives) == 1, [archive.name for archive in archives]
    return archives[0]


def _unpack_wheel(wheel: Path, target: Path) -> Path:
    """Lay a wheel out in *target* the way an install does.

    A pure-Python wheel is the package tree plus its metadata, so extracting it
    is what ``pip install --no-index --no-deps --target`` would produce, without
    an installer, a network probe or a resolver in the test.

    Args:
        wheel: The built wheel.
        target: Directory to unpack into.

    Returns:
        *target*, for convenient chaining.
    """
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(target)
    return target


def _run_mypy_against(
    path: Path, search_path: Path, cwd: Path
) -> subprocess.CompletedProcess[str]:
    """Type-check *path* with *search_path* as the only route to the package.

    Args:
        path: The consumer file to check.
        search_path: Directory mypy must resolve ``audio_suite_shared`` from.
        cwd: Working directory, kept outside the checkout.

    Returns:
        The completed process; the caller decides what a pass means.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--config-file",
            str(REPO_ROOT / "pyproject.toml"),
            "--no-incremental",
            str(path),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env={**os.environ, "MYPYPATH": str(search_path)},
        timeout=300,
    )


def _build_wheel(tmp_path: Path) -> Path:
    """Build a wheel from a staging copy of the packaging inputs.

    Only the files the build reads are copied: the project metadata, its
    readme and licence, and the package under test. Copying the whole checkout
    would build every sibling package for one assertion.

    Args:
        tmp_path: The test's temporary directory.

    Returns:
        The single wheel the build produced.
    """
    staging = _stage_inputs(tmp_path)
    out = tmp_path / "dist"
    out.mkdir()
    result = subprocess.run(
        [sys.executable, "-c", _BUILD_WHEEL_SCRIPT, str(out)],
        cwd=staging,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    wheels = sorted(out.glob("*.whl"))
    assert len(wheels) == 1, [wheel.name for wheel in wheels]
    return wheels[0]


class TestTheMarkerShips:
    """The marker exists, is empty, and is declared as package data."""

    def test_the_marker_exists(self) -> None:
        assert MARKER.is_file(), "audio_suite_shared/py.typed is missing"

    def test_the_marker_is_empty(self) -> None:
        """PEP 561 gives the contents no meaning, so they stay empty.

        A note inside the file would be read as marker data by other tools
        that inspect it; the change note lives in ``test_release_notes``.
        """
        assert MARKER.read_bytes() == b""

    def test_the_package_data_declares_the_marker(self) -> None:
        """The entry records intent; the wheel build below proves the outcome.

        setuptools also copies ``py.typed`` on its own, so this declaration is
        not what makes the marker ship - dropping it must still not be silent.
        """
        config = tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        package_data = config["tool"]["setuptools"]["package-data"]
        assert "py.typed" in package_data["audio_suite_shared"]


class TestTheShippedFilesAreInABuiltWheel:
    """A package-data entry is a claim about a wheel, so build one.

    The build runs against a staging copy, never the checkout: ``setuptools``
    writes ``build/`` and ``*.egg-info/`` beside its inputs, and a test that
    measures the tree must not leave its own output in it.
    """

    def test_the_wheel_contains_the_package_data_files(self, tmp_path: Path) -> None:
        pytest.importorskip("setuptools")
        wheel = _build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            # The positive control: without this the data assertions could
            # pass on a wheel that carries nothing at all.
            assert "audio_suite_shared/__init__.py" in names, names
            assert "audio_suite_shared/py.typed" in names, names
            assert archive.getinfo("audio_suite_shared/py.typed").file_size == 0
            # `--json-schema` prints this document, so the wheel must carry
            # the same bytes the checkout does. Unlike `py.typed`, setuptools
            # does not copy a .json automatically: this is the assertion the
            # package-data entry actually protects.
            schema = "audio_suite_shared/cli_schema.json"
            assert schema in names, names
            assert (
                archive.read(schema) == (PACKAGE_DIR / "cli_schema.json").read_bytes()
            )


def _declared_patterns() -> list[str]:
    """The ``package-data`` patterns the build declares for this package."""
    config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return list(config["tool"]["setuptools"]["package-data"]["audio_suite_shared"])


def _shipped_data_files() -> set[str]:
    """Root-level, non-Python files of the package: what a wheel could ship.

    Only the package root is scanned. A data file inside a subpackage needs its
    own declaration key, which this lock does not claim to cover.
    """
    return {
        path.name
        for path in PACKAGE_DIR.iterdir()
        if path.is_file() and path.suffix not in {".py", ".pyc", ".pyo"}
    }


def _resolved_declaration() -> tuple[set[str], list[str]]:
    """Expand the declared patterns against the package root.

    Returns:
        The shipped files the declaration names, and any pattern that matched
        nothing - a stale entry names a file that was renamed or deleted.
    """
    shipped = _shipped_data_files()
    resolved: set[str] = set()
    unmatched: list[str] = []
    for pattern in _declared_patterns():
        hits = {name for name in shipped if fnmatch.fnmatchcase(name, pattern)}
        if hits:
            resolved |= hits
        else:
            unmatched.append(pattern)
    return resolved, unmatched


class TestThePackageDataMatchesThePackage:
    """A ``package-data`` declaration is a bidirectional claim.

    It names files that must exist, and the package root holds data files that
    must be named. Checking one direction only lets the other drift silently: a
    stale name ships nothing, and an undeclared file never ships at all.
    """

    def test_every_declared_file_exists_in_the_package_root(self) -> None:
        _resolved, unmatched = _resolved_declaration()
        assert not unmatched, (
            "package-data declares files the package root does not have "
            f"(renamed or deleted?): {unmatched}"
        )

    def test_every_shipped_data_file_is_declared(self) -> None:
        resolved, _unmatched = _resolved_declaration()
        undeclared = sorted(_shipped_data_files() - resolved)
        assert not undeclared, (
            "these files sit in the package root but package-data never names "
            f"them, so a wheel install would not carry them: {undeclared}"
        )

    def test_every_declared_file_reaches_the_wheel(self, tmp_path: Path) -> None:
        """The tree check proves intent; only the wheel proves the outcome."""
        pytest.importorskip("setuptools")
        resolved, _unmatched = _resolved_declaration()
        wheel = _build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as archive:
            names = set(archive.namelist())
        assert "audio_suite_shared/__init__.py" in names, sorted(names)
        missing = sorted(
            name for name in resolved if f"audio_suite_shared/{name}" not in names
        )
        assert not missing, f"declared but absent from the wheel: {missing}"


class TestTheConsumerIsCheckedByTheGate:
    """The fixture must sit where the bare ``mypy .`` reaches it."""

    def test_the_consumer_fixture_exists(self) -> None:
        assert CONSUMER.is_file()

    def test_the_consumer_is_outside_the_excluded_tests_tree(self) -> None:
        """``[tool.mypy] exclude`` drops ``tests/``, so a fixture there would
        only ever be checked by this module's subprocess."""
        relative = CONSUMER.relative_to(REPO_ROOT)
        assert "tests" not in relative.parts
        config = tomllib.loads(
            (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert "^tests/" in config["tool"]["mypy"]["exclude"]


class TestTheConsumerSeesAnnotations:
    """The fixture passes, and the same run fails when an annotation is wrong."""

    def test_the_fixture_type_checks(self) -> None:
        pytest.importorskip("mypy")
        result = _run_mypy(CONSUMER)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Success" in result.stdout

    def test_a_wrong_annotation_is_reported(self, tmp_path: Path) -> None:
        pytest.importorskip("mypy")
        source = CONSUMER.read_text(encoding="utf-8")
        assert _DISCRIMINATING_ASSERTION in source, (
            "the consumer fixture no longer carries the assertion the "
            "negative control mutates - update the control, do not drop it"
        )
        broken = tmp_path / "broken_consumer.py"
        broken.write_text(
            source.replace(_DISCRIMINATING_ASSERTION, _MUTATED_ASSERTION),
            encoding="utf-8",
        )
        result = _run_mypy(broken)
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        assert "[assert-type]" in combined, combined


class TestTheWheelCarriesNoBuildArtefacts:
    """S-5: the outcome, not the ignore list that was meant to produce it.

    ``_stage_inputs`` filters ``__pycache__``, ``*.pyc`` and ``*.pyo`` by name,
    which only excludes what it was told about. Reading the wheel's namelist is
    what proves the shipped artefact is clean.
    """

    def test_no_bytecode_or_cache_directory_reaches_the_wheel(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("setuptools")
        wheel = _build_wheel(tmp_path)
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
        # The positive control: an empty or broken wheel would pass vacuously.
        assert "audio_suite_shared/__init__.py" in names, names
        offenders = [
            name
            for name in names
            if "__pycache__" in name or name.endswith((".pyc", ".pyo"))
        ]
        assert not offenders, f"build artefacts shipped: {offenders}"


class TestTheSdistCarriesTheSameData:
    """S-4: the sdist has its own include rules, so read the tarball.

    ``cli_schema.json`` is loaded at CLI import, so an sdist install that omits
    it fails on first use rather than at install time - the failure mode is
    worth a direct check.
    """

    def test_the_sdist_carries_every_declared_data_file(self, tmp_path: Path) -> None:
        pytest.importorskip("setuptools")
        resolved, _unmatched = _resolved_declaration()
        archive = _build_sdist(tmp_path)
        with tarfile.open(archive) as tar:
            names = tar.getnames()
        # sdist nests everything under ``<name>-<version>/``.
        assert any(name.endswith("audio_suite_shared/__init__.py") for name in names), (
            names
        )
        missing = sorted(
            name
            for name in resolved
            if not any(entry.endswith(f"audio_suite_shared/{name}") for entry in names)
        )
        assert not missing, f"declared but absent from the sdist: {missing}"


class TestTheInstalledWheelIsTyped:
    """S-2: the PEP 561 claim from the position a consumer is actually in.

    ``TestTheConsumerSeesAnnotations`` resolves the package through the
    checkout, so it proves the source tree is annotated; it cannot prove the
    distribution is. These checks resolve the package from the wheel's own
    contents and run the same consumer against it.
    """

    def test_the_consumer_type_checks_against_the_wheels_contents(
        self, tmp_path: Path
    ) -> None:
        pytest.importorskip("setuptools")
        pytest.importorskip("mypy")
        wheel = _build_wheel(tmp_path)
        installed = _unpack_wheel(wheel, tmp_path / "installed")
        consumer = tmp_path / "installed_consumer.py"
        consumer.write_text(CONSUMER.read_text(encoding="utf-8"), encoding="utf-8")

        result = _run_mypy_against(consumer, installed, tmp_path)

        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined
        assert "Success" in combined, combined

    def test_the_check_reads_the_install_not_the_checkout(self, tmp_path: Path) -> None:
        """Negative control: if mypy used the checkout, this mutation is unseen."""
        pytest.importorskip("setuptools")
        pytest.importorskip("mypy")
        wheel = _build_wheel(tmp_path)
        installed = _unpack_wheel(wheel, tmp_path / "installed")
        removed = installed / "audio_suite_shared" / "suite_config.py"
        assert removed.is_file(), "the wheel layout changed; update the control"
        removed.unlink()
        consumer = tmp_path / "installed_consumer.py"
        consumer.write_text(CONSUMER.read_text(encoding="utf-8"), encoding="utf-8")

        result = _run_mypy_against(consumer, installed, tmp_path)

        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined
        # ``ignore_missing_imports`` turns the vanished module into ``Any``
        # instead of a "cannot find" error, so the signal is the two consumer
        # assertions that read its annotations - the same two that pass above.
        assert combined.count("[assert-type]") == 2, combined
        assert "Success" not in combined, combined
