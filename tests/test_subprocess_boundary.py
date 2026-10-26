"""Policy lock: no shipped module spawns a process outside the wrapper.

``SECURITY.md`` states that every first-party subprocess invocation goes
through ``audio_suite_shared.secure_subprocess`` (executable allowlist, no
shell). Two packages drifted from that — the Audio Enhancer's ffmpeg I/O and
the CD Ripper's results tab, the latter building a PowerShell command string —
and bandit grades those raw calls Low, so the gate accepted them and nothing
reported the drift (audit R-08, plan C3).

This scan is the lock: it parses every shipped runtime module, reports any
``subprocess.run``/``Popen``/``call``/``check_output``/``getoutput``/
``getstatusoutput`` reference (including the ``from subprocess import run``
form), and allows exactly one file — the wrapper itself.

Changed in 2.1.4: new lock for the subprocess boundary (plan C3).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The one runtime module allowed to spawn a process: the wrapper itself.
WRAPPER = "audio_suite_shared/secure_subprocess.py"

#: Directory names that are not the shipped runtime.
#:
#: ``utilities`` is the developer scripts (release cut, docs builds,
#: benchmarks, restorers). They invoke ``uv``/``git``/``pytest`` against the
#: checkout, never run on user audio, and must not drag those tools into the
#: product's executable allowlist. ``plugins`` is extension code, whose
#: subprocess use belongs to the plugin author's own review.
SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "docs",
        "plugins",
        "tests",
        "utilities",
    }
)

#: The spawning entry points of the ``subprocess`` module.
SPAWNING_NAMES = frozenset(
    {"run", "Popen", "call", "check_call", "check_output", "getoutput"}
)


def _runtime_modules() -> list[Path]:
    """Return every shipped runtime module under the repository root.

    Returns:
        Sorted ``.py`` paths outside :data:`SKIPPED_DIRS`.
    """
    modules: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT)
        if SKIPPED_DIRS.intersection(relative.parts[:-1]):
            continue
        modules.append(path)
    return modules


def _direct_spawns(source: str, label: str) -> list[str]:
    """Return ``label:line`` for every direct spawn in *source*.

    Both spellings count: ``subprocess.run(...)`` and a ``run(...)`` imported
    with ``from subprocess import run``.  Constants such as ``subprocess.PIPE``
    and exception types are not spawns and are ignored.

    Args:
        source: Python source text to parse.
        label:  Name used in the returned locations.

    Returns:
        One ``label:line`` string per direct spawn, in source order.
    """
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            imported.update(
                alias.name for alias in node.names if alias.name in SPAWNING_NAMES
            )

    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in SPAWNING_NAMES
            and isinstance(func.value, ast.Name)
            and func.value.id == "subprocess"
        ):
            found.append(f"{label}:{node.lineno}")
        elif isinstance(func, ast.Name) and func.id in imported:
            found.append(f"{label}:{node.lineno}")
    return sorted(found)


class TestScanner:
    """The detector itself, so an empty scan cannot pass forever."""

    def test_flags_the_attribute_form(self) -> None:
        found = _direct_spawns("import subprocess\nsubprocess.run(['x'])\n", "bad")
        assert found == ["bad:2"]

    def test_flags_the_imported_name_form(self) -> None:
        found = _direct_spawns("from subprocess import run as spawn\n", "importer")
        assert found == []
        found = _direct_spawns("from subprocess import run\nrun(['x'])\n", "importer")
        assert found == ["importer:2"]

    def test_ignores_constants_and_exception_types(self) -> None:
        source = (
            "import subprocess\n"
            "print(subprocess.PIPE, subprocess.DEVNULL)\n"
            "try:\n"
            "    pass\n"
            "except subprocess.CalledProcessError:\n"
            "    pass\n"
        )
        assert _direct_spawns(source, "ok") == []


class TestBoundary:
    def test_the_scan_sees_the_runtime(self) -> None:
        """A scan that found nothing would satisfy the lock vacuously."""
        modules = _runtime_modules()
        assert len(modules) > 100
        names = {path.relative_to(REPO_ROOT).as_posix() for path in modules}
        assert WRAPPER in names
        assert not any(name.startswith("utilities/") for name in names)

    def test_only_the_wrapper_spawns(self) -> None:
        offenders: list[str] = []
        for path in _runtime_modules():
            relative = path.relative_to(REPO_ROOT).as_posix()
            source = path.read_text(encoding="utf-8")
            offenders.extend(_direct_spawns(source, relative))
        allowed = [hit for hit in offenders if hit.split(":", 1)[0] == WRAPPER]
        unexpected = [hit for hit in offenders if hit not in allowed]
        assert unexpected == [], (
            "these call subprocess directly; use "
            "audio_suite_shared.secure_subprocess.run_secure_subprocess "
            "instead: " + ", ".join(unexpected)
        )

    def test_the_wrapper_itself_is_scanned(self) -> None:
        """The allowed file must still be visible to the detector."""
        source = (REPO_ROOT / WRAPPER).read_text(encoding="utf-8")
        assert _direct_spawns(source, WRAPPER)
