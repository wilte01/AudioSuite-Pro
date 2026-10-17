"""Locks for ``tests/lock_counts.py``: the generated lock-count inventory.

The CI step that proves the instruction locks on a runner without a user-global
baseline also asserts how many locks each module collects.  That number used to
be typed into the workflow, where nothing in the suite could see it and a typo
could only be discovered by the runner failing for the wrong reason.  The
inventory moves it into an artifact a command produces, and these locks close
the ways such an artifact goes wrong.

Four things are locked:

1. **The committed file is honest.**  It loads, names only real
   ``tests/test_*.py`` modules, records an ISO date, and the live collection is
   inside the band it declares - the same claim the CI step makes, made here so
   a developer sees a stale number before pushing.
2. **The loader refuses.**  Every field is validated, including the shapes that
   would otherwise pass as valid Python: a boolean counts as an integer, and a
   count of zero would turn the floor into a check nothing can fail.
3. **The band is two-sided.**  A shrunken module is reported, a module past its
   cap is reported, and the two boundaries themselves are accepted - so the
   comparison cannot be off by one in either direction.
4. **Recording refuses a failing run.**  Counts are only written when the
   modules pass, because a count taken from a broken tree freezes whatever the
   breakage happened to report.

Changed in 1.1.0: initial version.
Changed in 1.2.0: added with the generated inventory that replaced the counts
declared by hand in the CI workflow.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from tests.lock_counts import (
    INVENTORY,
    LockCountError,
    cap_for,
    collect_counts,
    ensure_passing,
    load_inventory,
    main,
    serialize_inventory,
    violations,
    write_inventory,
)


def _write_module(root: Path, name: str, body: str) -> Path:
    """Create ``root/tests/<name>`` with ``body`` and return its path.

    A temporary tree keeps the refusal tests independent of the repository's own
    modules: they need a module that passes and one that fails, and neither
    should be this suite.
    """
    tests = root / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    path = tests / name
    path.write_text(body, encoding="utf-8")
    return path


_PASSING = "def test_ok() -> None:\n    assert 1 + 1 == 2\n"
_FAILING = "def test_bad() -> None:\n    assert 1 + 1 == 3\n"


class TestCommittedInventory:
    """The file this repository commits describes the locks it actually has."""

    def test_it_records_a_generation_date_that_could_have_happened(self) -> None:
        """The date is not pinned: regenerating on another day must stay green."""
        inventory = load_inventory()
        assert date.fromisoformat(inventory.generated) <= date.today(), (
            "a generation date in the future means the file was hand-edited "
            "rather than produced by a run"
        )
        assert inventory.modules, "an empty inventory would check nothing"

    def test_every_module_it_names_is_a_test_module_that_exists(self) -> None:
        inventory = load_inventory()
        missing = [
            name
            for name in inventory.modules
            if not (INVENTORY.parent.parent / name).is_file()
        ]
        assert not missing, (
            f"the inventory names modules that are not on disk: {missing}"
        )

    def test_the_live_counts_are_inside_their_band(self) -> None:
        """The check a developer can run before pushing, not only on CI."""
        inventory = load_inventory()
        observed = collect_counts(list(inventory.modules))
        assert violations(observed, inventory.modules) == [], (
            "a lock module's collected count is outside the band the inventory "
            "declares; regenerate after an intended change with "
            "`python -m tests.lock_counts --write`"
        )

    def test_check_exits_zero_for_the_committed_inventory(self) -> None:
        assert main(["--check"]) == 0


class TestLoader:
    """A count file must not parse to something weaker than it claims."""

    @staticmethod
    def _payload(**overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "_comment": "counts",
            "_generated": "2026-10-17",
            "modules": {"test_locks.py": 3},
        }
        payload.update(overrides)
        return payload

    def _load(self, tmp_path: Path, payload: dict[str, object]) -> None:
        path = tmp_path / "counts.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(LockCountError):
            load_inventory(path)

    def test_a_missing_file_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(LockCountError, match="does not exist"):
            load_inventory(tmp_path / "absent.json")

    def test_an_unknown_key_is_refused(self, tmp_path: Path) -> None:
        self._load(tmp_path, self._payload(extra=1))

    def test_a_count_that_is_not_an_integer_is_refused(self, tmp_path: Path) -> None:
        self._load(tmp_path, self._payload(modules={"test_locks.py": "3"}))

    def test_a_boolean_count_is_refused(self, tmp_path: Path) -> None:
        """``True`` is an ``int`` in Python, and would record a count of one."""
        self._load(tmp_path, self._payload(modules={"test_locks.py": True}))

    def test_a_zero_count_is_refused(self, tmp_path: Path) -> None:
        self._load(tmp_path, self._payload(modules={"test_locks.py": 0}))

    def test_a_module_name_outside_the_tests_directory_is_refused(
        self, tmp_path: Path
    ) -> None:
        self._load(tmp_path, self._payload(modules={"../test_locks.py": 3}))

    def test_a_generated_date_that_is_not_iso_is_refused(self, tmp_path: Path) -> None:
        self._load(tmp_path, self._payload(_generated="17/10/2026"))

    def test_the_valid_payload_is_accepted(self, tmp_path: Path) -> None:
        """Positive control: the refusals above are refusals, not normalcy."""
        path = tmp_path / "counts.json"
        path.write_text(json.dumps(self._payload()), encoding="utf-8")
        assert load_inventory(path).modules == {"test_locks.py": 3}


class TestBand:
    """Both bounds are enforced, and each boundary value is accepted."""

    @pytest.mark.parametrize(
        ("floor", "cap"),
        [(1, 2), (5, 6), (21, 26), (43, 52)],
    )
    def test_the_cap_allows_a_fifth(self, floor: int, cap: int) -> None:
        assert cap_for(floor) == cap

    def test_a_module_below_its_floor_is_reported(self) -> None:
        problems = violations({"test_locks.py": 20}, {"test_locks.py": 21})
        assert problems and "below its floor of 21" in problems[0]

    def test_a_module_at_its_floor_is_accepted(self) -> None:
        assert violations({"test_locks.py": 21}, {"test_locks.py": 21}) == []

    def test_a_module_at_its_cap_is_accepted(self) -> None:
        assert violations({"test_locks.py": 26}, {"test_locks.py": 21}) == []

    def test_a_module_one_past_its_cap_is_reported(self) -> None:
        problems = violations({"test_locks.py": 27}, {"test_locks.py": 21})
        assert problems and "past its cap of 26" in problems[0]

    def test_a_module_that_disappeared_is_reported(self) -> None:
        problems = violations({"test_other.py": 5}, {"test_locks.py": 21})
        assert problems and "not collected at all" in problems[0]


class TestWriter:
    """One file shape, so regeneration is a one-line diff."""

    def test_it_writes_utf8_without_a_bom_and_with_crlf(self, tmp_path: Path) -> None:
        payload = write_inventory(
            {"test_locks.py": 3}, path=tmp_path / "counts.json", generated="2026-10-17"
        )
        assert not payload.startswith(b"\xef\xbb\xbf")
        assert payload.count(b"\n") == payload.count(b"\r\n")
        assert payload.endswith(b"\r\n")

    def test_what_it_writes_loads_back(self, tmp_path: Path) -> None:
        path = tmp_path / "counts.json"
        write_inventory(
            {"test_locks.py": 3, "test_more.py": 9}, path=path, generated="2026-10-17"
        )
        assert load_inventory(path).modules == {
            "test_locks.py": 3,
            "test_more.py": 9,
        }

    def test_it_orders_modules_for_a_stable_diff(self, tmp_path: Path) -> None:
        payload = serialize_inventory(
            {"test_zzz.py": 1, "test_aaa.py": 2}, generated="2026-10-17"
        )
        assert payload.index(b"test_aaa.py") < payload.index(b"test_zzz.py")


class TestRecording:
    """Counts come from a passing run, never from whatever is on disk."""

    def test_a_passing_module_is_accepted(self, tmp_path: Path) -> None:
        _write_module(tmp_path, "test_probe.py", _PASSING)
        ensure_passing(["test_probe.py"], root=tmp_path)
        assert collect_counts(["test_probe.py"], root=tmp_path) == {"test_probe.py": 1}

    def test_a_failing_module_is_refused(self, tmp_path: Path) -> None:
        _write_module(tmp_path, "test_probe.py", _FAILING)
        with pytest.raises(LockCountError, match="refusing to record counts"):
            ensure_passing(["test_probe.py"], root=tmp_path)

    def test_a_module_that_cannot_be_collected_is_refused(self, tmp_path: Path) -> None:
        _write_module(tmp_path, "test_probe.py", _PASSING)
        with pytest.raises(LockCountError, match="cannot collect"):
            collect_counts(["test_missing.py"], root=tmp_path)

    def test_check_fails_when_a_listed_module_cannot_be_collected(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "counts.json"
        write_inventory({"test_missing_locks.py": 3}, path=path, generated="2026-10-17")
        assert main(["--check", "--inventory", str(path)]) == 1
