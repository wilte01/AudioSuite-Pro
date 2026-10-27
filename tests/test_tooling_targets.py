"""Lock the interpreter the suite's tooling declares to the floor it ships.

``[project] requires-python`` is a promise, and three declarations have to agree
about it: the floor itself, Ruff's ``target-version`` (which decides both the
grammar Ruff checks against and which standard-library modules it knows as
stdlib) and mypy's ``python_version`` (which decides the typeshed stubs and the
syntax the type gate accepts).  They disagreed for three releases — Ruff
targeted ``py310`` and mypy ``3.12`` against a ``>=3.11`` floor — and nothing in
the suite noticed:

* **Ruff was green for the wrong reason.**  At a py310 target ``tomllib`` is not
  standard library, so a correct 3.11 import block was mis-sorted; raising the
  target to py311 reported 12 `I001` findings that had been invisible.  Ruff
  reports nothing when the target is wrong, so silence was never evidence.
* **mypy certified a target nothing runs.**  ``python_version = "3.12"`` passed
  while the floor leg the package declares could not run the code it approved;
  checked at 3.11 it reported one real error (``ndarray.max()`` with no
  argument, `spectral_viewer/core/spectrogram.py`).

So the lock is one equality, asserted three ways, plus the CI jobs that have to
install what the declarations promise: the ``typecheck`` job must run the floor
interpreter, and the ``lint`` job's Ruff must come from ``uv.lock`` rather than
an unpinned ``pip install ruff`` — an unpinned linter can red the gate when the
repository has not changed at all.

Every extraction is checked non-empty first, and the disagreement path is
exercised against edited copies of the real file, so neither a missing section
nor a check that cannot fail can pass this module.

The security gate is locked here for the same reason: ``packaging/build``
(gitignored, written by the installer) stages a copy of the app *and* a bundled
CPython, and Bandit walked it - 3690 HIGH findings from CPython's own stdlib, so
the documented ``bandit -r . -x ./.venv -c pyproject.toml`` could not pass in a
state a developer reaches just by building the installer.  Bandit matches
``exclude_dirs`` entries as path *substrings*, so the entries are asserted
narrow: an over-broad entry would drop first-party modules from the scan.

Changed in 2.1.6: initial version (R-15,
PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

from tests.ci_workflow import job

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: The floor the three declarations must name, as ``(major, minor)``.
#: Spelled out rather than derived from the file under test: a lock that reads
#: its expectation from its subject asserts only that the file equals itself.
EXPECTED_FLOOR = (3, 11)

#: ``">=3.11"`` -> ``(3, 11)``; the lowest bound ``requires-python`` names.
_REQUIRES_PATTERN = re.compile(r">=\s*(\d+)\.(\d+)")

#: ``"py311"`` -> ``(3, 11)``; ``"py39"`` -> ``(3, 9)``.
_TARGET_PATTERN = re.compile(r"py(\d)(\d+)")

#: ``python-version: "3.11"`` inside a job block.
_JOB_PYTHON_PATTERN = re.compile(r'python-version:\s*"([^"]+)"')


def _load(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed pyproject, asserting the sections this lock reads exist.

    Args:
        path: The file to read; the real ``pyproject.toml`` when omitted.

    Returns:
        The parsed TOML document.

    Raises:
        AssertionError: if a table this lock inspects is missing, because every
            extraction below would then fail for the wrong reason.
    """
    source = PYPROJECT if path is None else path
    with source.open("rb") as handle:
        data: dict[str, Any] = tomllib.load(handle)

    for section in ("project", "tool"):
        assert data.get(section), f"{source.name} has no [{section}] table"
    tool = data["tool"]
    for key in ("ruff", "mypy", "bandit"):
        assert tool.get(key), f"{source.name} has no [tool.{key}] table"
    return data


def floor(path: Path | None = None) -> tuple[int, int]:
    """Return the lowest interpreter ``[project] requires-python`` allows.

    Raises:
        AssertionError: if ``requires-python`` names no lower bound.
    """
    requires = _load(path)["project"]["requires-python"]
    match = _REQUIRES_PATTERN.search(requires)
    assert match is not None, f"requires-python {requires!r} names no lower bound"
    return int(match.group(1)), int(match.group(2))


def ruff_target(path: Path | None = None) -> tuple[int, int]:
    """Return ``[tool.ruff] target-version`` as a ``(major, minor)`` pair."""
    target = _load(path)["tool"]["ruff"]["target-version"]
    match = _TARGET_PATTERN.fullmatch(target)
    assert match is not None, f"target-version {target!r} is not a pyXYZ value"
    return int(match.group(1)), int(match.group(2))


def mypy_target(path: Path | None = None) -> tuple[int, int]:
    """Return ``[tool.mypy] python_version`` as a ``(major, minor)`` pair."""
    version = _load(path)["tool"]["mypy"]["python_version"]
    parts = version.split(".")
    assert len(parts) == 2, f"python_version {version!r} is not major.minor"
    return int(parts[0]), int(parts[1])


def _render(version: tuple[int, int]) -> str:
    return f"{version[0]}.{version[1]}"


def disagreements(path: Path | None = None) -> list[str]:
    """Return one line per declaration that does not name the floor.

    Args:
        path: The pyproject to inspect; the real one when omitted.

    Returns:
        Empty when every declaration agrees with ``requires-python``.
    """
    want = floor(path)
    found = (
        ("[tool.ruff] target-version", ruff_target(path)),
        ("[tool.mypy] python_version", mypy_target(path)),
    )
    return [
        f"{label} is {_render(value)}, but requires-python's floor is {_render(want)}"
        for label, value in found
        if value != want
    ]


def _edited(tmp_path: Path, old: str, new: str) -> Path:
    """Write a copy of the real pyproject with one value replaced.

    Raises:
        AssertionError: if ``old`` is no longer in the file - the proof below
            must fail loudly rather than test an unedited copy.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    assert old in text, f"pyproject.toml no longer contains {old!r}"
    copy = tmp_path / "pyproject.toml"
    copy.write_text(text.replace(old, new, 1), encoding="utf-8")
    return copy


class TestTheDeclaredTargetsAgree:
    """Ruff's target, mypy's version and the floor are one number."""

    def test_the_floor_is_what_the_plan_says(self) -> None:
        assert floor() == EXPECTED_FLOOR, (
            "requires-python's floor moved; the lock, the CI matrix and the "
            "README's prerequisites all name it (PLAN_audit_2026-10-24_"
            "deferred_p2p3.md R-15)"
        )

    def test_both_tools_target_the_floor(self) -> None:
        problems = disagreements()

        assert not problems, (
            "the tooling targets disagree with requires-python:\n  "
            + "\n  ".join(problems)
        )

    def test_a_lower_ruff_target_is_reported(self, tmp_path: Path) -> None:
        """The pre-R-15 value must fail this lock, not pass it."""
        copy = _edited(tmp_path, 'target-version = "py311"', 'target-version = "py310"')

        problems = disagreements(copy)

        assert problems, "a py310 target against a 3.11 floor passed the lock"
        assert any("target-version" in line for line in problems), problems

    def test_a_different_mypy_target_is_reported(self, tmp_path: Path) -> None:
        copy = _edited(tmp_path, 'python_version = "3.11"', 'python_version = "3.12"')

        problems = disagreements(copy)

        assert problems, "a 3.12 mypy target against a 3.11 floor passed the lock"
        assert any("python_version" in line for line in problems), problems

    def test_a_raised_floor_is_reported(self, tmp_path: Path) -> None:
        """Raising the floor alone leaves both tools behind it."""
        copy = _edited(
            tmp_path, 'requires-python = ">=3.11"', 'requires-python = ">=3.12"'
        )

        problems = disagreements(copy)

        assert len(problems) == 2, problems


class TestTheCiJobsUseTheFloor:
    """CI installs the interpreter and the linter the declarations promise."""

    @staticmethod
    def _executed(block: str) -> str:
        """Return a job block's executed lines, with its comments removed.

        The lint job's comment explains why it takes ruff from the lock and
        quotes the command it replaced, and a comment cannot install anything -
        the same distinction ``tests/test_ci_security_audit.py`` draws when it
        proves the audit never points at ``.venv``.  Matching the raw block
        would fail on the explanation rather than on the wiring.
        """
        return "\n".join(
            line for line in block.splitlines() if not line.strip().startswith("#")
        )

    def test_the_typecheck_job_runs_the_floor(self) -> None:
        block = job("typecheck")
        found = _JOB_PYTHON_PATTERN.findall(block)

        assert found == [_render(EXPECTED_FLOOR)], (
            "the typecheck job must install exactly the floor interpreter "
            f"({_render(EXPECTED_FLOOR)}); it names {found}"
        )

    def test_the_typecheck_job_still_runs_mypy(self) -> None:
        """Non-vacuity for the slice above: an empty job would pass it."""
        assert "uv run mypy ." in job("typecheck")

    def test_the_lint_job_takes_ruff_from_the_lock(self) -> None:
        executed = self._executed(job("lint"))

        assert "uv sync" in executed, "the lint job no longer installs from uv.lock"
        assert "uv run ruff check ." in executed, "ruff check is no longer locked"
        assert "uv run ruff format --check ." in executed, (
            "ruff format is no longer locked"
        )
        assert "pip install ruff" not in executed, (
            "the lint job installs an unpinned ruff again: a new release with a "
            "new default rule would red the gate with no repository change"
        )

    def test_the_comment_removal_is_narrow(self) -> None:
        """Non-vacuity: the filter drops comments, not the whole job."""
        executed = self._executed(job("lint"))

        assert "uses: actions/checkout@v4" in executed
        assert "Changed in 2.1.6" not in executed


#: Entries ``[tool.bandit] exclude_dirs`` must declare, and nothing wider.
_EXPECTED_EXCLUSIONS = ("tests", "packaging")

#: Directory parts the scanning guard below never reads: not source of ours.
_GENERATED_PARTS = frozenset(
    {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache", "build", "dist"}
)

#: The guard's walk must reach at least this many files, so a broken walk fails
#: instead of passing vacuously (the floor is well under the real count).
_MIN_PYTHON_FILES = 400


class TestTheSecurityGateSkipsTheInstallerOutput:
    """Bandit scans first-party Python - never the installer's output tree.

    ``packaging/build`` is gitignored build output: a copy of the app plus a
    bundled CPython.  The documented gate command walks ``.``, so it read that
    tree and reported 3690 HIGH findings drawn from CPython's own stdlib, while
    CI - which never builds the installer - stayed green.  Two things could
    quietly undo the fix: dropping the exclusion again, or widening it until it
    swallows first-party code, since Bandit matches entries as substrings.
    """

    def test_the_installer_output_is_excluded(self) -> None:
        declared = _load()["tool"]["bandit"]["exclude_dirs"]

        for entry in _EXPECTED_EXCLUSIONS:
            assert entry in declared, (
                f"bandit no longer excludes {entry!r}; it excludes {declared}. "
                "Without it the security gate fails for anyone who has built "
                "the installer"
            )

    def test_the_exclusions_cannot_swallow_first_party_code(self) -> None:
        """Every path an entry matches must already be out of scope.

        A substring entry is a blind spot as wide as its shortest match, so this
        asserts the *consequence* rather than the entry: a production module
        whose path contains an excluded entry fails here.  ``tests`` is the one
        deliberate exclusion, hence the allowance for a ``tests`` part.
        """
        declared: list[str] = _load()["tool"]["bandit"]["exclude_dirs"]
        examined = 0
        swallowed: list[str] = []

        for path in sorted(REPO_ROOT.rglob("*.py")):
            parts = path.relative_to(REPO_ROOT).parts
            if _GENERATED_PARTS.intersection(parts):
                continue
            examined += 1
            relative = "/".join(parts)
            if not any(entry in relative for entry in declared):
                continue
            if "tests" in parts:
                continue
            swallowed.append(relative)

        assert examined >= _MIN_PYTHON_FILES, (
            f"the guard reached only {examined} files - the walk is broken, so "
            "it would pass without checking anything"
        )
        assert not swallowed, (
            "these production modules match a bandit exclusion entry, so the "
            "security gate never reads them:\n  " + "\n  ".join(swallowed)
        )
