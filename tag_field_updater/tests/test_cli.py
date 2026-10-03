"""
test_cli.py — ``audiosuite tag-update`` CLI contract (audit H1, plan A1).

The regression these tests exist for is a *data-integrity* one: ``--dry``
accepted a ``dry_run`` argument, reported ``"dry_run": true`` in its own JSON
payload, and then wrote the tags anyway — every one of the eight format rules
called ``audio.save()`` and ``record_tag_edit_snapshot(...)`` unconditionally.
``tag_field_updater/cli.py`` sat at 48% coverage, so nothing exercised the
path, and ``TestDocumentedFlagParity`` skipped the command entirely because
its docstring carried a plain-text ``Examples:`` block with no bracketed
``[--flag]`` token for the gate to read.

Every assertion here is a **positive** contract stated about the outcome:
what the file on disk now holds, what the JSON reports, and how many undo rows
exist for it.  None of them asserts "nothing happened" — per ``AGENTS.md`` §7
such a test pins whatever the implementation happened not to do.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from mutagen.id3 import ID3, TCON
from pydub import AudioSegment

from audio_suite_shared.cli_app import cli

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

#: The value the fixture file starts with, and the value a live run must
#: produce.  Both are asserted as literals so a change in
#: :func:`tag_field_updater.core.mapping_engine.update_value` is a visible
#: contract change rather than a silently-agreed one.
ORIGINAL_GENRE = "Rock/Pop"
REWRITTEN_GENRE = "Rock; Pop"


@pytest.fixture()
def song(tmp_path: Path) -> Path:
    """A real 50 s MP3 carrying an ``ID3`` genre frame with a bare slash."""
    path = tmp_path / "library" / "probe.mp3"
    path.parent.mkdir()
    AudioSegment.silent(duration=50).export(str(path), format="mp3")
    tags = ID3()
    tags.add(TCON(encoding=3, text=ORIGINAL_GENRE))
    tags.save(str(path))
    return path


def read_genre(path: Path) -> str:
    """Re-read the ``TCON`` frame from disk with a fresh mutagen handle."""
    return str(ID3(str(path))["TCON"])


def digest(path: Path) -> str:
    """SHA-256 of the file's bytes — the strongest "was it rewritten?" check."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def undo_rows_for(undo_db: Path, file_path: Path) -> int:
    """Count the undo-log records written for *file_path*.

    A dry run must add no row: recording a snapshot for a change that never
    happened would offer the user an undo that restores nothing.
    """
    if not undo_db.exists():
        return 0
    conn = sqlite3.connect(str(undo_db))
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM undo_records WHERE file_path = ?",
            (str(file_path),),
        )
        return int(cursor.fetchone()[0])
    finally:
        conn.close()


def invoke(*args: str) -> Result:
    """Invoke the CLI with the tag-update command's arguments."""
    runner = CliRunner()
    return runner.invoke(cli, ["tag-update", *args], catch_exceptions=False)


@pytest.fixture()
def undo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the undo log at a per-test database inside ``tmp_path``."""
    db = tmp_path / "undo.db"
    monkeypatch.setenv("AUDIOSUITE_UNDO_DB", str(db))
    return db


def payload(result: Result) -> dict[str, object]:
    """Parse the command's JSON report from **stdout only**.

    ``Result.output`` is stdout *and* stderr merged in write order, so parsing
    the merged stream is a bet on ordering (``AGENTS.md`` §6 item 11).  The
    contract is "payload on stdout, diagnostics on stderr" — read that channel.
    """
    assert result.stdout.strip(), "the command wrote no JSON to stdout"
    return dict(json.loads(result.stdout))


# ---------------------------------------------------------------------------
# The dry-run write gate
# ---------------------------------------------------------------------------


class TestDryRunWithholdsWrites:
    """``--dry`` must analyse and report without writing anything."""

    def test_dry_run_reports_the_update_it_withheld(
        self, song: Path, undo_db: Path
    ) -> None:
        """The positive dry-run contract: the change is reported, not applied.

        The user has to be able to see what *would* change — a dry run that
        also hides the pending work is useless — so ``updated`` stays 1 while
        the file keeps its original tag.
        """
        result = invoke(str(song.parent), "--dry", "--json")
        assert result.exit_code == 0

        report = payload(result)
        assert report["dry_run"] is True
        assert report["processed"] == 1
        assert report["updated"] == 1

    def test_dry_run_leaves_the_tag_on_disk_unchanged(
        self, song: Path, undo_db: Path
    ) -> None:
        """Re-read the tag with a fresh handle — the audit's exact repro."""
        invoke(str(song.parent), "--dry", "--json")
        assert read_genre(song) == ORIGINAL_GENRE

    def test_dry_run_leaves_the_file_bytes_and_mtime_unchanged(
        self, song: Path, undo_db: Path
    ) -> None:
        """Both the content hash and the mtime must be untouched.

        ``audio.save()`` rewrites the container even when the tag payload is
        byte-identical, so the SHA-256 is what proves the file was never
        opened for writing at all.
        """
        before_digest = digest(song)
        before_mtime = song.stat().st_mtime_ns

        invoke(str(song.parent), "--dry", "--json")

        assert digest(song) == before_digest
        assert song.stat().st_mtime_ns == before_mtime

    def test_dry_run_records_no_undo_row_for_the_file(
        self, song: Path, undo_db: Path
    ) -> None:
        """An undo entry for an unapplied edit is a lie the user can act on."""
        invoke(str(song.parent), "--dry", "--json")
        assert undo_rows_for(undo_db, song) == 0

    def test_dry_run_reports_zero_undo_rows_while_live_records_one(
        self, song: Path, undo_db: Path
    ) -> None:
        """Contrast run: the gate is what withholds the row, not a dead log.

        Without the live half, ``undo_rows_for == 0`` would also hold if the
        undo hook were broken for every mode — a test that passes for the
        wrong reason.
        """
        invoke(str(song.parent), "--live", "--json")
        assert undo_rows_for(undo_db, song) == 1


class TestLiveRunStillWrites:
    """The gate must not turn into "never write"."""

    def test_live_run_rewrites_the_tag_on_disk(self, song: Path, undo_db: Path) -> None:
        result = invoke(str(song.parent), "--live", "--json")
        assert result.exit_code == 0

        report = payload(result)
        assert report["dry_run"] is False
        assert report["updated"] == 1
        assert read_genre(song) == REWRITTEN_GENRE

    def test_live_run_changes_the_file_bytes(self, song: Path, undo_db: Path) -> None:
        before_digest = digest(song)
        invoke(str(song.parent), "--live", "--json")
        assert digest(song) != before_digest

    def test_dry_then_live_applies_the_change_exactly_once(
        self, song: Path, undo_db: Path
    ) -> None:
        """A dry run must leave the file in a state a live run can still act on."""
        invoke(str(song.parent), "--dry", "--json")
        assert read_genre(song) == ORIGINAL_GENRE

        invoke(str(song.parent), "--live", "--json")
        assert read_genre(song) == REWRITTEN_GENRE


class TestDocumentedExampleIsReal:
    """The compounding defect: the help text advertised a flag that never was.

    Click registers ``--dry``/``--live`` (the shared ``--dry/--live`` pair), so
    the documented ``--dry-run`` exited 2 with "No such option".  The docstring
    is now corrected, and ``TestDocumentedFlagParity`` reads ``Examples:``
    blocks so the drift cannot come back unnoticed.
    """

    def test_the_documented_dry_example_resolves(self) -> None:
        from tag_field_updater import cli as tag_update_cli_module

        doc = inspect.getdoc(tag_update_cli_module.tag_update_cli)
        assert doc is not None, "the command lost its help text"
        assert "--dry-run" not in doc, (
            "the help text still advertises --dry-run, which the shared "
            "--dry/--live option pair does not register"
        )
        assert "audiosuite tag-update /Music --dry" in doc

    def test_every_flag_named_in_the_help_examples_actually_runs(
        self, song: Path, undo_db: Path
    ) -> None:
        """Executable documentation: each documented example exits 0.

        The positive form of the parity contract — read the command's own
        ``Examples:`` block, run the argv it shows, and require success.  A
        flag that stops resolving fails here even if the docstring is
        reworded, and a docstring that starts advertising a non-flag fails
        the assertion below before it can reach a command.
        """
        from tag_field_updater import cli as tag_update_cli_module

        doc = inspect.getdoc(tag_update_cli_module.tag_update_cli) or ""
        examples = doc.split("Examples:", 1)[1]
        flags = re.findall(r"(--[a-z0-9-]+)", examples)
        assert flags, (
            "the Examples block advertises no flags at all, so this test "
            "would pass without exercising any documented invocation"
        )

        for flag in flags:
            extra = ["--json"] if flag != "--json" else []
            result = invoke(str(song.parent), flag, *extra)
            assert result.exit_code == 0, (
                f"documented example flag {flag} exited "
                f"{result.exit_code}: {result.output}"
            )
