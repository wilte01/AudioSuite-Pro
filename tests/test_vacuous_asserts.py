"""
tests/test_vacuous_asserts.py - no vacuous assertions in tracked tests.

Session D3 post-mortem (AudioSuite iteration-7): several test drafts were
generated through shell-string editing and shipped shapes that compile and
pass but verify nothing:

* ``assert x or True``                  - always true
* ``assert (a, b, c)``                  - assert on a bare tuple literal
* ``assert a, b; b = x``                - (out of scope here; not a shape)
* ``x = x if False else y``             - the carrying assign, never the guard

An assert that CANNOT fail is worse than no assert - it masquerades as
verification (the same class the iteration-5 non-vacuity guards target, at
syntax level; see the A3 "silent swallow" and G1 "empty scan" lessons).
This lock sweeps every tracked ``*.py`` file whose path contains a
``tests/`` segment through the AST and rejects those shapes, with a
self-check proving each matcher genuinely matches (non-vacuity discipline,
iteration-5 G1).

The tracked set is read through ``git ls-files`` so the locks assert on what
is actually *committed*, not merely present in a working tree.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def tracked_test_files() -> tuple[Path, ...]:
    """Every tracked ``*.py`` file living in a ``tests/`` directory.

    Returns:
        Paths (absolute, sorted) relative to the repo root.

    Raises:
        AssertionError: if git lists nothing - the lock would read nothing.
    """
    out = subprocess.run(
        ["git", "ls-files", "*.py"],  # B603/B607: audited pattern, shell=False
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=True,
    ).stdout.splitlines()
    files = sorted(
        REPO_ROOT / line
        for line in out
        if "tests" in Path(line).parts and line.endswith(".py")
    )
    assert files, "git ls-files found no tracked test files"
    return tuple(files)


def find_vacuous_asserts(tree: ast.AST) -> list[str]:
    """Return human-readable descriptions of vacuous assertion shapes in
    *tree* (one entry per offending line).

    Shapes locked (each one makes the assert unable to verify intent):
        1. ``assert <anything> or True`` - always-true boolean or.
        2. ``assert <anything> and False`` - constant folded in real Python?
           No: False is a literal and the assert always fails to verify the
           first operand, so it is equally vacuous in the sense of verifying
           nothing about the operand.
        3. ``assert (a, b, ...)`` - assert on a tuple literal: never empty.
        4. ``assert x if False else y`` - a conditional expression whose test
           is a constant False, so the asserted operand is the *carry* value.
        5. ``assert <anything> if True else y`` - same, positive direction.

    Args:
        tree: Parsed module AST of one test file.

    Returns:
        A list of ``"field:<line> <description>"`` strings; empty when the
        file contains no vacuous assert shape.
    """
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert):
            continue
        cond = node.test
        # Shape 1/2: assert <a> or True / assert <a> and False
        if isinstance(cond, ast.BoolOp) and isinstance(cond.op, (ast.Or, ast.And)):
            for value in cond.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, bool):
                    findings.append(f"bool-literal operand at line {cond.lineno}")
        # Shape 3: assert on a tuple literal
        if isinstance(cond, ast.Tuple) and cond.elts:
            findings.append(f"tuple-literal operand at line {cond.lineno}")
        # Shape 4/5: assert on a conditional whose test is a bool constant
        if isinstance(cond, ast.IfExp) and isinstance(cond.test, ast.Constant):
            if isinstance(cond.test.value, bool):
                findings.append(f"constant IfExp test at line {cond.lineno}")
    return findings


def _compile(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_no_vacuous_asserts_in_any_tracked_test_file() -> None:
    """Lock: every committed test file parses with zero vacuous asserts."""
    files = tracked_test_files()
    offenders: list[str] = []
    for path in files:
        findings = find_vacuous_asserts(_compile(path))
        offenders.extend(f"{path.relative_to(REPO_ROOT)}: {f}" for f in findings)
    assert not offenders, "\n".join(offenders)


class TestScannerNonVacuity:
    """Every matcher must fire on its own positive control, and not fire on
    a sane assert - the lock itself would otherwise pass vacuously."""

    def _from_source(self, source: str) -> ast.AST:
        return ast.parse(source)

    def test_positive_control_every_shape_detected(self) -> None:
        sources = [
            "def f():\n    assert a or True\n",  # bool or-literal
            "def f():\n    assert a and False\n",  # bool and-literal
            "def f():\n    assert (1, 2)\n",  # tuple literal
            "def f():\n    assert a if False else b\n",  # constant IfExp
        ]
        total = 0
        for source in sources:
            found = find_vacuous_asserts(self._from_source(source))
            assert found, f"matcher missed: {source!r}"
            total += len(found)
        assert total >= 4, total

    def test_negative_control_sane_asserts_pass(self) -> None:
        sources = [
            "def f():\n    assert a\n",
            "def f():\n    assert a or b\n",
            "def f():\n    assert a, 'message'\n",
            "def f():\n    assert (a in b), 'membership assert'\n",
            "def f():\n    assert a if b else c  # non-constant IfExp\n",
        ]
        for source in sources:
            assert find_vacuous_asserts(self._from_source(source)) == []

    def test_scanner_runs_over_a_real_file_not_a_stub(self) -> None:
        """Non-vacuity: the lock genuinely reads tracked files - prove one
        real file's parse yields produced a source tree, not {'module': [].}"""
        files = tracked_test_files()
        assert files, "no tracked test files"
        tree = _compile(files[-1])
        assert isinstance(tree, ast.Module)
        sample = find_vacuous_asserts(tree)
        assert isinstance(sample, list)
