"""Committed lock counts for the instruction locks the CI runner checks.

A passing run proves the locks executed; it does not prove there are as many of
them as before.  The workflow that verifies the instruction locks on a runner
with no user-global baseline therefore also compares each module's collected
count against a number, and that number must not be typed into YAML: a literal
there can only be maintained by hand, a typo in it fails the step for the wrong
reason, and nothing in the suite can see it.

``tests/data/lock_counts.json`` is that artifact, generated from a passing run
(``--write``, which refuses unless the modules pass first) and read by two
callers - the CI step and ``tests/test_lock_counts.py`` - so the runner and the
suite make the same claim from one source instead of drifting apart.

A recorded number is a floor and a staleness cap.  A module may grow by up to a
fifth without an edit, because ordinary additions should not require one;
beyond that the number is stale and is regenerated deliberately.  Falling below
the floor is the case that matters: a lock file that quietly loses tests is
verification shrinking, and a doubled count is the shape that hides a
parametrization bug or another module's tests leaking in.

The inventory is also the list of modules the step checks, so registering a new
lock module is ``--module`` on a ``--write`` run rather than a line anybody
could mistype.

To regenerate after a deliberate change, and to create or extend the file::

    python -m tests.lock_counts --write
    python -m tests.lock_counts --write --module test_new_locks.py

Changed in 1.1.0: initial version.
Changed in 1.2.0: added with the CI instruction-lock step, replacing the counts
the workflow used to declare by hand.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The generated inventory of lock counts (see the module docstring).
INVENTORY = REPO_ROOT / "tests" / "data" / "lock_counts.json"

#: A module may sit at most this fraction above its recorded count before the
#: count is stale: ``cap_for(21) == 26``, ``cap_for(43) == 52``.
GROWTH_DENOMINATOR = 5

#: Keys the inventory may carry.  An unknown key is a typo or a file left by an
#: older schema, and both would silently change what the check means.
_KNOWN_KEYS = frozenset({"_comment", "_generated", "modules"})

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

#: The step runs modules directly under ``tests/``; a path would escape the
#: directory the CI step names and a non-test name would collect nothing.
_MODULE = re.compile(r"test_[A-Za-z0-9_]+\.py\Z")

#: One collected node id per line, as ``--collect-only -q`` prints them.
_COLLECTED = re.compile(r"^tests/[^ \n]+\.py::", re.MULTILINE)

_COMMENT = (
    "Collected lock counts for the modules the CI instruction-lock step checks, "
    "generated from a passing run - do not edit by hand, run "
    "`python -m tests.lock_counts --write` after a deliberate change."
)


class LockCountError(Exception):
    """The inventory is missing or malformed, or a collection could not run.

    Raised rather than warned: a count file that quietly parses to something
    weaker than it says turns the check built on it into one that cannot fail.
    """


@dataclass(frozen=True)
class LockCounts:
    """The committed inventory (see the module docstring).

    Attributes:
        path: The JSON file itself - named in messages, so a failure says which
            file to regenerate.
        comment: The inventory's own explanation of why it exists.
        generated: ISO date of the passing run that produced the counts.
        modules: Module file name (under ``tests/``) to recorded count.
    """

    path: Path
    comment: str
    generated: str
    modules: Mapping[str, int]


def _require(condition: bool, path: Path, problem: str) -> None:
    """Raise ``LockCountError`` naming ``path`` unless ``condition`` holds."""
    if not condition:
        raise LockCountError(f"{path}: {problem}")


def load_inventory(path: Path | None = None) -> LockCounts:
    """Read the inventory, refusing anything weaker than it claims to be.

    Args:
        path: The inventory to read; defaults to ``INVENTORY``.

    Returns:
        The loaded inventory.

    Raises:
        LockCountError: if the file is missing, not an object, carries an
            unknown key, has a ``modules`` value that is not a ``tests/test_*``
            name, or a count that is not a positive integer.
    """
    source = INVENTORY if path is None else path
    _require(source.is_file(), source, "inventory does not exist")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LockCountError(f"{source}: not valid JSON ({exc})") from exc
    _require(isinstance(payload, dict), source, "top level must be an object")

    unknown = sorted(set(payload) - _KNOWN_KEYS)
    _require(not unknown, source, f"unknown keys: {', '.join(unknown)}")

    comment = payload.get("_comment")
    _require(
        isinstance(comment, str) and bool(comment.strip()),
        source,
        "missing `_comment` explaining the file",
    )
    generated = payload.get("_generated")
    _require(
        isinstance(generated, str) and bool(_ISO_DATE.match(generated)),
        source,
        "`_generated` must be an ISO date (YYYY-MM-DD)",
    )

    raw_modules = payload.get("modules")
    _require(
        isinstance(raw_modules, dict) and bool(raw_modules),
        source,
        "`modules` must be a non-empty object",
    )
    modules: dict[str, int] = {}
    for name, count in raw_modules.items():
        _require(
            isinstance(name, str) and bool(_MODULE.match(name)),
            source,
            f"{name!r} is not a tests/test_*.py module name",
        )
        # bool is an int subclass, and `True` here would count as one lock.
        _require(
            isinstance(count, int) and not isinstance(count, bool) and count > 0,
            source,
            f"{name}: count must be a positive integer, got {count!r}",
        )
        modules[name] = count
    return LockCounts(
        path=source, comment=comment, generated=generated, modules=modules
    )


def cap_for(floor: int) -> int:
    """Return the count above which a recorded number counts as stale.

    Args:
        floor: The recorded count (the lower bound).

    Returns:
        The upper bound: ``floor`` plus one fifth, rounded up, so a small
        module still tolerates a lock or two of growth.
    """
    return floor + (floor + GROWTH_DENOMINATOR - 1) // GROWTH_DENOMINATOR


def _run_pytest(
    modules: Sequence[str],
    *,
    root: Path,
    python: str,
    collect_only: bool,
) -> subprocess.CompletedProcess[str]:
    """Run ``pytest`` over ``modules`` and return the completed process.

    Args:
        modules: Module file names under ``root/tests``.
        root: Directory holding the ``tests`` package.
        python: Interpreter to run.
        collect_only: Whether to collect instead of executing the tests.
    """
    command = [python, "-m", "pytest", *(f"tests/{name}" for name in modules)]
    if collect_only:
        command += ["--collect-only", "-q", "-p", "no:cacheprovider", "--no-cov"]
    else:
        command += ["--tb=short", "-q", "-p", "no:cacheprovider", "--no-cov"]
    try:
        return subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except OSError as exc:  # interpreter cannot be executed at all
        raise LockCountError(f"cannot run {python}: {exc}") from exc


def collect_counts(
    modules: Sequence[str],
    *,
    root: Path = REPO_ROOT,
    python: str | None = None,
) -> dict[str, int]:
    """Return how many tests each module collects.

    Args:
        modules: Module file names under ``root/tests``.
        root: Directory holding the ``tests`` package.
        python: Interpreter to run; defaults to the current one.

    Returns:
        Module name to collected count, in the order given.

    Raises:
        LockCountError: if the collection run fails - a module that no longer
            exists reports that, rather than passing as "collected zero".
    """
    interpreter = sys.executable if python is None else python
    result = _run_pytest(modules, root=root, python=interpreter, collect_only=True)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-8:]
        raise LockCountError(
            "cannot collect "
            + ", ".join(f"tests/{name}" for name in modules)
            + f" (pytest exit {result.returncode}):\n  "
            + "\n  ".join(tail)
        )
    found = _COLLECTED.findall(result.stdout)
    counts = {name: 0 for name in modules}
    for node_id in found:
        module = node_id.split("::", 1)[0].removeprefix("tests/")
        if module in counts:
            counts[module] += 1
    return counts


def ensure_passing(
    modules: Sequence[str],
    *,
    root: Path = REPO_ROOT,
    python: str | None = None,
) -> None:
    """Refuse to record counts unless the modules pass first.

    A count taken from a failing tree freezes the numbers a broken lock file
    happens to report, which is the opposite of what the inventory is for.

    Args:
        modules: Module file names under ``root/tests``.
        root: Directory holding the ``tests`` package.
        python: Interpreter to run; defaults to the current one.

    Raises:
        LockCountError: if the run fails, naming the failing summary.
    """
    interpreter = sys.executable if python is None else python
    result = _run_pytest(modules, root=root, python=interpreter, collect_only=False)
    if result.returncode != 0:
        tail = (result.stdout + result.stderr).strip().splitlines()[-8:]
        raise LockCountError(
            "refusing to record counts from a failing run:\n  " + "\n  ".join(tail)
        )


def violations(observed: Mapping[str, int], expected: Mapping[str, int]) -> list[str]:
    """Return one message per count outside its recorded band.

    Args:
        observed: What the modules collected.
        expected: What the inventory records.

    Returns:
        Empty when every module sits between its floor and its cap.
    """
    problems: list[str] = []
    for module, floor in expected.items():
        if module not in observed:
            problems.append(f"{module}: not collected at all")
            continue
        got = observed[module]
        cap = cap_for(floor)
        if got < floor:
            problems.append(f"{module}: collected {got}, below its floor of {floor}")
        elif got > cap:
            problems.append(
                f"{module}: collected {got}, past its cap of {cap} "
                f"(recorded {floor}; regenerate after intended growth)"
            )
    return problems


def serialize_inventory(
    counts: Mapping[str, int],
    *,
    generated: str,
    comment: str = _COMMENT,
) -> bytes:
    """Return ``counts`` as JSON bytes: UTF-8, no BOM, CRLF, trailing newline.

    One shape for the file, written here so a Windows editor cannot flip its
    line endings and turn a one-line regeneration into a whole-file rewrite.
    """
    payload: dict[str, Any] = {
        "_comment": comment,
        "_generated": generated,
        "modules": {module: counts[module] for module in sorted(counts)},
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def write_inventory(
    counts: Mapping[str, int],
    *,
    path: Path | None = None,
    generated: str | None = None,
) -> bytes:
    """Write the inventory and return the bytes written.

    Args:
        counts: Module name to collected count, as ``collect_counts`` returns.
        path: Where to write; defaults to ``INVENTORY``.
        generated: ISO date to record; defaults to today.

    Returns:
        The exact bytes written, so a caller can assert on them.
    """
    destination = INVENTORY if path is None else path
    payload = serialize_inventory(
        counts, generated=date.today().isoformat() if generated is None else generated
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return payload


def _check(expected: LockCounts, *, root: Path, python: str | None) -> int:
    """Compare the live collection with the inventory and report it."""
    observed = collect_counts(list(expected.modules), root=root, python=python)
    for module, floor in expected.modules.items():
        print(
            f"{module}: {observed[module]} collected, floor {floor}, "
            f"cap {cap_for(floor)}"
        )
    problems = violations(observed, expected.modules)
    for problem in problems:
        print(f"gate fail: {problem}", file=sys.stderr)
    return 1 if problems else 0


def _write(modules: Sequence[str], *, path: Path, python: str | None) -> int:
    """Regenerate the inventory from a passing run."""
    ensure_passing(modules, python=python)
    observed = collect_counts(modules, python=python)
    write_inventory(observed, path=path)
    for module, count in observed.items():
        print(f"{module}: {count}")
    print(f"wrote {path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``--check`` or ``--write`` action from the command line.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status: 0 when the counts are in band or were written, 1
        when they are not or the action could not run.
    """
    parser = argparse.ArgumentParser(
        prog="python -m tests.lock_counts",
        description="Check or regenerate the instruction-lock count inventory.",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument(
        "--check", action="store_true", help="compare live counts with the file"
    )
    action.add_argument(
        "--write", action="store_true", help="regenerate the file from a passing run"
    )
    parser.add_argument(
        "--inventory", type=Path, default=INVENTORY, help="inventory to read/write"
    )
    parser.add_argument(
        "--module",
        action="append",
        default=[],
        metavar="tests/test_*.py",
        help="lock module to register (repeatable; use with --write)",
    )
    args = parser.parse_args(argv)

    try:
        expected = load_inventory(args.inventory) if args.inventory.is_file() else None
        if args.write:
            registered = list(expected.modules) if expected is not None else []
            modules = list(dict.fromkeys([*registered, *args.module]))
            if not modules:
                raise LockCountError(
                    f"{args.inventory}: no modules to record; pass --module"
                )
            return _write(modules, path=args.inventory, python=None)
        if expected is None:
            raise LockCountError(
                f"{args.inventory}: inventory does not exist; create it with "
                "--write --module tests/test_*.py"
            )
        return _check(expected, root=REPO_ROOT, python=None)
    except LockCountError as exc:
        print(f"gate fail: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
