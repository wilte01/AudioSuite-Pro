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
it), so that entry states intent while this build proves the outcome. The
consumer check has a negative control on purpose. A mypy run that passes
because the fixture imports nothing meaningful would be indistinguishable from
one that passes because the annotations are gone, so the control mutates a
single ``assert_type`` and requires mypy to reject it.

Changed in 2.4.3: added for WP-10 C-I6.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    staging = tmp_path / "staging"
    staging.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(REPO_ROOT / name, staging / name)
    shutil.copytree(
        PACKAGE_DIR,
        staging / "audio_suite_shared",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
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
