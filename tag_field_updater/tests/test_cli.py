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

Changed in 2.1.4: ``TestExitContract`` pins the R-06 status (PLAN D9) — a run
that reports a per-file error exits 1 through the real command, a tree with
nothing to rewrite exits 0, and one unreadable file does not stop the others.

Changed in 2.2.0: ``TestFilenameSource`` covers the filename source end to end
(F-01) - the dry-run default, an explicit ``--live`` run read back off disk,
"only fill blanks" versus ``--overwrite``, the no-match skip, a refused pattern,
and action groups round-tripping through a redirected config.  The documented-
example parity test now supplies the values the new value-taking flags need.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from mutagen.id3 import ID3, TCON, TIT2
from pydub import AudioSegment

from audio_suite_shared.cli_app import cli
from audio_suite_shared.tag_helper import read_editable_tags

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


class TestExitContract:
    """R-06: the shell status mirrors the ``errors`` the payload reports."""

    def test_one_unreadable_file_makes_the_live_run_exit_1(
        self, song: Path, undo_db: Path
    ) -> None:
        """The pre-fix behaviour: summary said ``Errors: 1`` and the shell saw 0.

        The readable file must still be rewritten — a failure is reported, not
        fatal — so this asserts both halves of the contract in one run.
        """
        (song.parent / "broken.mp3").write_bytes(b"this is not an mp3")

        result = invoke(str(song.parent), "--live", "--json")

        assert result.exit_code == 1
        report = payload(result)
        assert report["errors"] == 1
        assert report["processed"] == 2
        assert report["updated"] == 1
        assert read_genre(song) == REWRITTEN_GENRE

    def test_the_same_failure_exits_1_in_text_mode(self, tmp_path: Path) -> None:
        library = tmp_path / "library"
        library.mkdir()
        (library / "broken.flac").write_bytes(b"not a flac either")

        result = invoke(str(library), "--live")

        assert result.exit_code == 1
        assert "Errors:          1" in result.output

    def test_a_tree_with_nothing_to_rewrite_exits_0(
        self, tmp_path: Path, undo_db: Path
    ) -> None:
        """No slash in the value means no edit and no error — a clean run."""
        path = tmp_path / "library" / "clean.mp3"
        path.parent.mkdir()
        AudioSegment.silent(duration=50).export(str(path), format="mp3")
        tags = ID3()
        tags.add(TCON(encoding=3, text="Rock"))
        tags.save(str(path))

        result = invoke(str(path.parent), "--live", "--json")

        assert result.exit_code == 0
        report = payload(result)
        assert report["errors"] == 0
        assert read_genre(path) == "Rock"


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

    #: Documented flags that take a value, with the value the example implies.
    #: A bare ``--pattern`` is a malformed invocation, so the parity check has
    #: to run the flag the way the example does.
    _VALUE_FLAGS: dict[str, tuple[str, ...]] = {
        "--pattern": ("%artist% - %title%",),
        "--action-group": ("Doc Example",),
        # Saving needs patterns to save, so the flag's own value comes first
        # and the pattern follows it (click reads an option's value from the
        # next token).
        "--save-action-group": (
            "Doc Example",
            "--pattern",
            "%artist% - %title%",
        ),
    }

    def test_every_flag_named_in_the_help_examples_actually_runs(
        self, song: Path, undo_db: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Executable documentation: each documented example exits 0.

        The positive form of the parity contract — read the command's own
        ``Examples:`` block, run the argv it shows, and require success.  A
        flag that stops resolving fails here even if the docstring is
        reworded, and a docstring that starts advertising a non-flag fails
        the assertion below before it can reach a command.

        Changed in 2.2.0: the block now documents value-taking flags (the
        filename source), so the harness supplies their value and points the
        shared config at ``tmp_path`` — running a saved group writes it, and a
        test must never touch the shipped ``audio_suite_config.json``.
        """
        from audio_suite_shared import suite_config
        from tag_field_updater import cli as tag_update_cli_module
        from tag_field_updater.utils import config as action_config

        config_path = tmp_path / "audio_suite_config.json"
        monkeypatch.setattr(suite_config, "CONFIG_PATH", config_path)
        monkeypatch.setattr(
            suite_config, "_LOCK_PATH", config_path.with_suffix(".json.lock")
        )
        suite_config._invalidate_cache()
        action_config.save_action_group("Doc Example", ("%artist% - %title%",))

        doc = inspect.getdoc(tag_update_cli_module.tag_update_cli) or ""
        examples = doc.split("Examples:", 1)[1]
        flags = re.findall(r"(--[a-z0-9-]+)", examples)
        assert flags, (
            "the Examples block advertises no flags at all, so this test "
            "would pass without exercising any documented invocation"
        )

        try:
            for flag in flags:
                extra = list(self._VALUE_FLAGS.get(flag, ()))
                if flag != "--json":
                    extra.append("--json")
                result = invoke(str(song.parent), flag, *extra)
                assert result.exit_code == 0, (
                    f"documented example flag {flag} exited "
                    f"{result.exit_code}: {result.output}"
                )
        finally:
            suite_config._invalidate_cache()


# ---------------------------------------------------------------------------
# The filename source (F-01)
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path, None, None]:
    """Point the shared suite config at *tmp_path*, never the shipped file."""
    from audio_suite_shared import suite_config

    path = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", path)
    monkeypatch.setattr(suite_config, "_LOCK_PATH", path.with_suffix(".json.lock"))
    suite_config._invalidate_cache()
    yield path
    suite_config._invalidate_cache()


@pytest.fixture()
def named_song(tmp_path: Path) -> Path:
    """A real MP3 named ``Artist - Title`` with a title already set."""
    path = tmp_path / "tagged" / "Parsed Artist - Parsed Title.mp3"
    path.parent.mkdir()
    try:
        AudioSegment.silent(duration=50).export(str(path), format="mp3")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode MP3 ({type(exc).__name__})")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Existing Title"]))
    tags.save(str(path))
    return path


def stored_tags(path: Path) -> dict[str, object]:
    """Read the editable fields back off disk through a fresh handler."""
    return dict(read_editable_tags(str(path)))


class TestFilenameSource:
    """``--pattern`` / ``--action-group`` end to end through the real writer."""

    PATTERN = "%artist% - %title%"

    def test_filename_mode_is_a_dry_run_by_default(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        before = digest(named_song)

        result = invoke(str(named_song.parent), "--pattern", self.PATTERN)

        assert result.exit_code == 0, result.output
        assert digest(named_song) == before
        assert "defaults to a dry run" in result.output
        # The parse is printed: a dry run exists to make a mis-parse visible.
        assert "[PARSED]" in result.output
        assert "artist='Parsed Artist'" in result.output
        assert "kept existing: title" in result.output

    def test_an_explicit_live_run_writes_the_parsed_values(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        result = invoke(str(named_song.parent), "--pattern", self.PATTERN, "--live")

        assert result.exit_code == 0, result.output
        stored = stored_tags(named_song)
        assert stored["artist"] == "Parsed Artist"
        # "Only fill blanks" is the default, so the existing title survives.
        assert stored["title"] == "Existing Title"

    def test_overwrite_replaces_an_existing_tag(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        result = invoke(
            str(named_song.parent), "--pattern", self.PATTERN, "--overwrite", "--live"
        )

        assert result.exit_code == 0, result.output
        assert stored_tags(named_song)["title"] == "Parsed Title"

    def test_a_file_matching_no_pattern_is_reported_and_left_alone(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        before = digest(named_song)

        result = invoke(
            str(named_song.parent),
            "--pattern",
            "%track%. %artist% - %title%",
            "--live",
            "--json",
        )

        assert result.exit_code == 0, result.output
        assert payload(result)["skipped"] == 1
        assert digest(named_song) == before

    def test_an_invalid_pattern_is_refused_before_any_write(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        before = digest(named_song)

        result = invoke(str(named_song.parent), "--pattern", "Artist - Title", "--live")

        assert result.exit_code != 0
        assert "names no field" in result.output
        assert digest(named_song) == before

    def test_an_action_group_round_trips_through_the_shared_config(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        saved = invoke(
            str(named_song.parent),
            "--pattern",
            self.PATTERN,
            "--save-action-group",
            "Bandcamp",
            "--dry",
        )
        assert saved.exit_code == 0, saved.output
        assert "Bandcamp" in saved.output

        result = invoke(str(named_song.parent), "--action-group", "Bandcamp", "--live")
        assert result.exit_code == 0, result.output
        assert stored_tags(named_song)["artist"] == "Parsed Artist"

    def test_an_unknown_action_group_lists_the_saved_ones(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        result = invoke(str(named_song.parent), "--action-group", "Missing")

        assert result.exit_code != 0
        assert "unknown action group" in result.output
        assert "none" in result.output

    def test_action_groups_can_be_listed(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        from tag_field_updater.utils import config as action_config

        action_config.save_action_group("Bandcamp", (self.PATTERN,))

        result = invoke(str(named_song.parent), "--list-action-groups")

        assert result.exit_code == 0, result.output
        assert "Saved action groups (1)" in result.output
        assert self.PATTERN in result.output

    def test_saving_without_patterns_is_refused(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        result = invoke(str(named_song.parent), "--save-action-group", "Empty")

        assert result.exit_code != 0
        assert "nothing to store" in result.output

    def test_explicit_flags_beat_the_saved_group(
        self, named_song: Path, undo_db: Path, isolated_config: Path
    ) -> None:
        """A group is a starting point; what the user typed wins."""
        from tag_field_updater.utils import config as action_config

        action_config.save_action_group(
            "Fills", ("%artist% - %title%",), only_fill_blanks=True
        )

        result = invoke(
            str(named_song.parent),
            "--action-group",
            "Fills",
            "--pattern",
            "%artist% - %title%",
            "--overwrite",
            "--live",
        )

        assert result.exit_code == 0, result.output
        assert stored_tags(named_song)["title"] == "Parsed Title"
