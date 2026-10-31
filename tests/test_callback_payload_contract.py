"""Every GUI callback the processor invokes must accept the payload it sends.

Changed in 1.4.1: initial version, the cross-tool lock for the completion seam.
Changed in 1.4.1: extended to the progress and error seams, one rule per seam.
Changed in 2.0.0: registers ``stem_separator`` (Sprint 6, Item 6.1).

The processor owns the payloads of the three callbacks it takes, and each GUI
handler mirrors them by hand, so the two drift independently.  Two shipped
defects proved what that costs on the completion seam: ``BPMAnalyzerApp``
declared its own keyword list while ``run_analysis`` grew ``skipped_files``
(D112), and ``AudioEnhancerApp`` declared five fields while ``run_enhancement``
publishes ``processed``/``skipped`` as well — both finished the audio work and
then raised ``TypeError`` in the callback, losing the report.

The progress seam is the same shape with more variation: the shared runner
publishes ``processed/total/skipped/errors/display_text``, the in-place DSP
runner adds ``succeeded``, and tools add their own counters (``converted``,
``updated``, ``no_genre``, ``done``, ``result``).  A handler bound to one
publisher would raise if that tool switched to the other; no live defect was
found here, so this half is preventive.

The error seam is closed by contract: every tool-side ``on_error(...)`` call in
the tree passes exactly one positional message (the Master Driver's runner
callbacks are a separate two-argument contract and are not wired here), so the
lock pins that arity rather than demanding a catch-all it would never need.

Rules derived from the tree, not from a table:

* ``on_complete`` and every ``on_*progress`` wiring: the handler accepts
  ``**kwargs``.  It still declares every field it uses — extras are ignored,
  never required — so a field added by the processor cannot end a finished run.
* ``on_error`` wiring: the handler accepts one positional message (or ``*args``).

The modules are parsed, never imported: the apps build Tk widgets at import
time and this is a static contract.  ``EXPECTED_SEAMS`` is a frozen snapshot,
so a new GUI tool must be registered here deliberately and a broken discovery
pass cannot succeed vacuously.

Changed in 2.1.0: a plugin tool with no card module is not a GUI seam.

Changed in 2.1.7: ``documentation`` replaces ``user_guides`` in the walk's excluded
directories.

Changed in 2.2.1: registers ``tag_field_updater``, which now starts its run
through ``processor.run_scan`` with the three shared callbacks (maintenance item
U4).  It was the one folder tool whose window drove the scan itself, so it had
no completion seam to check.

Changed in 2.2.1: registers ``tag_editor``, which now starts its load walk and
every apply run through ``run_scan`` / ``run_apply`` (maintenance item U5).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories that never hold first-party app code.  ``plugins`` is
#: third-party code: its wiring is covered by the plugin's own suite, and a
#: plugin must not be able to join (or break) this frozen first-party table.
_SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "documentation",
        "plugins",
    }
)

#: Seams that carry a keyword payload the handler must tolerate.
OPEN_PAYLOAD_SEAMS = frozenset({"complete", "progress"})

#: Seams every GUI tool wires: a run has progress, one completion, and errors.
EXPECTED_SEAMS: frozenset[str] = frozenset({"complete", "progress", "error"})

#: (repo-relative wiring module, class that wires the callbacks).  Both shipped
#: apps live at a package's ``app.py``; ``lyrics_manager`` inherits its handlers.
EXPECTED_TOOLS: frozenset[tuple[str, str]] = frozenset(
    {
        ("album_art_normalizer/app.py", "ArtNormalizerApp"),
        ("album_genre_tagger/app.py", "GenreConsolidatorApp"),
        ("audio_enhancer/app.py", "AudioEnhancerApp"),
        ("audio_fingerprinter/app.py", "FingerprinterApp"),
        ("audio_normalizer/app.py", "AudioNormalizerApp"),
        ("audio_refinery/app.py", "AudioRefineryApp"),
        ("bpm_analyzer/app.py", "BPMAnalyzerApp"),
        ("genre_sync/app.py", "GenreSetterApp"),
        ("lyrics_manager/app.py", "LyricsManagerApp"),
        ("metadata_scrubber/app.py", "MetadataScrubberApp"),
        ("ml_denoiser/app.py", "MlDenoiserApp"),
        ("music_format_converter/app.py", "MusicFormatConverterApp"),
        ("replaygain_analyzer/app.py", "ReplayGainAnalyzerApp"),
        ("silence_trimmer/app.py", "SilenceTrimmerApp"),
        ("stem_separator/app.py", "StemSeparatorApp"),
        ("tag_editor/ui/app.py", "TagEditorApp"),
        ("tag_field_updater/ui/app.py", "TagFieldUpdaterApp"),
        ("tempo_analyzer/app.py", "TempoAnalyzerApp"),
    }
)


@dataclass(frozen=True)
class Wiring:
    """One callback keyword and the handler it resolves to."""

    path: Path
    line: int
    class_name: str
    seam: str
    handler_name: str
    has_var_keyword: bool
    positional_params: tuple[str, ...]
    has_var_positional: bool

    @property
    def label(self) -> str:
        """Return a readable ``module:line Class.handler`` identifier."""
        rel = self.path.relative_to(REPO_ROOT).as_posix()
        return f"{rel}:{self.line} {self.class_name}.{self.handler_name}"


def _first_party_sources() -> list[tuple[Path, ast.Module]]:
    """Parse every first-party module outside the test packages.

    Returns:
        ``(path, module)`` pairs, sorted by path.
    """
    sources: list[tuple[Path, ast.Module]] = []
    for path in sorted(REPO_ROOT.rglob("*.py")):
        parts = set(path.relative_to(REPO_ROOT).parts)
        if parts & _SKIPPED_DIRS or "tests" in parts:
            continue
        sources.append((path, ast.parse(path.read_text(encoding="utf-8"))))
    return sources


def _iter_with_class(
    node: ast.AST, current: ast.ClassDef | None = None
) -> list[tuple[ast.AST, ast.ClassDef | None]]:
    """Walk *node*, tagging each descendant with its innermost class."""
    tagged: list[tuple[ast.AST, ast.ClassDef | None]] = []
    for child in ast.iter_child_nodes(node):
        tagged.append((child, current))
        nested = child if isinstance(child, ast.ClassDef) else current
        tagged.extend(_iter_with_class(child, nested))
    return tagged


def _class_index(
    sources: Sequence[tuple[Path, ast.Module]],
) -> dict[str, ast.ClassDef]:
    """Map every class name to its definition, for inherited-handler lookups."""
    index: dict[str, ast.ClassDef] = {}
    for _path, tree in sources:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                index.setdefault(node.name, node)
    return index


def _base_name(node: ast.expr) -> str | None:
    """Return a base class's name from ``Base`` or ``module.Base``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _find_method(
    index: dict[str, ast.ClassDef],
    cls: ast.ClassDef,
    name: str,
    seen: set[str] | None = None,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Resolve *name* on *cls*, following first-party base classes."""
    visited = seen or set()
    if cls.name in visited:
        return None
    visited.add(cls.name)
    for item in cls.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if item.name == name:
                return item
    for base in cls.bases:
        base_name = _base_name(base)
        if base_name is not None and base_name in index:
            found = _find_method(index, index[base_name], name, visited)
            if found is not None:
                return found
    return None


def _is_self(node: ast.expr) -> bool:
    """Return True for the ``self`` name."""
    return isinstance(node, ast.Name) and node.id == "self"


def _seam_for(keyword: str) -> str | None:
    """Return the seam a callback keyword belongs to, if any."""
    if keyword == "on_complete":
        return "complete"
    if keyword == "on_error":
        return "error"
    if keyword.startswith("on_") and keyword.endswith("_progress"):
        return "progress"
    return None


def _wired_handler_name(value: ast.expr, seam: str) -> str | None:
    """Return the handler a callback keyword ultimately calls.

    Both wiring styles resolve: the direct ``on_progress=self._on_progress``
    and a forwarding ``lambda **kw: self._on_progress(..., **kw)`` (a lambda is
    followed to its ``self.<name>`` call).  A callback that is not a bound
    method — the Master Driver's ``lambda executed: ...``, a CLI's local
    wrapper, ``album_art_sync``'s nested progress function — returns ``None``
    and is not a GUI handler.
    """
    if isinstance(value, ast.Attribute) and _is_self(value.value):
        return value.attr
    if isinstance(value, ast.Lambda):
        called = [
            node.func.attr
            for node in ast.walk(value.body)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_self(node.func.value)
        ]
        for name in called:
            if seam in name.lower():
                return name
        return called[0] if called else None
    return None


def discover_wirings(
    sources: Sequence[tuple[Path, ast.Module]],
) -> list[Wiring]:
    """Return every GUI callback wiring with the facts the seams check.

    Args:
        sources: Parsed first-party modules.

    Returns:
        One entry per recognisable callback keyword that resolves to a method;
        a site whose handler cannot be resolved is recorded with an empty
        ``handler_name`` so the caller can fail loudly instead of skipping it.
    """
    index = _class_index(sources)
    wirings: list[Wiring] = []
    for path, tree in sources:
        for node, cls in _iter_with_class(tree):
            if cls is None or not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg is None:
                    continue
                seam = _seam_for(keyword.arg)
                if seam is None:
                    continue
                handler_name = _wired_handler_name(keyword.value, seam)
                if handler_name is None:
                    continue
                method = _find_method(index, cls, handler_name)
                wirings.append(
                    Wiring(
                        path=path,
                        line=node.lineno,
                        class_name=cls.name,
                        seam=seam,
                        handler_name=handler_name if method is not None else "",
                        has_var_keyword=(
                            method is not None and method.args.kwarg is not None
                        ),
                        positional_params=tuple(arg.arg for arg in method.args.args[1:])
                        if method is not None
                        else (),
                        has_var_positional=(
                            method is not None and method.args.vararg is not None
                        ),
                    )
                )
    return wirings


SOURCE_CACHE: list[tuple[Path, ast.Module]] = _first_party_sources()
WIRINGS: list[Wiring] = discover_wirings(SOURCE_CACHE)


def _seams_found() -> frozenset[tuple[str, str, str]]:
    """Return the discovered ``(module, class, seam)`` triples."""
    return frozenset(
        (wiring.path.relative_to(REPO_ROOT).as_posix(), wiring.class_name, wiring.seam)
        for wiring in WIRINGS
    )


def test_the_scan_finds_every_gui_callback() -> None:
    """The scan must see the whole suite, not a subset it happens to match."""
    found = _seams_found()
    assert {(path, cls) for path, cls, _ in found} == EXPECTED_TOOLS
    assert {seam for _, _, seam in found} == EXPECTED_SEAMS
    for tool in EXPECTED_TOOLS:
        wired = {seam for path, cls, seam in found if (path, cls) == tool}
        assert wired == EXPECTED_SEAMS, f"{tool} wires {sorted(wired)}"
    assert all(wiring.handler_name for wiring in WIRINGS), [
        f"unresolved handler: {wiring.label}"
        for wiring in WIRINGS
        if not wiring.handler_name
    ]


def test_open_payload_handlers_accept_unexpected_keys() -> None:
    """A handler the processor calls must absorb payload fields it ignores."""
    narrow = [
        wiring.label
        for wiring in WIRINGS
        if wiring.seam in OPEN_PAYLOAD_SEAMS and not wiring.has_var_keyword
    ]
    assert not narrow, (
        "callbacks without **kwargs; a field added by the processor would raise "
        "TypeError after the work is done (D112):\n  " + "\n  ".join(narrow)
    )


def test_error_handlers_accept_one_positional_message() -> None:
    """Every tool-side ``on_error(...)`` call passes one positional message."""
    wrong = [
        wiring.label
        for wiring in WIRINGS
        if wiring.seam == "error"
        and not (wiring.positional_params or wiring.has_var_positional)
    ]
    assert not wrong, (
        "error handlers that cannot take the positional message every tool-side "
        "on_error(...) call passes:\n  " + "\n  ".join(wrong)
    )


def test_the_scan_flags_a_narrow_handler() -> None:
    """Prove both rules can fail: each bad handler is reported, not tolerated."""
    source = ast.parse(
        "class Demo:\n"
        "    def _on_complete(self, total: int) -> None: ...\n"
        "    def _on_progress(self, processed: int) -> None: ...\n"
        "    def _on_error(self) -> None: ...\n"
        "    def run(self) -> None:\n"
        "        work(on_complete=lambda **kw: self._on_complete(**kw))\n"
        "        work(on_progress=lambda **kw: self._on_progress(**kw))\n"
        "        work(on_error=self._on_error)\n"
    )
    wirings = discover_wirings([(REPO_ROOT / "demo" / "app.py", source)])

    by_seam = {wiring.seam: wiring for wiring in wirings}
    assert set(by_seam) == {"complete", "progress", "error"}
    assert by_seam["complete"].has_var_keyword is False
    assert by_seam["progress"].has_var_keyword is False
    assert by_seam["error"].positional_params == ()
    assert by_seam["error"].has_var_positional is False


#: The Tk marshalling call: ``widget.after(ms, fn, *args)`` takes positional
#: arguments only.
_AFTER = "after"


def _after_calls_with_keywords(
    sources: Sequence[tuple[Path, ast.Module]] | None = None,
) -> list[str]:
    """Return every ``.after(...)`` call in first-party source that passes keywords.

    ``Misc.after`` is ``after(ms, func, *args)``: forwarding a published keyword
    payload as ``after(0, fn, **kw)`` raises ``TypeError: after() got an
    unexpected keyword argument`` *inside* the completion call, so the work
    finished and the window reported nothing.  Two shipped tools
    (``noise_reduction``, ``pop_click_remover``) had exactly that shape until
    F-02's new window showed the difference; the payload is bound into the call
    with ``functools.partial`` instead.

    Args:
        sources: Parsed modules to scan; defaults to the first-party tree.

    Returns:
        One ``path:line`` label per offending call.
    """
    offenders: list[str] = []
    for path, tree in SOURCE_CACHE if sources is None else sources:
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == _AFTER
                and node.keywords
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{node.lineno}"
                )
    return offenders


def test_after_is_never_called_with_keywords() -> None:
    """A marshalled callback binds its payload positionally, never as keywords."""
    assert any(wiring.seam == "complete" for wiring in WIRINGS), (
        "no completion seam discovered; the scan is broken"
    )
    offenders = _after_calls_with_keywords()

    assert not offenders, (
        "root.after(ms, fn, *args) takes positional arguments only; **kwargs "
        "raises TypeError inside the call and the run reports nothing "
        "(use functools.partial):\n  " + "\n  ".join(offenders)
    )


def test_the_after_scan_flags_a_keyword_call() -> None:
    """Prove the marshalling scan can fail, on the shape it exists to catch."""
    demo = REPO_ROOT / "demo" / "app.py"
    source = ast.parse(
        "def run():\n"
        "    root.after(0, self._on_complete, **kw)\n"
        "    root.after(0, partial(self._on_progress, **kw))\n"
    )

    offenders = _after_calls_with_keywords([(demo, source)])

    assert offenders == ["demo/app.py:2"], offenders
