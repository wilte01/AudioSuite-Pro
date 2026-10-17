"""Tests for audio_suite_shared.run_outcome.

Changed in 1.2.0: initial version, covering the channel that puts a tool's
one-line caveat (a refused ISRC submission) on the Master Driver's step line.

Every test points ``AUDIOSUITE_LOG_DIR`` at its own ``tmp_path``, so the notes
land in a scratch directory rather than the session's shared log tree: a note
is keyed by tool id alone, and one test's leftover would otherwise be readable
by another's ``read_outcome`` call.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from audio_suite_shared import run_outcome


@pytest.fixture(autouse=True)
def _isolated_notes_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the channel at a per-test log directory."""
    monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
    return tmp_path


class TestOutcomePath:
    def test_lives_under_the_logs_directory(self, _isolated_notes_dir: Path) -> None:
        path = run_outcome.outcome_path("fingerprinter")

        assert path == (
            _isolated_notes_dir / run_outcome.OUTCOME_DIR_NAME / "fingerprinter.json"
        )

    @pytest.mark.parametrize("tool_id", ["", "..", "../evil", "a/b", "a\\b", "a b"])
    def test_refuses_ids_that_could_escape_the_directory(self, tool_id: str) -> None:
        """The id becomes a file name, so a path separator is refused, not trusted."""
        with pytest.raises(ValueError):
            run_outcome.outcome_path(tool_id)

    def test_rejected_id_writes_nothing(
        self, _isolated_notes_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Recording under a bad id must leave the tree alone."""
        with pytest.raises(ValueError):
            run_outcome.record_outcome("../escape", "note")

        assert not (_isolated_notes_dir.parent / "escape.json").exists()
        assert not (_isolated_notes_dir / run_outcome.OUTCOME_DIR_NAME).exists()


class TestRecordAndRead:
    def test_round_trip(self, _isolated_notes_dir: Path) -> None:
        note = "ISRC submission: rejected (2 ISRC(s), 1 recording(s))"

        run_outcome.record_outcome("fingerprinter", note)

        assert run_outcome.read_outcome("fingerprinter") == note
        payload = json.loads(
            (
                _isolated_notes_dir
                / run_outcome.OUTCOME_DIR_NAME
                / "fingerprinter.json"
            ).read_text(encoding="utf-8")
        )
        assert payload["tool_id"] == "fingerprinter"
        assert payload["note"] == note
        assert payload["recorded"]

    def test_non_ascii_note_survives(self) -> None:
        note = "ISRC submission: not authorised \u2014 HTTP 403"

        run_outcome.record_outcome("fingerprinter", note)

        assert run_outcome.read_outcome("fingerprinter") == note

    def test_note_is_collapsed_to_one_line(self) -> None:
        run_outcome.record_outcome(
            "fingerprinter", "rejected:\n  HTTP 400\n\n  see log"
        )

        assert run_outcome.read_outcome("fingerprinter") == "rejected: HTTP 400 see log"

    def test_long_note_is_truncated_to_the_reporting_budget(self) -> None:
        run_outcome.record_outcome(
            "fingerprinter", "x" * (run_outcome.MAX_NOTE_CHARS * 2)
        )

        note = run_outcome.read_outcome("fingerprinter")

        assert len(note) == run_outcome.MAX_NOTE_CHARS
        assert note.endswith("...")

    def test_empty_note_clears_the_record(self) -> None:
        run_outcome.record_outcome("fingerprinter", "rejected")

        run_outcome.record_outcome("fingerprinter", "   \n  ")

        assert run_outcome.read_outcome("fingerprinter") == ""

    def test_record_overwrites_an_earlier_note(self) -> None:
        run_outcome.record_outcome("fingerprinter", "rejected")
        run_outcome.record_outcome("fingerprinter", "offline")

        assert run_outcome.read_outcome("fingerprinter") == "offline"

    def test_notes_are_per_tool(self) -> None:
        run_outcome.record_outcome("fingerprinter", "rejected")
        run_outcome.record_outcome("replaygain", "clipping")

        assert run_outcome.read_outcome("fingerprinter") == "rejected"
        assert run_outcome.read_outcome("replaygain") == "clipping"


class TestReadIsTotal:
    def test_missing_note_reads_as_empty(self) -> None:
        assert run_outcome.read_outcome("fingerprinter") == ""

    def test_malformed_json_reads_as_empty(self, _isolated_notes_dir: Path) -> None:
        path = run_outcome.outcome_path("fingerprinter")
        path.parent.mkdir(parents=True)
        path.write_text("{not json", encoding="utf-8")

        assert run_outcome.read_outcome("fingerprinter") == ""

    def test_json_that_is_not_an_object_reads_as_empty(
        self, _isolated_notes_dir: Path
    ) -> None:
        path = run_outcome.outcome_path("fingerprinter")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(["rejected"]), encoding="utf-8")

        assert run_outcome.read_outcome("fingerprinter") == ""

    def test_non_string_note_reads_as_empty(self, _isolated_notes_dir: Path) -> None:
        path = run_outcome.outcome_path("fingerprinter")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"note": 42}), encoding="utf-8")

        assert run_outcome.read_outcome("fingerprinter") == ""


class TestShortfall:
    """The one wording every tool's caveat count uses."""

    def test_counts_against_the_total(self) -> None:
        assert run_outcome.shortfall(3, 12, "track", "did not rip") == (
            "3 of 12 tracks did not rip"
        )

    def test_singular_count_still_names_the_group_plural(self) -> None:
        # "1 of 40 file did not scrub" reads as a bug; the total is the subject.
        assert run_outcome.shortfall(1, 40, "file", "could not be scrubbed") == (
            "1 of 40 files could not be scrubbed"
        )

    def test_one_with_no_total_is_not_pluralised(self) -> None:
        assert run_outcome.shortfall(1, 0, "file", "was skipped") == (
            "1 file was skipped"
        )

    def test_unknown_total_drops_the_clause(self) -> None:
        assert run_outcome.shortfall(4, 0, "file", "failed") == "4 files failed"


class TestRecordCaveats:
    """A tool states its counts once; the channel decides what is worth saying."""

    def test_joins_every_problem_in_order(self) -> None:
        note = run_outcome.record_caveats(
            "scrubber",
            "2 of 40 files could not be scrubbed",
            "3 of 40 files were skipped",
        )

        assert note == (
            "2 of 40 files could not be scrubbed; 3 of 40 files were skipped"
        )
        assert run_outcome.read_outcome("scrubber") == note

    def test_blank_phrases_are_ignored(self) -> None:
        assert run_outcome.record_caveats("scrubber", "", "   \n", "1 file failed") == (
            "1 file failed"
        )

    def test_a_clean_run_records_nothing_and_clears_an_older_note(self) -> None:
        run_outcome.record_outcome("scrubber", "2 of 40 files could not be scrubbed")

        assert run_outcome.record_caveats("scrubber", "", "") == ""
        assert run_outcome.read_outcome("scrubber") == ""

    def test_long_joined_note_is_collapsed_to_one_bounded_line(self) -> None:
        note = run_outcome.record_caveats("scrubber", *(["x" * 100] * 5))

        assert len(note) <= run_outcome.MAX_NOTE_CHARS
        assert "\n" not in note
        assert run_outcome.read_outcome("scrubber") == note

    def test_unwritable_note_is_swallowed_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A read-only install must not fail a run over a reporting note."""

        def _boom(tool_id: str, note: str) -> None:
            raise OSError("read-only file system")

        monkeypatch.setattr(run_outcome, "record_outcome", _boom)

        assert run_outcome.record_caveats("scrubber", "1 file failed") == ""

    def test_unusable_tool_id_is_not_swallowed(self) -> None:
        """A hand-typed id is a defect: loud here, caught by the id contract."""
        with pytest.raises(ValueError):
            run_outcome.record_caveats("../escape", "1 file failed")


class TestClear:
    def test_clear_removes_the_note(self) -> None:
        run_outcome.record_outcome("fingerprinter", "rejected")

        run_outcome.clear_outcome("fingerprinter")

        assert run_outcome.read_outcome("fingerprinter") == ""
        assert not run_outcome.outcome_path("fingerprinter").exists()

    def test_clear_is_idempotent(self) -> None:
        """The driver clears before every step, including a tool's first run."""
        run_outcome.clear_outcome("fingerprinter")
        run_outcome.clear_outcome("fingerprinter")

        assert run_outcome.read_outcome("fingerprinter") == ""
