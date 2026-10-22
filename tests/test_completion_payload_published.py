"""Locks that every processor still *publishes* the completion payload its GUI reads.

Changed in 2.0.0: initial version, closing the publisher half of the completion
seam (PLAN_feature_expansion.md D117).

The two existing locks read the consumer side.
``tests/test_callback_payload_contract.py`` proves every handler tolerates the
fields its processor may send, and
``tests/test_completion_seam.py`` proves each handler's required set is the
contract, so a dropped field raises instead of rendering a plausible zero.  A
``run_*`` that stops sending ``errors`` -- or renames it -- satisfies both, and
the failure lands where the original defects did: inside the callback, after the
DSP has finished, so the run writes no report.

This module closes that gap from the publisher side, without running anything:

* every GUI tool in the contract lock must carry a ``TestCompletionSeam`` case
  in its own ``test_app.py`` that names the processor it drives, so a tool
  added to ``EXPECTED_TOOLS`` without a publisher case fails here instead of
  shrinking the set silently;
* every declared entry point must resolve to a real callable;
* every field a handler *requires* must be published by that entry point,
  supplied by the app's wiring lambda, or carried by the shared completion
  helpers -- the static half of the negative control each tool's case performs
  at runtime.

The static scan never imports a processor: the apps build Tk widgets at import
time, and importing fourteen processors to inspect a signature would make the
lock depend on the whole audio stack.  ``EXPECTED_PUBLISHERS`` is a frozen
table, so a new tool is registered deliberately and a broken discovery pass
cannot succeed vacuously.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Mapping

import pytest

from tests.test_callback_payload_contract import EXPECTED_TOOLS, REPO_ROOT
from tests.test_completion_seam import EXPECTED_REQUIRED

#: The one case class each tool's ``tests/test_app.py`` must carry.
CASE_CLASS = "TestCompletionSeam"

#: Tool package -> the entry point its processor publishes the completion from.
EXPECTED_PUBLISHERS: Mapping[str, str] = {
    "album_art_normalizer": (
        "album_art_normalizer.core.file_processor.run_normalization"
    ),
    "album_genre_tagger": "album_genre_tagger.core.consolidator.run_analysis",
    "audio_enhancer": "audio_enhancer.core.file_processor.run_enhancement",
    "audio_fingerprinter": (
        "audio_fingerprinter.core.file_processor.run_fingerprinting"
    ),
    "audio_normalizer": "audio_normalizer.core.file_processor.run_parallel_process",
    "audio_refinery": "audio_refinery.core.file_processor.run_pipeline",
    "bpm_analyzer": "bpm_analyzer.core.file_processor.run_analysis",
    "genre_sync": "genre_sync.core.file_processor.run_processing",
    "lyrics_manager": "lyrics_manager.core.file_processor.run_fetch",
    "metadata_scrubber": "metadata_scrubber.core.scrubber.run_scrubbing",
    "music_format_converter": (
        "music_format_converter.core.file_processor.run_conversion"
    ),
    "replaygain_analyzer": "replaygain_analyzer.core.file_processor.run_analysis",
    "silence_trimmer": "silence_trimmer.core.file_processor.run_trimming",
    "tempo_analyzer": "tempo_analyzer.core.file_processor.run_analysis",
}

#: Fields the shared completion helpers publish on a tool's behalf:
#: ``_emit_completion`` (parallel/CPU pools and ``run_analysis_workflow``) and
#: ``run_inplace_dsp_batch`` (the in-place DSP tools).
SHARED_COMPLETION_FIELDS: frozenset[str] = frozenset(
    {
        "total",
        "processed",
        "skipped",
        "errors",
        "duration_secs",
        "log_entries",
    }
)

#: Fields the app's own wiring lambda adds, so a handler may require one
#: without any processor publishing it.
WIRING_FIELDS: frozenset[str] = frozenset(
    {"header", "delete", "is_live", "preserve_list"}
)

#: Local names a processor builds its completion dict in.
_PAYLOAD_NAMES: frozenset[str] = frozenset({"completion", "cb_kwargs", "payload"})

#: Calls that mean "this entry point delegates its completion to a shared
#: helper", so an empty local publish set is explained rather than vacuous.
_SHARED_RUNNERS: tuple[str, ...] = (
    "_emit_completion(",
    "run_parallel_processing(",
    "run_cpu_bound_processing(",
    "run_analysis_workflow(",
    "run_inplace_dsp_batch(",
)


def _app_class_by_package() -> dict[str, str]:
    """Return ``tool package -> app class`` from the contract lock's table."""
    mapping: dict[str, str] = {}
    for path, class_name in EXPECTED_TOOLS:
        mapping[Path(path).parts[0]] = class_name
    return mapping


def _publisher_symbol(entry_point: str) -> tuple[str, str]:
    """Split ``"pkg.core.file.processor.run_x"`` into ``(module, attribute)``."""
    module, _, attribute = entry_point.rpartition(".")
    return module, attribute


def _module_source(module: str) -> str:
    """Return the source text of the module a publisher lives in."""
    path = REPO_ROOT / Path(*module.split("."))
    source = path.with_suffix(".py")
    if not source.is_file():
        pytest.fail(f"{module}: no source file at {source}")
    return source.read_text(encoding="utf-8")


def _function_node(tree: ast.Module, name: str) -> ast.FunctionDef:
    """Return the top-level ``def name`` node, or fail with the names found."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    defined = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    pytest.fail(f"no top-level def {name!r} (found: {defined})")


def _published_fields(tree: ast.Module, function: ast.FunctionDef) -> set[str]:
    """Return the completion field names *function* publishes.

    Collects the keyword names of every ``*complete(`` call and the string keys
    of any dict literal bound to one of ``_PAYLOAD_NAMES`` -- the two shapes the
    tree uses to hand a payload to ``on_complete``.
    """
    published: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            func = node.func
            called = (
                func.attr
                if isinstance(func, ast.Attribute)
                else func.id
                if isinstance(func, ast.Name)
                else ""
            )
            if called.endswith("complete"):
                published.update(
                    keyword.arg for keyword in node.keywords if keyword.arg
                )
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {
                target.id
                if isinstance(target, ast.Name)
                else getattr(target, "attr", "")
                for target in targets
            }
            if not names & _PAYLOAD_NAMES or not isinstance(node.value, ast.Dict):
                continue
            published.update(
                key.value
                for key in node.value.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
    return published


def _case_class(tool_package: str) -> ast.ClassDef:
    """Return the tool's ``TestCompletionSeam`` node, or fail naming the file."""
    path = REPO_ROOT / tool_package / "tests" / "test_app.py"
    if not path.is_file():
        pytest.fail(f"{tool_package}: no tests/test_app.py at {path}")
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == CASE_CLASS:
            return node
    pytest.fail(f"{tool_package}: {path.name} has no {CASE_CLASS} case class")


def _names_in(node: ast.AST) -> set[str]:
    """Return every identifier and attribute name referenced inside *node*."""
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            found.add(child.id)
        elif isinstance(child, ast.Attribute):
            found.add(child.attr)
    return found


def test_the_table_covers_every_gui_tool() -> None:
    """The publisher table is exactly the contract lock's tool set."""
    expected = set(_app_class_by_package())
    assert set(EXPECTED_PUBLISHERS) == expected, (
        "publisher table is out of step with EXPECTED_TOOLS: "
        f"missing={sorted(expected - set(EXPECTED_PUBLISHERS))} "
        f"stale={sorted(set(EXPECTED_PUBLISHERS) - expected)}"
    )
    assert len(EXPECTED_PUBLISHERS) >= 14, len(EXPECTED_PUBLISHERS)


@pytest.mark.parametrize(("tool", "entry_point"), sorted(EXPECTED_PUBLISHERS.items()))
def test_every_entry_point_resolves(tool: str, entry_point: str) -> None:
    """A declared publisher must be a real, callable attribute."""
    module_name, attribute = _publisher_symbol(entry_point)
    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute, None)), (
        f"{tool}: {entry_point} is not a callable attribute of {module_name}"
    )


@pytest.mark.parametrize("tool", sorted(EXPECTED_PUBLISHERS))
def test_every_tool_has_a_publisher_case(tool: str) -> None:
    """The tool's own ``test_app.py`` drives that entry point in a seam case."""
    case = _case_class(tool)
    tests = [
        node
        for node in case.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    ]
    assert tests, f"{tool}: {CASE_CLASS} has no test methods"
    _, attribute = _publisher_symbol(EXPECTED_PUBLISHERS[tool])
    assert attribute in _names_in(case), (
        f"{tool}: {CASE_CLASS} never mentions {attribute!r}, so it does not "
        "drive the tool's real completion entry point"
    )


@pytest.mark.parametrize(("tool", "entry_point"), sorted(EXPECTED_PUBLISHERS.items()))
def test_every_required_field_is_published(tool: str, entry_point: str) -> None:
    """A field its handler requires must come from the processor or the wiring."""
    module_name, attribute = _publisher_symbol(entry_point)
    tree = ast.parse(_module_source(module_name))
    function = _function_node(tree, attribute)
    published = _published_fields(tree, function)

    assert published or any(
        runner in ast.unparse(function) for runner in _SHARED_RUNNERS
    ), (
        f"{tool}: {attribute} publishes no completion fields and reaches no "
        "shared runner"
    )

    app_class = _app_class_by_package()[tool]
    required = set(EXPECTED_REQUIRED[app_class]) - WIRING_FIELDS
    missing = required - published - SHARED_COMPLETION_FIELDS
    assert not missing, (
        f"{tool}: {attribute} does not publish {sorted(missing)}, which "
        f"{app_class}._on_complete requires"
    )
