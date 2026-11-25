"""Lock ASCII-only console and log output (R-14, audit finding C-09).

A cp1252 console — Windows' default — cannot encode ``—``, ``✓``, ``✗`` or
``→``, so printing one raises ``UnicodeEncodeError: 'charmap' codec can't
encode character``.  That is not hypothetical: writing this suite's own
non-ASCII inventory crashed under the default console during the audit, and a
skip reason rendered as ``Slider update failed ? broken Tcl/Tk environment``.

The rule this module enforces is the one ``AGENTS.md`` states for
``utilities/*.py`` markers, extended to every first-party output call:
typography belongs in comments, docstrings and documentation, where no console
ever renders it; anything that reaches a console or a log uses ASCII.

Only string constants that are arguments to an output call - or that form a
per-file ``display``/``display_text`` line - are inspected, so a comment or
docstring may keep its em dashes.  Both spellings are caught: the literal
glyph and its ``\\u2014`` escape produce the same malformed constant.

Changed in 2.1.7: initial version, closing R-14 by making the rule enforceable.
The audit's C-09 finding asked for exactly this arbiter - "a test that subprocess
CLI output is cp1252-encodable" - and it is the reason the sweep is a one-off
rather than a periodic chore.
Changed in 2.9.0: the scan also reads ``display``/``display_text`` values, the
per-file line every tool prints through ``on_progress``; those were assigned to
a variable rather than passed to an output call, so five tools kept an arrow a
cp1252 console renders as ``\\u2192``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Callables whose string arguments reach a console or a log record.
_OUTPUT_CALLS: frozenset[str] = frozenset(
    {
        "print",
        "debug",
        "info",
        "warning",
        "error",
        "critical",
        "exception",
        "log",
    }
)

#: Names whose string value is the per-file line a tool shows and logs.  They
#: reach the console through ``on_progress``, so they are output even when they
#: are built in an assignment rather than passed to one of the calls above.
_DISPLAY_NAMES: frozenset[str] = frozenset({"display", "display_text"})

#: Directories that are not first-party source for this rule: a vendored build
#: tree repeats shipped modules, and a plugin is third-party code the suite does
#: not own.
_EXCLUDED_DIRS: frozenset[str] = frozenset({"tests", "packaging", "plugins"})


def _candidate_files() -> list[Path]:
    """Return every first-party module whose output this rule governs.

    ``utilities/`` is included by name rather than by package discovery: those
    scripts are exactly where the rule was first written, and they have no
    ``__init__.py`` to discover.
    """
    files = sorted((REPO_ROOT / "utilities").glob("*.py"))
    for package in sorted(REPO_ROOT.iterdir()):
        if (
            package.is_dir()
            and (package / "__init__.py").is_file()
            and package.name not in _EXCLUDED_DIRS
        ):
            files.extend(
                path
                for path in sorted(package.rglob("*.py"))
                if not _EXCLUDED_DIRS.intersection(path.relative_to(REPO_ROOT).parts)
            )
    return files


def _constants(node: ast.AST) -> Iterator[tuple[int, str]]:
    """Yield ``(line, value)`` for every string constant under *node*."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.lineno, sub.value


def _is_display_target(node: ast.expr) -> bool:
    """Return whether *node* is assigned to a per-file display name."""
    return isinstance(node, ast.Name) and node.id in _DISPLAY_NAMES


def _output_strings(path: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(line, value)`` for every string that reaches the console.

    Two shapes count: an argument (or ``display`` keyword) of an output call,
    and a ``display``/``display_text`` value, which is the per-file line a tool
    hands to ``on_progress`` after building it in an assignment.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else (func.attr if isinstance(func, ast.Attribute) else None)
            )
            if name in _OUTPUT_CALLS:
                for argument in node.args:
                    yield from _constants(argument)
            for keyword in node.keywords:
                if keyword.arg in _DISPLAY_NAMES:
                    yield from _constants(keyword.value)
        elif isinstance(node, ast.Assign):
            if any(_is_display_target(target) for target in node.targets):
                yield from _constants(node.value)
        elif isinstance(node, ast.AnnAssign):
            if _is_display_target(node.target) and node.value is not None:
                yield from _constants(node.value)


@pytest.fixture(scope="module")
def scanned() -> list[tuple[Path, int, str]]:
    """Every output string in the tree, as ``(path, line, value)`` triples."""
    return [
        (path, line, value)
        for path in _candidate_files()
        for line, value in _output_strings(path)
    ]


class TestDisplayStringsAreScanned:
    """The per-file line is output even when it is built in an assignment."""

    def test_an_assigned_display_value_is_scanned(self, tmp_path: Path) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            'display = f"[TAGGED] {name} \u2192 {action}"\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2192" in value for value in values)

    def test_a_display_keyword_is_scanned(self, tmp_path: Path) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            'on_progress(display_text=f"[SKIP] {name} \u2192 Clean")\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2192" in value for value in values)


class TestConsoleOutputIsAscii:
    """No first-party console/log string may carry a non-ASCII character."""

    def test_scan_is_non_vacuous(self, scanned: list[tuple[Path, int, str]]) -> None:
        """The scan must really cover the tree, or it passes for free."""
        assert len(scanned) > 500, (
            f"only {len(scanned)} output strings found - the scan has stopped "
            "reaching the tree"
        )
        paths = {path for path, _line, _value in scanned}
        assert (REPO_ROOT / "utilities") / "verify_refinery_log.py" in paths, (
            "utilities/ is not being scanned"
        )
        assert (REPO_ROOT / "audio_suite_shared") / "exceptions.py" in paths, (
            "the shared package is not being scanned"
        )
        assert (REPO_ROOT / "bpm_analyzer") / "core" / "file_processor.py" in paths, (
            "per-file display lines are not being scanned"
        )

    def test_no_output_string_carries_a_non_ascii_character(
        self, scanned: list[tuple[Path, int, str]]
    ) -> None:
        """The assertion the rule exists for, reported per offending line."""
        offenders = [
            f"{path.relative_to(REPO_ROOT)}:{line}: {value!r}"
            for path, line, value in scanned
            if not value.isascii()
        ]
        assert not offenders, (
            "console/log output must be ASCII-only (R-14 / AGENTS.md 'Utility "
            "Script Markers'); keep typography in comments and docs:\n  "
            + "\n  ".join(offenders)
        )

    def test_every_output_string_encodes_to_the_console_codec(
        self, scanned: list[tuple[Path, int, str]]
    ) -> None:
        """State the failure directly: cp1252 is what breaks, not ASCII-ness.

        This is the audit's own acceptance criterion.  It passes for the same
        reason the assertion above does, and it is kept because a future
        relaxation to "latin-1 is fine" would have to change this test by hand
        rather than quietly pass.
        """
        for path, line, value in scanned:
            value.encode("cp1252")  # UnicodeEncodeError names the character
