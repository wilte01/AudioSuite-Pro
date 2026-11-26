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

Only string constants that reach output are inspected, so a comment or
docstring may keep its em dashes.  Both spellings are caught: the literal
glyph and its ``\\u2014`` escape produce the same malformed constant.

Changed in 2.1.7: initial version, closing R-14 by making the rule enforceable.
The audit's C-09 finding asked for exactly this arbiter - "a test that subprocess
CLI output is cp1252-encodable" - and it is the reason the sweep is a one-off
rather than a periodic chore.
Changed in 2.9.0: the scan also reads ``display``/``display_text`` values, the
per-file line every tool prints through ``on_progress``; those were assigned to
a variable rather than passed to an output call, so five tools kept an arrow a
cp1252 console renders as ``\\u2192``.  The same rule now covers ``log_text``
and the ``action`` fragment both lines are built from: a repair that prints
``Fixed 1 thing - Done`` in ASCII still wrote an em dash into the run report
through the fragment, so the lock has to read the fragment and not only the
line that quotes it.  ``outcome`` joins them, and a display value that is a
*call* is followed: Album Art Normalizer's skip line is the string its
``process_*_artwork`` functions return, and the fingerprinter's is
``_result_display``'s, so a lock that stopped at the call site would have left
both defects in place.  Only a producer that can hand back text is followed,
annotated ``str`` or not annotated at all: ``outcome`` is a generic name that a
dozen modules also give to object-returning calls (``join_files``,
``ScanOutcome``, ``verify_extracted_track``), whose strings are fields rather
than lines any console shows.  The run report is read the same way.
The ``[ALBUM]`` summary is a ``report_line`` field on ``AlbumResolution``, so
the name is display text even though it is never bound to a local, and a string
appended (or inserted, or extended) into ``log_entries`` or ``report_lines`` is
a report line because that is where the run report is assembled.  Those two
containers are named for the report, which keeps the rule narrow: a Tk listbox
fills a plain ``lines``/``notes`` list with its bullets, and a console never
renders it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from functools import lru_cache
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

#: Names whose string value is a per-file line a tool shows and logs, or a
#: fragment that line is built from.  They reach the console through
#: ``on_progress`` and the run report through ``log_entries``, so they are
#: output even when they are built in an assignment rather than passed to one
#: of the calls above.  The log line is written as ``log``, ``log_line`` or
#: ``log_text`` depending on the tool, so all three are covered; ``action`` is
#: the verdict both lines quote (``Fixed 1 thing``) and ``repaired_suffix`` the
#: fragment an in-place repair tool appends to it.  ``outcome`` is the status
#: string a processor returns for one file - Album Art Normalizer prints it as
#: ``[SKIPPED] song.mp3 - <outcome>`` - so the name is read here as well as the
#: line that quotes it.  It is a generic name, so ``_returns_text`` keeps it
#: from following a producer that returns an object; without that gate the
#: name alone would pull a dozen object fields into a console rule.
#: ``action`` is also the keyword argparse and Tk take for
#: an option flag; those strings are ASCII by construction, so the shared name
#: costs nothing and keeps one rule instead of one per call.
_DISPLAY_NAMES: frozenset[str] = frozenset(
    {
        "display",
        "display_text",
        "log",
        "log_line",
        "log_text",
        "action",
        "repaired_suffix",
        "outcome",
        "report_line",
    }
)

#: The run-report containers a tool assembles its report in: ``log_entries`` is
#: the completion payload's field the shell writes to ``*_log.txt``, and
#: ``report_lines`` is a phase's share of it - the ``[ALBUM]`` and ``[ISRC]``
#: lines reach the file through one of them and never through an output call.
#: The generic ``lines``/``notes`` locals around them are deliberately not read:
#: a Tk listbox fills one of those with bullets a console never renders.
_REPORT_CONTAINERS: frozenset[str] = frozenset({"log_entries", "report_lines"})

#: Methods that add one line, or a run of them, to a report container.
_REPORT_METHODS: frozenset[str] = frozenset({"append", "extend", "insert"})

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


@lru_cache(maxsize=None)
def _parse(path: Path) -> ast.Module:
    """Parse *path* once; the fragment walk revisits the same modules."""
    return ast.parse(path.read_text(encoding="utf-8"))


def _constants(node: ast.AST) -> Iterator[tuple[int, str]]:
    """Yield ``(line, value)`` for every string constant under *node*."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            yield sub.lineno, sub.value


def _is_display_target(node: ast.expr) -> bool:
    """Return whether *node* is assigned to a per-file display name."""
    return isinstance(node, ast.Name) and node.id in _DISPLAY_NAMES


def _display_expressions(tree: ast.Module) -> Iterator[ast.expr]:
    """Yield every expression whose value is a per-file display fragment."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in _DISPLAY_NAMES:
                    yield keyword.value
        elif isinstance(node, ast.Assign):
            if any(_is_display_target(target) for target in node.targets):
                yield node.value
        elif isinstance(node, ast.AnnAssign):
            if _is_display_target(node.target) and node.value is not None:
                yield node.value


def _output_strings(path: Path) -> Iterator[tuple[int, str]]:
    """Yield ``(line, value)`` for every string the module prints itself.

    Three shapes count: an argument of an output call, a
    ``display``/``display_text``-style value, which is the per-file line a tool
    hands to ``on_progress`` after building it in an assignment, and a line
    added to a run-report container, which no output call ever sees.
    """
    tree = _parse(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if _call_name(node) in _OUTPUT_CALLS or _is_report_append(node):
                for argument in node.args:
                    yield from _constants(argument)
    for expression in _display_expressions(tree):
        yield from _constants(expression)


def _call_name(node: ast.Call) -> str | None:
    """Return the name a call is made through, or None for anything else."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_report_append(node: ast.Call) -> bool:
    """Return whether *node* adds a line to a run-report container."""
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr in _REPORT_METHODS
        and isinstance(func.value, ast.Name)
        and func.value.id in _REPORT_CONTAINERS
    )


def _imported_module(path: Path, node: ast.ImportFrom, name: str) -> Path | None:
    """Resolve one name of an ``ImportFrom`` to the module file it lives in."""
    if node.level:
        base = path.parent
        for _ in range(node.level - 1):
            base = base.parent
    else:
        base = REPO_ROOT
    module = base.joinpath(*node.module.split(".")) if node.module else base / name
    for candidate in (module.with_suffix(".py"), module / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _local_definition(
    tree: ast.Module, name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return this module's own definition of *name*, if it has one."""
    for node in tree.body:
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == name
        ):
            return node
    return None


def _definition(
    path: Path,
    tree: ast.Module,
    name: str,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> tuple[Path, ast.Module, ast.FunctionDef | ast.AsyncFunctionDef] | None:
    """Resolve *name* to the function body that defines it, in this file or an
    import, following a re-export chain rather than guessing.

    *visited* is the whole guard: a re-export names each module at most once,
    so the walk cannot loop and needs no hop count.
    """
    key = (path, name)
    if key in visited:
        return None
    local = _local_definition(tree, name)
    if local is not None:
        return path, tree, local
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != name:
                continue
            module = _imported_module(path, node, alias.name)
            if module is None:
                return None
            return _definition(module, _parse(module), alias.name, visited | {key})
    return None


def _local_values(tree: ast.Module, name: str) -> list[ast.expr]:
    """Return every expression this module binds to a local *name*."""
    values: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_is_name(target, name) for target in node.targets):
                values.append(node.value)
        elif isinstance(node, ast.AnnAssign):
            if _is_name(node.target, name) and node.value is not None:
                values.append(node.value)
    return values


def _is_name(node: ast.expr, name: str) -> bool:
    """Return whether *node* is the bare name *name*."""
    return isinstance(node, ast.Name) and node.id == name


def _is_function_table(value: ast.expr) -> bool:
    """Return whether *value* is a table of functions a processor is chosen from."""
    return isinstance(value, ast.Dict | ast.List | ast.Set | ast.Tuple)


def _call_sources(
    path: Path,
    tree: ast.Module,
    expression: ast.AST,
    visited: frozenset[tuple[Path, str]],
) -> Iterator[tuple[Path, ast.Module, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Yield the functions whose text can become *expression*'s value."""
    for sub in ast.walk(expression):
        if isinstance(sub, ast.Call):
            name = _call_name(sub)
            if name is not None:
                yield from _name_sources(path, tree, name, visited, from_call=True)
        elif isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
            yield from _name_sources(path, tree, sub.id, visited, from_call=False)


def _name_sources(
    path: Path,
    tree: ast.Module,
    name: str,
    visited: frozenset[tuple[Path, str]],
    *,
    from_call: bool,
) -> Iterator[tuple[Path, ast.Module, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Resolve *name* to the producers behind it, following a local binding only
    when it is a call the value is made from or a table of callables."""
    key = (path, name)
    if key in visited:
        return
    definition = _definition(path, tree, name)
    if definition is not None:
        yield definition
        return
    for value in _local_values(tree, name):
        if from_call or _is_function_table(value):
            yield from _call_sources(path, tree, value, visited | {key})


def _returns_text(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether *function* can hand back text rather than an object.

    An unannotated function counts, so the rule fails safe: skipping it would
    hide the very lines this module exists for.  An annotated non-text return -
    ``JoinOutcome``, ``InstallOutcome``, ``VerifyOutcome`` - does not, because
    its ``return`` builds an object and the strings inside it are fields, not
    text any console renders.
    """
    if function.returns is None:
        return True
    for node in ast.walk(function.returns):
        if isinstance(node, ast.Name) and node.id == "str":
            return True
        if isinstance(node, ast.Constant) and node.value == "str":
            return True
    return False


def _producer_strings(
    path: Path,
    tree: ast.Module,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    visited: frozenset[tuple[Path, str]] = frozenset(),
) -> Iterator[tuple[Path, int, str]]:
    """Yield ``(path, line, value)`` for the text *function* returns.

    Only ``return`` statements are read - not the whole body - so a helper the
    producer merely calls for its side effects cannot drag unrelated strings
    into the lock.  A return that delegates to a sibling formatter is followed,
    because that is where a composed line's wording lives; *visited* stops two
    helpers that delegate to each other.
    """
    if not _returns_text(function):
        return
    seen = visited | {(path, function.name)}
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            for line, value in _constants(node.value):
                yield path, line, value
            for source_path, source_tree, helper in _call_sources(
                path, tree, node.value, seen
            ):
                yield from _producer_strings(source_path, source_tree, helper, seen)


def _fragment_strings(path: Path) -> Iterator[tuple[Path, int, str]]:
    """Yield the strings a call-returned display value is built from.

    A tool that binds ``outcome = processor(...)`` or passes
    ``display_text=_result_display(result)`` prints text this module's own file
    does not contain, so the scan follows the call to the function that returns
    it.  Without that hop the em dashes in those lines are invisible to the
    lock and resurface on the user's console.
    """
    tree = _parse(path)
    for expression in _display_expressions(tree):
        for source_path, source_tree, function in _call_sources(
            path, tree, expression, frozenset()
        ):
            yield from _producer_strings(source_path, source_tree, function)


@pytest.fixture(scope="module")
def scanned() -> list[tuple[Path, int, str]]:
    """Every output string in the tree, as ``(path, line, value)`` triples."""
    found: set[tuple[Path, int, str]] = set()
    for path in _candidate_files():
        found.update((path, line, value) for line, value in _output_strings(path))
        found.update(_fragment_strings(path))
    return sorted(found, key=lambda item: (str(item[0]), item[1], item[2]))


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

    @pytest.mark.parametrize(
        "keyword",
        ["display_text", "log", "log_line", "log_text", "action", "repaired_suffix"],
    )
    def test_a_display_keyword_is_scanned(self, keyword: str, tmp_path: Path) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            f'InplaceDspResult({keyword}=f"[SKIP] {{name}} \\u2192 Clean")\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2192" in value for value in values)

    @pytest.mark.parametrize(
        "name", ["log", "log_line", "log_text", "action", "outcome"]
    )
    def test_a_log_or_action_assignment_is_scanned(
        self, name: str, tmp_path: Path
    ) -> None:
        """The report line and the verdict are output even before they print."""
        module = tmp_path / "mod.py"
        module.write_text(
            f'{name} = f"Fixed 1 thing \\u2014 {{{{suffix}}}}"\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2014" in value for value in values)


class TestCallReturnedFragmentsAreScanned:
    """A display value a tool gets back from a call is output too."""

    def test_a_same_file_formatter_is_followed(self, tmp_path: Path) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            "def _describe(name):\n"
            '    return f"[SKIP] {name} \u2014 clean"\n'
            "\n"
            "display_text = _describe(name)\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert any("\u2014" in value for value in values)

    def test_an_imported_formatter_is_followed(self, tmp_path: Path) -> None:
        package = tmp_path / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "formats.py").write_text(
            'def describe(name):\n    return f"[SKIP] {name} \u2014 clean"\n',
            encoding="utf-8",
        )
        module = package / "runner.py"
        module.write_text(
            "from .formats import describe\n\ndisplay = describe(name)\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert any("\u2014" in value for value in values)

    def test_a_text_annotated_formatter_is_followed(self, tmp_path: Path) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            "def _describe(name) -> str:\n"
            '    return f"[SKIP] {name} \u2014 clean"\n'
            "\n"
            "display_text = _describe(name)\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert any("\u2014" in value for value in values)

    def test_an_object_returning_producer_is_not_followed(self, tmp_path: Path) -> None:
        """``outcome`` is a shared name; an object's fields are not console text."""
        module = tmp_path / "mod.py"
        module.write_text(
            "def _scan(path) -> ScanOutcome:\n"
            '    return ScanOutcome(message="stale \u2014 entry")\n'
            "\n"
            "outcome = _scan(path)\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert not any("\u2014" in value for value in values)

    def test_a_formatter_chosen_from_a_table_is_followed(self, tmp_path: Path) -> None:
        """Album Art Normalizer picks its processor from a per-suffix table."""
        module = tmp_path / "mod.py"
        module.write_text(
            "def _resize(path, target, dry_run):\n"
            '    return "Embedded image already 800x800 \u2014 skipped."\n'
            "\n"
            'HANDLERS = {".mp3": _resize}\n'
            "processor = HANDLERS.get(suffix)\n"
            "outcome = processor(path, target, dry_run)\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert any("\u2014" in value for value in values)


class TestRunReportLinesAreScanned:
    """Report lines are assembled in a container, never passed to a printer."""

    def test_a_report_line_field_is_scanned(self, tmp_path: Path) -> None:
        """``AlbumResolution.report_line`` carries the ``[ALBUM]`` summary."""
        module = tmp_path / "mod.py"
        module.write_text(
            "def _report_line(folder):\n"
            '    return f"[ALBUM] {folder}: decided \\u2014 Album"\n'
            "\n"
            "AlbumResolution(report_line=_report_line(folder))\n",
            encoding="utf-8",
        )

        values = [value for _path, _line, value in _fragment_strings(module)]

        assert any("\u2014" in value for value in values)

    @pytest.mark.parametrize("container", ["log_entries", "report_lines"])
    def test_a_line_appended_to_a_report_container_is_scanned(
        self, container: str, tmp_path: Path
    ) -> None:
        module = tmp_path / "mod.py"
        module.write_text(
            f'{container}.append(f"[ALBUM] {{label}}: ambiguous \\u2014 tied")\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2014" in value for value in values)

    def test_a_report_header_is_scanned_where_a_tool_inserts_it(
        self, tmp_path: Path
    ) -> None:
        """The Stem Separator prepends its run report's header with ``insert``."""
        module = tmp_path / "mod.py"
        module.write_text(
            'log_entries.insert(0, "=== Stem separation \\u2014 3 file(s) ===")\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert any("\u2014" in value for value in values)

    def test_an_unrelated_line_list_is_not_scanned(self, tmp_path: Path) -> None:
        """A Tk listbox fills ``lines`` with bullets; a console never shows it."""
        module = tmp_path / "mod.py"
        module.write_text(
            'lines.append(f"  \\u2022 {item}")\n',
            encoding="utf-8",
        )

        values = [value for _line, value in _output_strings(module)]

        assert not any("\u2022" in value for value in values)


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
        assert (
            REPO_ROOT / "album_art_normalizer"
        ) / "core" / "art_processor.py" in paths, (
            "a call-returned per-file outcome is not being scanned"
        )
        assert (
            REPO_ROOT / "audio_fingerprinter" / "core" / "fingerprint_messages.py"
            in paths
        ), "an imported per-file formatter is not being followed"
        assert (
            REPO_ROOT / "audio_fingerprinter" / "core" / "album_cluster.py" in paths
        ), "a report line carried on a result object is not being scanned"
        assert (
            REPO_ROOT / "audio_fingerprinter" / "core" / "fingerprint_phases.py"
            in paths
        ), "a report line appended to a report container is not being scanned"

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
