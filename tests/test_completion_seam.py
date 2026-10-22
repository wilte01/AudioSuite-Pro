"""Every GUI tool's completion handler must fail loudly when a field it needs is gone.

Changed in 1.4.1: added, one seam case per GUI tool plus the frozen field table.
Changed in 2.0.0: the table covers 15 GUI tools; ``stem_separator`` joins it
with its separated/files-written/output/device fields (Sprint 6, Item 6.1).

The completion seam deliberately tolerates unknown fields (``**_extra``, see
``tests/test_callback_payload_contract.py``), so a processor that renames a
field no longer crashes there.  That trade is only safe while the fields a
handler actually uses stay *required*: Python then raises ``TypeError: ...
missing 1 required positional argument: '<field>'`` naming the field, and the
run ends with a visible error instead of a report built from a default.  A
default is precisely how a dropped field goes silent -- ``errors: int = 0``
renders a clean "Errors: 0" summary from a payload that never carried the count.

Two cases per tool:

* the handler's required parameters are exactly ``EXPECTED_REQUIRED``, so
  adding or removing a required field -- or giving one a default -- is a
  deliberate table change rather than an accident;
* dropping any single required field raises ``TypeError`` naming that field.

``EXPECTED_REQUIRED`` records the contract, not the toolbar: optional additions
that default to ``None`` (``isrc_submission``, ``format_counts``,
``outside_range_files``) are absent because their absence is handled.
ReplayGain Analyzer's ``skipped``/``errors``/``duration_secs``/``log_entries``
defaulted until 1.4.1, which made its own errors count and total time render as
``0``/``00:00`` from a payload that never carried them; they are required now,
so its ``TestCompletionSeam`` cases send every field the handler declares.

What this cannot prove: that the processor still *sends* every field.  A field
whose handler requires it but whose publisher stopped sending it fails at
runtime by design -- loudly, which is the behaviour pinned here.  Supplying it
is covered by each tool's own ``test_app.py`` seam test driving the real
``run_*`` into the handler it binds, and -- since 2.0.0 -- statically by
``tests/test_completion_payload_published.py``, which fails when any tool's
wiring reads a completion field with a default instead of forwarding the
published payload (the silent zero this table's counterpart cannot see).

Changed in 2.0.0: points at the published-payload lock; the seam itself is
unchanged.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Any

import pytest

from tests.test_callback_payload_contract import REPO_ROOT, WIRINGS

#: Fields each tool's completion handler must receive; dropping one raises.
#: Keyed by the class that wires the callbacks (``LyricsManagerApp`` inherits
#: its handler from ``AnalysisTagToolApp``).
EXPECTED_REQUIRED: dict[str, frozenset[str]] = {
    "ArtNormalizerApp": frozenset(
        {"total", "processed", "skipped", "errors", "duration_secs", "log_entries"}
    ),
    "AudioEnhancerApp": frozenset(
        {"total", "done", "errors", "duration_secs", "results"}
    ),
    "AudioNormalizerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "AudioRefineryApp": frozenset(
        {
            "total",
            "processed",
            "succeeded",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "BPMAnalyzerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "FingerprinterApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "results",
            "counts",
        }
    ),
    "GenreConsolidatorApp": frozenset(
        {
            "total",
            "files_with_genre",
            "coverage_pct",
            "unique_genres",
            "album_genre_string",
            "write_count",
            "write_errors",
            "read_errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "GenreSetterApp": frozenset(
        {
            "total",
            "updated",
            "skipped",
            "no_genre",
            "errors",
            "duration_secs",
            "log_updated",
            "log_skipped",
            "log_no_genre",
            "log_errors",
        }
    ),
    "LyricsManagerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "MetadataScrubberApp": frozenset(
        {
            "header",
            "is_live",
            "preserve_list",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "MusicFormatConverterApp": frozenset(
        {
            "header",
            "delete",
            "total",
            "processed",
            "converted",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "output_dir",
        }
    ),
    "ReplayGainAnalyzerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "SilenceTrimmerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
    "StemSeparatorApp": frozenset(
        {
            "total",
            "processed",
            "separated",
            "files_written",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
            "output_dir",
            "device",
        }
    ),
    "TempoAnalyzerApp": frozenset(
        {
            "header",
            "total",
            "processed",
            "skipped",
            "errors",
            "duration_secs",
            "log_entries",
        }
    ),
}

#: One completion wiring per GUI tool, resolved by the static contract lock.
COMPLETION_WIRINGS = {
    wiring.class_name: wiring for wiring in WIRINGS if wiring.seam == "complete"
}


def _module_name(path: Path) -> str:
    """Return the dotted module name for a wiring's file path."""
    return path.relative_to(REPO_ROOT).with_suffix("").as_posix().replace("/", ".")


def _handler(tool: str) -> tuple[type[Any], Any]:
    """Import *tool*'s app class and return ``(class, bound handler function)``.

    The import happens inside the test, never at collection, so the apps'
    module-level setup (logging, config) runs under the suite's fixtures.
    """
    wiring = COMPLETION_WIRINGS[tool]
    module = importlib.import_module(_module_name(wiring.path))
    cls = getattr(module, tool)
    return cls, getattr(cls, wiring.handler_name)


def _required(fn: Any) -> set[str]:
    """Return the parameters *fn* refuses to run without."""
    signature = inspect.signature(fn)
    return {
        name
        for name, param in signature.parameters.items()
        if name != "self"
        and param.kind in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY)
        and param.default is param.empty
    }


def test_the_seam_table_covers_every_gui_tool() -> None:
    """A partial table would leave tools silently untested."""
    assert len(COMPLETION_WIRINGS) == 15
    assert set(EXPECTED_REQUIRED) == set(COMPLETION_WIRINGS)


@pytest.mark.parametrize("tool", sorted(EXPECTED_REQUIRED))
def test_completion_contract_is_the_required_field_set(tool: str) -> None:
    """The handler's required fields are the contract, not an accident."""
    _cls, fn = _handler(tool)
    assert _required(fn) == EXPECTED_REQUIRED[tool], (
        f"{tool}._on_complete now requires {sorted(_required(fn))}; if the "
        "change is intended, update EXPECTED_REQUIRED.  A field that gained a "
        "default stops failing loudly when the processor omits it."
    )


@pytest.mark.parametrize("tool", sorted(EXPECTED_REQUIRED))
def test_dropping_a_required_field_raises_with_its_name(tool: str) -> None:
    """Each field, absent from the payload, stops the callback by name."""
    cls, fn = _handler(tool)
    required = _required(fn)
    assert required, f"{tool}._on_complete declares no required completion field"

    instance = object.__new__(cls)
    for field in sorted(required):
        payload = {name: object() for name in required if name != field}
        with pytest.raises(TypeError) as caught:
            fn(instance, **payload)
        assert field in str(caught.value), (
            f"dropping {field!r} from {tool}'s completion payload raised "
            f"{caught.value!r}, which does not name the field a log reader "
            "needs to trace the failure"
        )


def test_a_defaulted_field_is_not_treated_as_required() -> None:
    """The probe must see a default, or the table could hide a silent field."""

    def handler(
        self: object, total: int = 0, errors: int = 0, **_extra: Any
    ) -> None: ...

    assert _required(handler) == set()
