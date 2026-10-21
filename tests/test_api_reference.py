"""Gate: every ``audio_suite_shared`` module appears in the API reference.

PLAN_feature_expansion P3. `docs/api.rst` listed 11 of the 62 shared modules,
so a tool author looking for the log handlers or the tag-helper tiers found
nothing, and — worse — 51 modules were never parsed by the docs build at all
(which is why P2's parser gate could not have caught their warts). The list is
now exhaustive, and this test keeps it that way: a new shared module that ships
without a reference entry fails here, and so does a stale entry for a module
that no longer exists.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "audio_suite_shared"
API_RST = ROOT / "docs" / "api.rst"

_AUTOMODULE = re.compile(
    r"^\.\. automodule:: audio_suite_shared\.(\w+)\s*$", re.MULTILINE
)


def _documented() -> list[str]:
    """Modules named by an ``automodule`` directive in the reference."""
    return _AUTOMODULE.findall(API_RST.read_text(encoding="utf-8"))


def _shipped() -> set[str]:
    """Modules that exist in the package, excluding the package initialiser."""
    return {path.stem for path in PACKAGE.glob("*.py")} - {"__init__"}


def test_every_shared_module_is_documented() -> None:
    documented = set(_documented())
    shipped = _shipped()

    # An empty scan must fail loudly: this is the trap that let a
    # wrongly-scoped walk pass vacuously in an earlier remediation.
    assert shipped, "no modules found in audio_suite_shared"
    assert documented, "no automodule directives found in docs/api.rst"

    missing = sorted(shipped - documented)
    assert not missing, (
        "these shared modules ship without an entry in docs/api.rst: "
        + ", ".join(missing)
    )


def test_the_reference_has_no_stale_entries() -> None:
    stale = sorted(set(_documented()) - _shipped())
    assert not stale, (
        "docs/api.rst documents modules that no longer exist: " + ", ".join(stale)
    )


def test_each_module_is_listed_once() -> None:
    documented = _documented()
    duplicates = sorted({name for name in documented if documented.count(name) > 1})
    assert not duplicates, (
        "docs/api.rst renders these modules more than once, which makes every "
        "cross-reference to them ambiguous: " + ", ".join(duplicates)
    )
