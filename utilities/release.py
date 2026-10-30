#!/usr/bin/env python3
"""release.py

Cut one suite release with a single idempotent command: bump the version,
re-lock, rotate the changelog, regenerate the version-labelled user guides,
prove the regenerated guides differ only in their text, then run the full gate.

Usage:
    python utilities/release.py 1.4.0
    python utilities/release.py 1.4.0 --date 2026-11-02 --dry-run
    python utilities/release.py 1.4.0 --skip-gate

Why a script instead of a checklist
-----------------------------------

The 1.2.0 and 1.3.0 cuts each had to do the same six things by hand, and each
one is easy to do half-way: bump `pyproject.toml` but forget `uv.lock`, rotate
the changelog but leave `[Unreleased]` blank, or regenerate a guide and commit
a LibreOffice re-save that silently rewrote `docProps/app.xml`. Every step here
is therefore both *checked* and *skipped when already done*:

* the version is read from `[project] version` (never a second constant);
* `uv lock --check` decides whether a lock is needed at all, and the new
  version is then read back out of `uv.lock` rather than assumed;
* the changelog promotion is driven by the real `[Unreleased]` body and refuses
  to "release" an empty one — for `CHANGELOG.md`, the user-facing history. The
  developer-facing `TECHNICAL_CHANGELOG.md` beside it is promoted in the same
  cut and legitimately holds nothing for a release with no developer-facing
  change;
* a guide is regenerated only when its subtitle does not already name the new
  version, and the regenerated `.docx` is compared zip-entry by zip-entry with
  the file it replaces - a change to anything but `word/document.xml` is
  external-tool drift (`docProps/app.xml`, a dropped `thumbnail.jpeg`), not this
  release, and fails the run;
* the gate is the project's own six commands, with bandit's severity block
  parsed because its exit code only says "some finding survived".

Idempotency is the contract, not a side effect: re-running the same version
after a success must report `[SKIP]` for every mutation and leave every byte
where it was, so a release cut can be retried after a transient failure
without producing a second commit's worth of noise.

Changed in 1.3.0: new module - the scripted release cut the 1.3.0 hand-run
proved out (bump, lock, changelog, guide regeneration plus zip-entry diff, and
the gate in one idempotent command).
Changed in 1.4.1: refreshes the editable install's metadata before the gate, so
a cut no longer fails `doctor`'s healthy-install tests on its own version bump
(PLAN D106).
Changed in 2.1.0: guides are rebuilt through the shared Markdown renderer
(``utilities/build_user_guides.py <tool>``) instead of each tool's retired
``generate_guide.py`` (PLAN_docs_consolidation P2.4). The version-subtitle and
zip-entry checks are unchanged - they still judge the artefact a user opens.
Changed in 2.1.6: the import block is re-sorted against the corrected ruff
target py311 — ``tomllib`` is 3.11 standard library
(R-15, PLAN_audit_2026-10-24_deferred_p2p3.md).

Changed in 2.1.7: the version-labelled guide scan reads
``documentation/user_guides/individual_programs/``.

Changed in 2.2.1: a cut promotes both change-history files (functional backlog
U2). ``CHANGELOG.md`` still must hold an entry; ``TECHNICAL_CHANGELOG.md`` is
optional, so a release with no developer-facing change adds no heading there
instead of failing the cut.

Changed in 2.2.0: the gate's progress survives a redirected stdout. A cut is
normally run from a background shell into a log, where Python block-buffers, so
the 2.1.7 run looked stalled at 14% for most of its 21 minutes and its steps'
lines surfaced after the output they announced. Every progress line is now
flushed and every gate child runs with ``PYTHONUNBUFFERED=1``;
``TestTheGateStreamsItsProgress`` pins both halves, including that a step's
marker is on disk *before* that step finishes.

"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

#: The only zip entry a version-only guide regeneration may touch.
GUIDE_TEXT_ENTRY = "word/document.xml"

#: Every guide subtitle opens with this literal (AGENTS / plan D15 shape).
VERSION_LABEL_PREFIX = "Version "

#: Separator between the version and the generation month in a subtitle.
VERSION_LABEL_SEPARATOR = " \u2014 "

#: The changelog's not-yet-versioned heading.
UNRELEASED_HEADING = "## [Unreleased]"

#: Phrases that declare an intentionally empty `[Unreleased]` section.
_EMPTY_PHRASES: tuple[str, ...] = (
    "nothing yet",
    "nothing to record",
    "no changes yet",
    "_nothing recorded_",
)

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(RuntimeError):
    """A release step cannot proceed without a human decision."""


# ---------------------------------------------------------------------------
# Version bump
# ---------------------------------------------------------------------------


def declared_version(pyproject_text: str) -> str | None:
    """Return ``[project] version`` from ``pyproject.toml`` source.

    Args:
        pyproject_text: The full contents of a ``pyproject.toml``.

    Returns:
        The declared version, or ``None`` when the table or key is absent.

    Raises:
        tomllib.TOMLDecodeError: If the text is not valid TOML.
    """
    project: Any = tomllib.loads(pyproject_text).get("project")
    if not isinstance(project, dict):
        return None
    version: Any = project.get("version")
    return version if isinstance(version, str) else None


def _eol(line: str) -> str:
    """Return the line ending *line* already uses."""
    return "\r\n" if line.endswith("\r\n") else "\n"


def bump_project_version(text: str, new_version: str) -> tuple[str, str | None]:
    """Set ``[project] version`` to *new_version*, adding the release note.

    The version line and the header comment block keep the line endings they
    already had, so a CRLF checkout is not rewritten as LF (AGENTS
    byte-level safety).

    Args:
        text: The current ``pyproject.toml`` source.
        new_version: The version to declare, e.g. ``"1.4.0"``.

    Returns:
        ``(new_text, old_version)``. When the file already declares
        *new_version* the text is returned unchanged and ``old_version`` is
        ``None``, which is what makes a repeated run a no-op.

    Raises:
        ReleaseError: If ``[project] version`` cannot be found.
    """
    old = declared_version(text)
    if old is None:
        raise ReleaseError("pyproject.toml has no [project] version")
    if old == new_version:
        return text, None

    lines = text.splitlines(keepends=True)
    section = next(
        (i for i, line in enumerate(lines) if line.strip() == "[project]"), None
    )
    if section is None:
        raise ReleaseError("pyproject.toml has no [project] table")
    version_at = next(
        (i for i in range(section + 1, len(lines)) if lines[i].startswith("version =")),
        None,
    )
    if version_at is None:
        raise ReleaseError("the [project] table has no version key")

    lines[version_at] = f'version = "{new_version}"{_eol(lines[version_at])}'

    marker = f"bumped [project] version {old} -> {new_version}"
    if marker not in text:
        header = [i for i, line in enumerate(lines) if line.startswith("#")]
        if not header:
            raise ReleaseError("pyproject.toml has no header comment block")
        insert_at = header[-1] + 1
        eol = _eol(lines[insert_at - 1])
        lines[insert_at:insert_at] = [
            f"# Changed in {new_version}: {marker}{eol}",
            f"# (release cut by utilities/release.py).{eol}",
        ]

    return "".join(lines), old


# ---------------------------------------------------------------------------
# Changelog rotation
# ---------------------------------------------------------------------------


def _section_end(lines: list[str], start: int) -> int:
    """Return the index of the next ``## `` heading after *start*.

    Raises:
        ReleaseError: If no later heading exists, which would make the
            extraction run to the end of the file instead of a section.
    """
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            return index
    raise ReleaseError(f"{UNRELEASED_HEADING!r} is not followed by a version heading")


#: The change history is two files (functional backlog U2): the user-facing
#: ``CHANGELOG.md`` and the developer-facing ``TECHNICAL_CHANGELOG.md`` beside
#: it. The flag is whether a cut must find an entry there.
CHANGELOG_FILES: tuple[tuple[str, bool], ...] = (
    ("CHANGELOG.md", True),
    ("TECHNICAL_CHANGELOG.md", False),
)


def _trim_blank(lines: list[str]) -> list[str]:
    """Drop leading and trailing blank lines."""
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _is_meaningful(body: list[str]) -> bool:
    """Whether a section body carries at least one changelog entry."""
    return any(line.lstrip().startswith(("- ", "* ")) for line in body)


def promote_changelog(
    text: str, version: str, date: str, *, require_entries: bool = True
) -> tuple[str, bool]:
    """Promote ``[Unreleased]`` to a dated version section and reopen it.

    Args:
        text: The current change-history source.
        version: The version being released, e.g. ``"1.4.0"``.
        date: The release date as ``YYYY-MM-DD``.
        require_entries: Whether the ``[Unreleased]`` section must hold at
            least one bullet. ``CHANGELOG.md`` requires one - a release with
            nothing for a user is not a release - while
            ``TECHNICAL_CHANGELOG.md`` does not: a release with no
            developer-facing change is normal, and it leaves that file without
            a heading for this version rather than an empty one.

    Returns:
        ``(new_text, changed)``. A changelog that already carries the version
        heading and a populated ``[Unreleased]`` placeholder is returned
        unchanged with ``changed`` false, as is an optional file whose
        ``[Unreleased]`` section holds nothing to promote.

    Raises:
        ReleaseError: If the ``[Unreleased]`` heading is missing, if it has no
            following version heading, or if it holds no entries to release
            and *require_entries* is set.
    """
    lines = text.splitlines(keepends=True)
    heading = f"## [{version}]"
    released = any(line.startswith(heading) for line in lines)
    unreleased_at = next(
        (i for i, line in enumerate(lines) if line.strip() == UNRELEASED_HEADING),
        None,
    )

    if released:
        if unreleased_at is None:
            raise ReleaseError("the changelog has no [Unreleased] heading")
        end = _section_end(lines, unreleased_at)
        if _trim_blank(lines[unreleased_at + 1 : end]):
            return text, False
        # Insert after the blank run that already follows the heading, rather
        # than straight after it, so the reopened section is not left with a
        # doubled blank line before the previous release heading.
        start = unreleased_at + 1
        while start < end and not lines[start].strip():
            start += 1
        eol = _eol(lines[unreleased_at])
        placeholder = [f"Nothing yet.{eol}", eol]
        lines[start:start] = placeholder
        return "".join(lines), True

    if unreleased_at is None:
        raise ReleaseError("the changelog has no [Unreleased] heading")
    end = _section_end(lines, unreleased_at)
    body = _trim_blank(lines[unreleased_at + 1 : end])
    if not _is_meaningful(body):
        if not require_entries:
            return text, False
        raise ReleaseError(
            "the [Unreleased] section holds no entries - nothing to release"
        )

    eol = _eol(lines[unreleased_at])
    head = [
        f"{UNRELEASED_HEADING}{eol}",
        eol,
        f"Nothing yet.{eol}",
        eol,
        f"## [{version}] - {date}{eol}",
        eol,
        *body,
        eol,
    ]
    return "".join([*lines[:unreleased_at], *head, *lines[end:]]), True


# ---------------------------------------------------------------------------
# User guides
# ---------------------------------------------------------------------------


def _document_paragraphs(path: Path) -> list[str]:
    """Return the paragraph texts of a ``.docx`` file."""
    from docx import Document

    return [paragraph.text.strip() for paragraph in Document(str(path)).paragraphs]


def guide_version_label(path: Path) -> str | None:
    """Return a guide's version subtitle, e.g. ``"Version 1.4.0 — May 2027"``."""
    for text in _document_paragraphs(path):
        if text.startswith(VERSION_LABEL_PREFIX):
            return text
    return None


def version_labelled_guides(root: Path) -> list[Path]:
    """Return every committed guide that displays a version.

    Args:
        root: The repository root.

    Returns:
        Guide paths, sorted.

    Raises:
        ReleaseError: If no guide is found, so the scan can never pass
            vacuously (AGENTS: an empty scan must fail loudly).
    """
    guides = sorted(
        (root / "documentation" / "user_guides" / "individual_programs").glob(
            "*/*_User_Guide.docx"
        )
    )
    labelled = [path for path in guides if guide_version_label(path) is not None]
    if not labelled:
        raise ReleaseError(
            "no user guide carries a version subtitle - the scan would be vacuous"
        )
    return labelled


def entry_data(path: Path) -> dict[str, bytes]:
    """Return a ``.docx``/``.pptx`` container's entries mapped to their bytes."""
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def guide_change_problems(
    guide: Path, before: dict[str, bytes], version: str
) -> list[str]:
    """Check a regenerated guide against the file it replaces.

    Args:
        guide: The regenerated guide.
        before: The replaced file's entries, captured before regeneration.
        version: The release version the subtitle must name.

    Returns:
        Human-readable problems; empty when the change is exactly a version
        subtitle rewrite.
    """
    after = entry_data(guide)
    differing = sorted(
        name for name in set(before) | set(after) if before.get(name) != after.get(name)
    )
    problems: list[str] = []
    if not differing:
        problems.append(
            "regeneration changed no entry - the version label is probably "
            "hardcoded instead of rendered from declared_version()"
        )
    unexpected = [name for name in differing if name != GUIDE_TEXT_ENTRY]
    if unexpected:
        problems.append(
            "entries other than "
            f"{GUIDE_TEXT_ENTRY} changed ({', '.join(unexpected)}) - that is "
            "external-tool drift (a re-save, not a version bump)"
        )
    label = guide_version_label(guide)
    expected = f"{VERSION_LABEL_PREFIX}{version}{VERSION_LABEL_SEPARATOR}"
    if label is None or not label.startswith(expected):
        problems.append(f"subtitle {label!r} does not start with {expected!r}")
    return problems


def regenerate_guide(guide: Path, python: str, root: Path) -> None:
    """Rebuild one guide through the shared Markdown renderer.

    Args:
        guide: The committed guide to rebuild.
        python: The interpreter carrying python-docx.
        root: The repository root, used as the renderer's working directory.

    Raises:
        ReleaseError: If the renderer is missing or exits non-zero.
    """
    renderer = root / "utilities" / "build_user_guides.py"
    if not renderer.is_file():
        raise ReleaseError(f"no shared guide renderer at {renderer}")
    result = subprocess.run(
        [python, str(renderer), guide.parent.name],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(
            f"build_user_guides.py failed for {guide.parent.name} "
            f"(exit {result.returncode}):\n{result.stdout}{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------


def update_lock(root: Path, offline: bool) -> None:
    """Regenerate ``uv.lock`` for the bumped version."""
    uv = shutil.which("uv")
    if uv is None:
        raise ReleaseError("uv is not on PATH; cannot re-lock")
    args = [uv, "lock", *(["--offline"] if offline else [])]
    result = subprocess.run(args, cwd=root, check=False)
    if result.returncode != 0:
        raise ReleaseError(f"uv lock failed (exit {result.returncode})")


def lock_is_current(root: Path, offline: bool) -> bool:
    """Whether ``uv.lock`` already matches ``pyproject.toml``."""
    uv = shutil.which("uv")
    if uv is None:
        raise ReleaseError("uv is not on PATH; cannot verify the lock")
    args = [uv, "lock", "--check", *(["--offline"] if offline else [])]
    return subprocess.run(args, cwd=root, check=False).returncode == 0


def lock_declares_version(root: Path, version: str) -> bool:
    """Whether ``uv.lock`` records *version* for the project itself."""
    text = (root / "uv.lock").read_text(encoding="utf-8")
    pattern = re.compile(rf'name = "audiosuite-pro"\nversion = "{re.escape(version)}"')
    return pattern.search(text) is not None


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


#: How many paths one ``compileall`` invocation receives. The whole list would
#: fit comfortably in a POSIX ``ARG_MAX`` but not in a Windows command line, and
#: ``compileall`` has no stdin mode to fall back on.
_COMPILE_BATCH = 100


def compile_tracked(root: Path, python: str) -> int:
    """Byte-compile the files git tracks, which is what "compile" means here.

    ``compileall .`` walks the working tree, ignored build output included, so a
    host that has built the installer fails this step for a reason that has
    nothing to do with the tree: ``packaging/build/app`` stages a vendored
    interpreter whose ``Lib/test`` fixtures are deliberately invalid Python
    (``badsyntax_pep3120.py`` and friends), and the 2.1.6 cut stopped on exactly
    that.  Git's index is the definition of first-party source, so the list comes
    from ``git ls-files`` and is passed in batches.

    ``compileall -`` is **not** the way to read a list from stdin: it prints
    "Can't list '-'" and exits **0**, which would be a gate that cannot fail.

    Args:
        root: The repository root.
        python: The interpreter carrying the dev extras.

    Returns:
        ``0`` when every tracked file compiles, else the first failing exit code.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.py"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if listed.returncode != 0:
        print("[ERROR] git ls-files failed, so the compile step cannot be bounded")
        return listed.returncode
    paths = [name.decode("utf-8") for name in listed.stdout.split(b"\0") if name]
    if not paths:
        print("[ERROR] git lists no Python files; refusing a vacuous compile step")
        return 1
    for start in range(0, len(paths), _COMPILE_BATCH):
        batch = paths[start : start + _COMPILE_BATCH]
        result = subprocess.run(
            [python, "-m", "compileall", "-q", "-f", *batch],
            cwd=root,
            check=False,
            env=streaming_env(),
        )
        if result.returncode != 0:
            return result.returncode
    return 0


def gate_commands(python: str) -> list[tuple[str, list[str]]]:
    """Return the gate's steps that are decided by their exit code.

    The order is AGENTS' Gate: compile, lint and format, types, then tests.
    Compile comes first but is not listed here: it runs over the tracked file
    list (:func:`compile_tracked`) rather than over ``.``. Security sits between
    types and tests and is run separately because its severity block, not its
    exit code, expresses the verdict.
    """
    return [
        ("ruff check", [python, "-m", "ruff", "check", "."]),
        ("ruff format --check", [python, "-m", "ruff", "format", "--check", "."]),
        ("mypy", [python, "-m", "mypy", "."]),
    ]


def bandit_verdict(returncode: int, output: str) -> tuple[bool, str]:
    """Interpret bandit's output as this project's 0-High / 0-Medium gate.

    Args:
        returncode: Bandit's exit code. ``1`` means "a finding survived the
            LOW/LOW filter", which is not a failure by itself.
        output: Bandit's combined output.

    Returns:
        ``(ok, summary)``. An unparseable severity block is never ok: a
        missing verdict must fail loudly rather than vacuously.
    """
    severity = output.find("Total issues (by severity):")
    confidence = output.find("Total issues (by confidence):")
    if severity < 0 or confidence <= severity:
        return False, "could not parse bandit's severity block"

    block = output[severity:confidence]
    counts: dict[str, int] = {}
    for level in ("High", "Medium", "Low"):
        match = re.search(rf"(?m)^\s*{level}:\s*(\d+)", block)
        if match is not None:
            counts[level] = int(match.group(1))

    high = counts.get("High")
    medium = counts.get("Medium")
    low = counts.get("Low")
    summary = f"severity High={high} Medium={medium} Low={low}"
    if high is None or medium is None:
        return False, f"incomplete severity block ({summary})"
    if returncode == 0:
        return True, summary
    if returncode == 1 and high == 0 and medium == 0:
        return True, summary
    return False, f"exit {returncode} with {summary}"


def streaming_env() -> dict[str, str]:
    """The environment a gate child needs to stay readable while it runs.

    A cut is normally launched from a background shell with stdout redirected
    to a log, and Python block-buffers a redirected stdout. Each child (ruff,
    mypy, pytest) then writes in 8 KiB bursts, so a 21-minute run arrives as a
    few chunks at the end and "still working" is indistinguishable from
    "wedged" - the 2.1.7 cut's log looked stalled at 14% for most of its
    duration for exactly this reason. ``PYTHONUNBUFFERED`` makes every child
    write as it goes.

    The parent's own progress lines need ``flush=True`` for the same reason,
    and they need it *separately*: a buffered ``[START] pytest`` would surface
    after pytest's output rather than before it, which misreports the order the
    gate ran in.

    Returns:
        A copy of the current environment with ``PYTHONUNBUFFERED`` set, so a
        child that needs further overrides can still merge its own onto it.
    """
    return {**os.environ, "PYTHONUNBUFFERED": "1"}


def run_gate(root: Path, python: str) -> int:
    """Run the full gate, stopping at the first failure.

    Every progress line is flushed and every child runs unbuffered, so the log
    of a backgrounded cut shows which step is running while it runs; see
    :func:`streaming_env`.

    Args:
        root: The repository root (the gate's working directory).
        python: The interpreter carrying the dev extras.

    Returns:
        ``0`` when every step passed, else the first failing exit code.
    """
    print("[START] gate (compile, lint, format, types, security, tests)", flush=True)
    print("[START] compileall (tracked files)", flush=True)
    code = compile_tracked(root, python)
    if code != 0:
        print(f"[ERROR] compileall (exit {code})", flush=True)
        return code
    print("[OK] compileall (tracked files)", flush=True)
    steps = [*gate_commands(python)]
    for index, (label, args) in enumerate(steps):
        print(f"[START] {label}", flush=True)
        result = subprocess.run(args, cwd=root, check=False, env=streaming_env())
        if result.returncode != 0:
            print(f"[ERROR] {label} (exit {result.returncode})", flush=True)
            return result.returncode
        print(f"[OK] {label}", flush=True)
        if index == len(steps) - 1:
            _run_security(root, python)

    print("[START] pytest", flush=True)
    result = subprocess.run(
        [python, "-m", "pytest", "-q"],
        cwd=root,
        check=False,
        env=streaming_env(),
    )
    if result.returncode != 0:
        print(f"[ERROR] pytest (exit {result.returncode})", flush=True)
        return result.returncode
    print("[OK] pytest", flush=True)
    print("[DONE] gate passed", flush=True)
    return 0


def refresh_install_metadata(root: Path, python: str) -> None:
    """Reinstall the project's metadata so the gate sees the bumped version.

    The gate's install-health tests compare ``pyproject.toml``'s version with
    the installed distribution's metadata.  After a bump the two disagree until
    the editable install is refreshed, so `doctor`'s healthy-install tests fail
    for the right reason - the environment is stale, not the code - and a
    release could never pass its own gate.

    This goes through ``uv``, the project's package manager and the only tool
    already required to cut a release: the venv it manages has no
    ``setuptools``, so ``pip install --no-build-isolation`` fails with
    ``BackendUnavailable`` and an isolated pip build would download a backend
    the lock never pinned. ``uv pip install --no-deps`` rewrites the editable
    install's metadata in about a tenth of a second and adds nothing else.

    Args:
        root: The repository root to reinstall from.
        python: The interpreter that carries the editable install.

    Raises:
        ReleaseError: If uv is missing or the reinstall fails, naming the
            command to run by hand.
    """
    uv = shutil.which("uv")
    if uv is None:
        raise ReleaseError(
            "uv is not on PATH, so the installed metadata cannot be refreshed "
            f"and the gate would read the old version; run `{python} -m pip "
            "install --no-deps -e .` and re-run"
        )
    print("[START] refresh the editable install's metadata", flush=True)
    result = subprocess.run(
        [
            uv,
            "pip",
            "install",
            "--no-deps",
            "--python",
            python,
            "-e",
            str(root),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseError(
            "could not refresh the installed metadata, so the gate would read "
            "the old version; run `"
            f"{python} -m pip install --no-deps -e .` and re-run:\n"
            f"{result.stdout}{result.stderr}"
        )
    print("[OK] editable install metadata refreshed", flush=True)


def _run_security(root: Path, python: str) -> None:
    """Run bandit and fail the gate on 0 High / 0 Medium violations."""
    print("[START] bandit", flush=True)
    env = {**streaming_env(), "PYTHONUTF8": "1"}
    result = subprocess.run(
        [
            python,
            "-X",
            "utf8",
            "-m",
            "bandit",
            "-r",
            ".",
            "-x",
            "./.venv",
            "-c",
            "pyproject.toml",
        ],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    print(result.stdout, flush=True)
    if result.stderr:
        print(result.stderr, file=sys.stderr, flush=True)
    ok, summary = bandit_verdict(result.returncode, result.stdout + result.stderr)
    if not ok:
        raise ReleaseError(f"bandit failed ({summary})")
    print(f"[OK] bandit ({summary})", flush=True)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


def _write(path: Path, text: str, dry_run: bool) -> None:
    """Write *text* to *path* unless this is a dry run."""
    if not dry_run:
        path.write_text(text, encoding="utf-8", newline="")


def _release_version(root: Path, version: str, dry_run: bool) -> None:
    """Bump ``[project] version`` and add its change note."""
    path = root / "pyproject.toml"
    text = path.read_text(encoding="utf-8")
    new_text, old = bump_project_version(text, version)
    if old is None:
        print(f"[SKIP] pyproject.toml already declares {version}")
        return
    if dry_run:
        print(f"[INFO] would bump pyproject.toml {old} -> {version}")
        return
    _write(path, new_text, dry_run)
    print(f"[OK] pyproject.toml {old} -> {version}")


def _release_lock(root: Path, version: str, offline: bool, dry_run: bool) -> None:
    """Regenerate and verify ``uv.lock``."""
    if dry_run:
        print("[INFO] would ensure uv.lock records the new version")
        return
    if lock_is_current(root, offline):
        print("[SKIP] uv.lock already matches pyproject.toml")
    else:
        update_lock(root, offline)
        print("[OK] uv.lock re-locked")
    if not lock_declares_version(root, version):
        raise ReleaseError(f"uv.lock does not record audiosuite-pro {version}")
    print(f"[OK] uv.lock records {version}")


def _release_changelog(root: Path, version: str, date: str, dry_run: bool) -> None:
    """Promote ``[Unreleased]`` in both change-history files and reopen it.

    ``CHANGELOG.md`` is the user-facing history ``whats_new`` renders and must
    hold an entry; ``TECHNICAL_CHANGELOG.md`` is the developer-facing half and
    legitimately holds none for a release with no developer-facing change, so
    it is promoted only when it has something to promote.
    """
    for name, required in CHANGELOG_FILES:
        path = root / name
        text = path.read_text(encoding="utf-8")
        already = any(line.startswith(f"## [{version}]") for line in text.splitlines())
        new_text, changed = promote_changelog(
            text, version, date, require_entries=required
        )
        if not changed:
            if already:
                print(f"[SKIP] {name} already carries [{version}] and a placeholder")
            else:
                print(f"[SKIP] {name} holds no entries for [{version}]")
            continue
        if dry_run:
            print(f"[INFO] would promote {name} [Unreleased] to [{version}]")
            continue
        _write(path, new_text, dry_run)
        print(f"[OK] {name} [{version}] - {date}")


def _release_guides(root: Path, version: str, python: str, dry_run: bool) -> None:
    """Regenerate every version-labelled guide and verify the diff."""
    guides = version_labelled_guides(root)
    print(f"[INFO] {len(guides)} version-labelled guide(s)")
    for guide in guides:
        label = guide_version_label(guide)
        if label is not None and label.startswith(
            f"{VERSION_LABEL_PREFIX}{version}{VERSION_LABEL_SEPARATOR}"
        ):
            print(f"[SKIP] {guide.name} already labels {version}")
            continue
        if dry_run:
            print(f"[INFO] would regenerate {guide.parent.name}/{guide.name}")
            continue
        before = entry_data(guide)
        regenerate_guide(guide, python, root)
        problems = guide_change_problems(guide, before, version)
        if problems:
            raise ReleaseError(
                f"{guide.parent.name}/{guide.name}: " + "; ".join(problems)
            )
        print(f"[OK] {guide.name} -> {guide_version_label(guide)}")


def _validate(version: str, date: str) -> None:
    """Reject a malformed version or date before anything is written."""
    if not _VERSION_RE.match(version):
        raise ReleaseError(f"{version!r} is not an X.Y.Z version")
    if not _DATE_RE.match(date):
        raise ReleaseError(f"{date!r} is not a YYYY-MM-DD date")
    try:
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise ReleaseError(f"{date!r} is not a real date: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    """Run the release cut.

    Args:
        argv: Command-line arguments, defaulting to ``sys.argv[1:]``.

    Returns:
        ``0`` on success, ``1`` when a step refuses to proceed, or the
        failing gate step's exit code.
    """
    parser = argparse.ArgumentParser(
        description="Cut a release: bump, re-lock, rotate the changelog, "
        "regenerate the version-labelled guides and run the gate."
    )
    parser.add_argument("version", help="The version to release, e.g. 1.4.0")
    parser.add_argument(
        "--date",
        default=dt.date.today().isoformat(),
        help="Release date for the changelog heading (default: today)",
    )
    parser.add_argument(
        "--root",
        default=str(_REPO_ROOT),
        help="Repository root (default: this checkout)",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Interpreter carrying the dev extras (default: this one)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report every planned change without writing or gating",
    )
    parser.add_argument(
        "--skip-gate",
        action="store_true",
        help="Stop after the file changes instead of running the gate",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Pass --offline to uv (no dependency graph changes expected)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    if not (root / "pyproject.toml").is_file():
        print(f"[ERROR] {root} has no pyproject.toml", file=sys.stderr)
        return 1

    try:
        _validate(args.version, args.date)
        _release_version(root, args.version, args.dry_run)
        _release_lock(root, args.version, args.offline, args.dry_run)
        _release_changelog(root, args.version, args.date, args.dry_run)
        _release_guides(root, args.version, args.python, args.dry_run)
        if args.dry_run:
            print("[DONE] dry run - nothing was written")
            return 0
        if args.skip_gate:
            print("[DONE] release files updated (gate skipped)")
            return 0
        # The gate reads the *installed* version through doctor; a bump that
        # leaves the editable install stale would fail its own gate.
        refresh_install_metadata(root, args.python)
        return run_gate(root, args.python)
    except ReleaseError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
