"""Tests for the duplicate disposition value and its settings validation.

The value is the one thing that decides whether a file is moved, trashed or
replaced, so every alias and every refusal is pinned here rather than discovered
through a live run.

Changed in 2.4.0: new module (PLAN_duplicate_disposition_2026-11-02.md DD-2).
"""

from __future__ import annotations

import pytest

from duplicate_finder.core.disposition import (
    DEFAULT_DISPOSITION,
    DISPOSITIONS,
    Disposition,
    label_for,
    normalize,
    uses_trash,
)
from duplicate_finder.core.models import ScanSettings


class TestNormalize:
    """One token reaches the file loop, however it was spelled."""

    def test_the_three_canonical_values_round_trip(self) -> None:
        for value in DISPOSITIONS:
            assert normalize(value) == value

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("quarantine", "quarantine"),
            ("MOVE", "quarantine"),
            ("move-to-quarantine", "quarantine"),
            ("delete", "delete"),
            ("Trash", "delete"),
            ("recycle", "delete"),
            ("asx-stub", "asx-stub"),
            ("ASX_STUB", "asx-stub"),
            ("stub", "asx-stub"),
            ("asx", "asx-stub"),
        ],
    )
    def test_aliases_reach_the_canonical_value(self, value: str, expected: str) -> None:
        assert normalize(value) == expected

    def test_an_empty_value_is_the_default(self) -> None:
        assert normalize("") == DEFAULT_DISPOSITION

    def test_an_unknown_value_names_the_allowed_set(self) -> None:
        with pytest.raises(ValueError, match="Unknown duplicate disposition"):
            normalize("shred")

    def test_the_default_is_quarantine(self) -> None:
        assert DEFAULT_DISPOSITION == Disposition.QUARANTINE.value


class TestLabelsAndTrash:
    """The surfaces show a sentence, the scan asks a boolean."""

    def test_every_value_has_a_label(self) -> None:
        assert all(label_for(value) for value in DISPOSITIONS)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("quarantine", False),
            ("delete", True),
            ("asx-stub", True),
        ],
    )
    def test_only_removing_dispositions_use_the_trash(
        self, value: str, expected: bool
    ) -> None:
        assert uses_trash(value) is expected


class TestScanSettings:
    """A hand-built settings object cannot smuggle in an unknown action."""

    def test_the_default_is_quarantine(self) -> None:
        assert ScanSettings().disposition == "quarantine"

    def test_a_valid_value_is_stored_canonically(self) -> None:
        assert ScanSettings(disposition="STUB").disposition == "asx-stub"

    def test_an_unknown_value_is_refused_at_construction(self) -> None:
        with pytest.raises(ValueError, match="Unknown duplicate disposition"):
            ScanSettings(disposition="shred")
