"""
Tests for file_reorganizer.core.pattern — the path resolver's security contract.

Security finding R-03: a tag value is untrusted input. Before this contract,
``resolve_path("../../evil", {})`` returned ``"..\\..\\evil"`` and the engine
joined it to the destination directory, so a tag could write outside the tree
the user chose. The resolver now refuses a traversal component, a drive-letter
prefix and a UNC share instead of rewriting them.

The refusal is a contract about the *returned value*: it is relative and
traversal-free, or the call raises. A leading separator is deliberately not
refused — an empty leading tag produces one, and the result is stripped to a
relative path below ``base_dir`` either way, so it cannot escape.

Changed in 2.1.2: new file, holding the R-03 traversal-refusal contract for
``file_reorganizer.core.pattern``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from file_reorganizer.core.pattern import PatternError, resolve_path

# ── Refusals ──────────────────────────────────────────────────────────────────

TRAVERSAL_VALUES = [
    "../../evil",
    "..\\..\\evil",
    "../x",
    "..",
    "../",
    "a/../b",
    "album/../../evil",
    "./x",
]


class TestTraversalIsRefused:
    @pytest.mark.parametrize("value", TRAVERSAL_VALUES)
    def test_traversal_component_raises(self, value: str) -> None:
        with pytest.raises(PatternError, match="not allowed"):
            resolve_path(value, {})

    @pytest.mark.parametrize("value", ["..", "../x", "a/../.."])
    def test_tag_value_cannot_walk_up(self, value: str) -> None:
        """The same refusal when the traversal arrives through a tag."""
        with pytest.raises(PatternError):
            resolve_path("%album%/%title%", {"album": value, "title": "T"})

    def test_drive_prefix_raises(self) -> None:
        with pytest.raises(PatternError, match="Drive-qualified"):
            resolve_path("C:\\Windows\\x", {})

    def test_drive_prefix_through_a_tag_raises(self) -> None:
        with pytest.raises(PatternError, match="Drive-qualified"):
            resolve_path("%album%/%title%", {"album": "D:", "title": "x"})

    @pytest.mark.parametrize("value", ["\\\\server\\share\\x", "//server/share/x"])
    def test_unc_prefix_raises(self, value: str) -> None:
        with pytest.raises(PatternError, match="UNC"):
            resolve_path(value, {})

    def test_error_names_the_offending_value(self) -> None:
        with pytest.raises(PatternError) as exc:
            resolve_path("%album%", {"album": "../../evil"})
        assert ".." in str(exc.value)


# ── The returned value is always contained ──────────────────────────────────


class TestResultIsContained:
    def test_normal_path_is_unchanged(self) -> None:
        result = resolve_path(
            "%artist%/%album%/%title%",
            {
                "artist": "Aphex Twin",
                "album": "Selected Ambient Works",
                "title": "Xtal",
            },
        )
        assert result == os.sep.join(["Aphex Twin", "Selected Ambient Works", "Xtal"])

    def test_separator_inside_a_tag_still_splits(self) -> None:
        """AC/DC keeps its historic meaning: the slash is a path separator."""
        result = resolve_path("%artist%/%album%", {"artist": "AC/DC", "album": "X"})
        assert result == os.sep.join(["AC", "DC", "X"])

    def test_empty_leading_tag_still_resolves_below_base(self) -> None:
        """`%albumartist%/%album%` with no albumartist must not now raise."""
        result = resolve_path("%albumartist%/%album%", {"album": "Album"})
        assert result == "Album"

    def test_all_empty_pattern_still_resolves_empty(self) -> None:
        """The engine skips an empty path; that contract is unchanged."""
        assert resolve_path("///", {}) == ""

    def test_base_dir_is_applied_and_stays_inside(self, tmp_path: Path) -> None:
        base = tmp_path / "library"
        result = resolve_path(
            "%album%/%title%", {"album": "A", "title": "T"}, base_dir=str(base)
        )
        candidate = Path(result)
        assert candidate.resolve().is_relative_to(base.resolve())

    def test_absolute_tag_value_cannot_escape_the_base(self, tmp_path: Path) -> None:
        """`/etc/passwd` is re-rooted under base_dir, never used as a root."""
        base = tmp_path / "library"
        result = resolve_path("%title%", {"title": "/etc/passwd"}, base_dir=str(base))
        assert Path(result).resolve().is_relative_to(base.resolve())
        assert Path(result).resolve() != Path(os.sep)
