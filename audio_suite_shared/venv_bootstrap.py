"""
venv_bootstrap.py — run a launcher from the project's ``.venv`` when it exists.

The ``*.pyw`` launchers are started by whichever interpreter Windows associates
with the extension, which is the system Python.  Extras are installed the way
this repository documents them (``uv sync --extra ml``), which puts them in
``<root>/.venv`` — so a double-clicked launcher does not see them.  The tool
then either reports the extra as missing although it is installed, or installs
a second copy into the system interpreter.

Each launcher therefore calls :func:`ensure_venv_interpreter` with its own
directory before it imports anything else.  When ``<root>/.venv`` holds an
interpreter and this process is not already running under it, the launcher is
re-executed — same script, same arguments — under that interpreter.  ``os.execv``
*replaces* the process, so the second launch is the only one that runs: no
parent process lingers and the window's lifetime is unchanged.

Nothing happens when there is no ``.venv`` (a plain ``pip install`` into the
system interpreter keeps working), when the venv's interpreter is already the
one running (``uv run``, a venv prompt, a re-executed launch), inside a pytest
run (which executes two launchers in-process), or in a frozen build.  A failing
``exec`` is logged and the current interpreter continues, so a broken venv
produces the normal import error instead of a launcher that silently does
nothing.

Changed in 2.1.0: initial version.
Changed in 2.1.6: ``ensure_venv_interpreter`` takes the same ``platform``
override ``find_venv_interpreter`` already had, so the two re-exec tests - whose
argv, executable and ``.venv/Scripts`` fixture are all Windows-shaped - run and
assert on a POSIX host instead of quietly returning early. Before it, the POSIX
smoke leg found them failing because the POSIX branch looked for
``.venv/bin/python`` and found none (R-12,
PLAN_audit_2026-10-24_deferred_p2p3.md).
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Marks a process that is already the re-executed launch.  It makes the loop
#: impossible even if the venv's interpreter reports an unexpected
#: ``sys.prefix`` (a half-created or relocated venv): one re-exec, never two.
ENV_SENTINEL = "AUDIOSUITE_VENV_REEXEC"

#: Directory inside the venv that holds the interpreters, per platform.
_WINDOWS_BIN_DIR = "Scripts"
_POSIX_BIN_DIR = "bin"


def _is_under(path: Path, parent: Path) -> bool:
    """Return True when *path* is *parent* or sits below it (lexically)."""
    candidate = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(parent))
    return candidate == root or candidate.startswith(root + os.sep)


def find_venv_interpreter(
    root: str | os.PathLike[str],
    *,
    executable: str | None = None,
    platform: str | None = None,
) -> Path | None:
    """Return the interpreter inside ``<root>/.venv``, or None without one.

    The candidate keeps the *window mode* of the interpreter that is asking:
    a launcher started by ``pythonw.exe`` re-executes under the venv's
    ``pythonw.exe`` so the console stays hidden, while a command-line launch
    uses ``python.exe``.  If the preferred name is absent the other one is
    used, because a venv may carry only one of them.

    Args:
        root: The suite root, i.e. the directory containing ``.venv``.
        executable: Interpreter currently running; defaults to
            ``sys.executable``.
        platform: Value to read instead of ``sys.platform`` (tests only).

    Returns:
        Path to the venv interpreter, or None when there is no usable one.
    """
    venv = Path(root) / ".venv"
    if not venv.is_dir():
        return None

    current = Path(executable or sys.executable).name.lower()
    if (platform or sys.platform).startswith("win"):
        names = (
            ("pythonw.exe", "python.exe")
            if "pythonw" in current
            else ("python.exe", "pythonw.exe")
        )
        bin_dir = venv / _WINDOWS_BIN_DIR
    else:
        names = ("python", "python3")
        bin_dir = venv / _POSIX_BIN_DIR

    for name in names:
        candidate = bin_dir / name
        if candidate.is_file():
            return candidate
    return None


def under_test(environ: Mapping[str, str] | None = None) -> bool:
    """Return True when a pytest run is executing this code.

    pytest imports two launchers and executes them in-process
    (``tests/test_pyw_launchers.py``); re-executing them would replace the test
    process with a GUI.  Two signals are checked — the imported ``pytest``
    module and ``PYTEST_CURRENT_TEST``, which pytest sets for the duration of
    every test — so neither an embedded run nor an exec'd launcher slips
    through.

    Args:
        environ: Environment to read instead of ``os.environ`` (tests only).
    """
    env = os.environ if environ is None else environ
    return "pytest" in sys.modules or bool(env.get("PYTEST_CURRENT_TEST"))


def ensure_venv_interpreter(
    root: str | os.PathLike[str],
    *,
    argv: Sequence[str] | None = None,
    executable: str | None = None,
    prefix: str | os.PathLike[str] | None = None,
    environ: MutableMapping[str, str] | None = None,
    exec_fn: Callable[[str, list[str]], object] | None = None,
    platform: str | None = None,
) -> Path | None:
    """Re-execute the launcher under ``<root>/.venv`` when that is not already
    the running interpreter.

    Call this first thing in a launcher, with the launcher's own directory.
    On success the call does not return: the process image is replaced.

    Args:
        root: The suite root, i.e. the directory containing ``.venv``.
        argv: Argument vector to forward; defaults to ``sys.argv``.
        executable: Interpreter currently running; defaults to
            ``sys.executable``.
        prefix: The running interpreter's ``sys.prefix`` (the venv directory
            once inside one); defaults to ``sys.prefix``.  Checked with the
            executable path because a POSIX venv's interpreter is a symlink
            back to the system Python, so its resolved path is not the answer.
        environ: Environment to read and mark; defaults to ``os.environ``.
        exec_fn: Test seam, called as ``exec_fn(path, argv)``; defaults to
            ``os.execv``.
        platform: Value to read instead of ``sys.platform`` (tests only), so a
            Windows-shaped launch can be verified on any host.

    Returns:
        The interpreter a re-exec was started with (only reachable through the
        ``exec_fn`` seam — a real ``exec`` replaces the process), or None when
        the current interpreter is the right one to continue in.
    """
    env = os.environ if environ is None else environ
    if env.get(ENV_SENTINEL) or getattr(sys, "frozen", False) or under_test(env):
        return None

    current = Path(executable or sys.executable)
    target = find_venv_interpreter(root, executable=str(current), platform=platform)
    if target is None:
        return None

    venv = Path(root) / ".venv"
    running_prefix = Path(prefix if prefix is not None else sys.prefix)
    if _is_under(current, venv) or _is_under(running_prefix, venv):
        return None

    arguments = list(sys.argv if argv is None else argv)
    if not arguments:
        # Nothing to hand the venv interpreter: a re-exec would start an
        # interactive session instead of the tool.
        return None

    env[ENV_SENTINEL] = "1"
    try:
        (exec_fn or os.execv)(str(target), [str(target), *arguments])
    except OSError as exc:
        # Keep the launch alive: the import that follows reports the real
        # problem (a venv missing a package), which beats a window that closes.
        if env.get(ENV_SENTINEL):
            del env[ENV_SENTINEL]
        logger.warning("Could not re-run under %s: %s", target, exc)
        return None
    return target
