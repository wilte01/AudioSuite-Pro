#!/usr/bin/env python3
"""docstring_report.py

Report public definitions that have no docstring, with an AST rather than grep.

Usage:
    python utilities/docstring_report.py
    python utilities/docstring_report.py --path audio_suite_shared --path master_driver
    python utilities/docstring_report.py --path audio_suite_shared --json

Why this exists
---------------
PLAN D98 bounded the documentation work to the shared package's public API and
the two largest model modules instead of all 193 gaps a grep found: a report is
only actionable when its scope is one a change can close.  This tool is the
audit, and ``tests/test_docstring_coverage.py`` is the lock that keeps the
scoped set closed.

Scope
-----
A *public definition* is:

* the module docstring itself;
* a top-level function or class whose name does not start with an underscore; or
* a method whose name does not start with an underscore, in a top-level class
  whose own name does not start with an underscore.

Two exclusions, both stated rather than silent.  A **property setter** is not
counted (`@thing.setter`): it exists to write the value its getter documenta-
tion already describes, so counting it would demand the same sentence twice.
A **nested helper** is not counted either - a function defined inside another
function is not reachable from outside it.

Exit status: 0 when every scanned definition is documented, 1 when any is not,
2 on unreadable input.

Changed in 1.4.1: methods of public classes join the scan, with property
setters excluded and documented (PLAN D98).
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: What this report calls a public definition, for its own output and the lock.
PUBLIC_KINDS = ("module", "class", "function", "method")

#: The node types that can carry a docstring, so ``get_docstring`` is typed.
Documented = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class Gap:
    """One public definition with no docstring.

    Attributes:
        path: File the definition lives in.
        line: 1-based line of the definition (1 for a module docstring).
        kind: ``module``, ``class`` or ``function``.
        name: The definition's name.
    """

    path: str
    line: int
    kind: str
    name: str


def scanned_files(paths: Sequence[Path]) -> list[Path]:
    """Return every ``.py`` file under *paths* (a file or a directory).

    Args:
        paths: Files or directories to walk.

    Returns:
        Sorted Python files, excluding ``tests`` directories and the caches a
        run leaves behind - a test module's helpers are not public API.

    Raises:
        FileNotFoundError: If a requested path does not exist, so a typo is an
            error rather than an empty, passing scan.
    """
    found: set[Path] = set()
    for root in paths:
        if not root.exists():
            raise FileNotFoundError(f"no such path: {root}")
        if root.is_file():
            if root.suffix == ".py":
                found.add(root)
            continue
        for path in root.rglob("*.py"):
            parts = path.parts
            if "tests" in parts or "__pycache__" in parts:
                continue
            found.add(path)
    return sorted(found)


def _is_setter(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when *node* is a property setter (``@x.setter``)."""
    return any(
        isinstance(decorator, ast.Attribute) and decorator.attr == "setter"
        for decorator in node.decorator_list
    )


def _public_members(
    node: ast.ClassDef,
) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Return the public, non-setter methods declared directly in *node*."""
    return [
        member
        for member in node.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not member.name.startswith("_")
        and not _is_setter(member)
    ]


def _definitions(
    tree: ast.Module,
) -> list[tuple[str, int, str, Documented]]:
    """Return ``(name, line, kind, node)`` for every public definition.

    ``name`` is dotted for a method (``Class.method``), so a gap names the
    class it belongs to.  Only directly declared members are visited: an
    inherited or nested definition is documented where it is declared.
    """
    found: list[tuple[str, int, str, Documented]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name.startswith("_"):
            continue
        kind = "class" if isinstance(node, ast.ClassDef) else "function"
        found.append((node.name, node.lineno, kind, node))
        if isinstance(node, ast.ClassDef):
            found.extend(
                (f"{node.name}.{member.name}", member.lineno, "method", member)
                for member in _public_members(node)
            )
    return found


def public_symbols(path: Path) -> list[str]:
    """Return every public definition *path* declares, documented or not.

    Args:
        path: A Python source file.

    Returns:
        The module stem (the module docstring's symbol) followed by each
        public definition, methods as ``Class.method``.  Tests use the count to
        prove the scan found a real surface rather than an empty directory.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [path.stem, *(name for name, _, _, _ in _definitions(tree))]


def gaps_in(path: Path) -> list[Gap]:
    """Return the undocumented public definitions in *path*.

    Args:
        path: A Python source file.

    Returns:
        One :class:`Gap` per missing docstring, ordered by line.

    Raises:
        SyntaxError: If the file does not parse; a file this report cannot read
            must not be reported as clean.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    gaps: list[Gap] = []
    if not ast.get_docstring(tree):
        gaps.append(Gap(str(path), 1, "module", path.stem))
    for name, lineno, kind, node in _definitions(tree):
        if ast.get_docstring(node):
            continue
        gaps.append(Gap(str(path), lineno, kind, name))
    return gaps


def report(paths: Sequence[Path]) -> list[Gap]:
    """Return every gap across *paths*, in file order."""
    gaps: list[Gap] = []
    for path in scanned_files(paths):
        gaps.extend(gaps_in(path))
    return gaps


def _display(path: str) -> str:
    """Return *path* relative to the repository when it is inside it."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:  # pragma: no cover - only for paths outside the repo
        return path


def main(argv: Sequence[str] | None = None) -> int:
    """Print the audit and return its exit status.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(
        prog="python utilities/docstring_report.py",
        description="Report public definitions that have no docstring.",
    )
    parser.add_argument(
        "--path",
        action="append",
        type=Path,
        dest="paths",
        help="file or directory to scan (repeatable; default: audio_suite_shared)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the gaps as JSON instead of [MISSING] lines",
    )
    args = parser.parse_args(argv)

    paths = args.paths or [REPO_ROOT / "audio_suite_shared"]
    try:
        files = scanned_files(paths)
        gaps = [gap for path in files for gap in gaps_in(path)]
    except (FileNotFoundError, SyntaxError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    # An empty scan is a broken invocation, not a clean bill of health: the
    # tests lock the real package, and the same guard belongs in the tool.
    if not files:
        print(f"[ERROR] no Python files under {paths}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "scanned_files": len(files),
                    "gaps": [asdict(gap) for gap in gaps],
                },
                indent=2,
            )
        )
    else:
        for gap in gaps:
            print(f"[MISSING] {_display(gap.path)}:{gap.line} {gap.kind} {gap.name}")
        print(f"[INFO] scanned {len(files)} file(s), {len(gaps)} missing docstring(s)")
    if gaps:
        print(
            "[ERROR] public definitions without a docstring: "
            f"{len(gaps)}; add one or scope the path with --path",
            file=sys.stderr,
        )
        return 1
    print("[OK] every scanned public definition is documented")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
