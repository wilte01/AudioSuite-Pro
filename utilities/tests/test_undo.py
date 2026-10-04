"""Tests for utilities/undo.py — the command-line undo batch CLI."""

import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from utilities import undo  # noqa: E402


class _StubHandler:
    """Minimal tag handler whose raw tags round-trip through pickle."""

    def __init__(self, raw_tags: dict) -> None:
        self.raw_tags = dict(raw_tags)

    def get_raw_tags(self) -> dict:
        return self.raw_tags

    def set_raw_tags(self, raw_tags: dict) -> None:
        self.raw_tags = dict(raw_tags)

    def save(self) -> None:
        pass


def _seed_tag_batch(db: Path, file_path: Path) -> str:
    """Create a tag-edit batch with one snapshot record; return its id."""
    from audio_suite_shared.batch_undo import active_batch, record_tag_edit_snapshot

    handler = _StubHandler({"TXXX:MOOD": "sad"})
    factory = MagicMock()
    factory.get_handler.return_value = handler
    with (
        patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory),
        active_batch("mood_analysis_batch_tagger", "tag_edit", db_path=db) as batch_id,
    ):
        record_tag_edit_snapshot(str(file_path), "write_mood")
    return batch_id


def _seed_overwrite_batch(db: Path, file_path: Path) -> str:
    """Create an in-place-audio batch with one byte-level record."""
    from audio_suite_shared.batch_undo import (
        active_batch,
        record_audio_overwrite_snapshot,
    )

    with active_batch("noise_reduction", "audio_overwrite", db_path=db) as batch_id:
        record_audio_overwrite_snapshot(str(file_path), "noise_reduce_edit")
    return batch_id


def _seed_move_batch(db: Path, src: Path, dst: Path, action: str = "move") -> str:
    """Create a file-reorg batch with one file record; return its id."""
    from audio_suite_shared.batch_undo import active_batch, record_file_reorg_snapshot

    with active_batch("file_reorganizer", "file_reorg", db_path=db) as batch_id:
        record_file_reorg_snapshot(str(src), str(dst), action)
    return batch_id


class TestList:
    def test_prints_batches_newest_first(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        _seed_tag_batch(db, tmp_path / "a.mp3")
        move_src = tmp_path / "song.mp3"
        move_src.touch()
        move_dst = tmp_path / "sorted" / "song.mp3"
        move_dst.parent.mkdir()
        move_src.replace(move_dst)
        _seed_move_batch(db, move_src, move_dst)

        assert undo._cmd_list(Namespace(limit=20, db=db)) == 0
        out = capsys.readouterr().out
        assert "mood_analysis_batch_tagger/tag_edit" in out
        assert "file_reorganizer/file_reorg" in out
        assert "1 record(s)" in out

    def test_empty_log_reports_info(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        assert undo._cmd_list(Namespace(limit=20, db=db)) == 0
        assert "[INFO] No undo batches found." in capsys.readouterr().out

    def test_limit_applied(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        for name in ("one.mp3", "two.mp3"):
            f = tmp_path / name
            f.touch()
            _seed_tag_batch(db, f)
        assert undo._cmd_list(Namespace(limit=1, db=db)) == 0
        lines = capsys.readouterr().out.strip().splitlines()
        assert len(lines) == 1


class TestShow:
    def test_shows_move_record(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        src = tmp_path / "song.mp3"
        dst = tmp_path / "sorted" / "song.mp3"
        batch_id = _seed_move_batch(db, src, dst)

        assert undo._cmd_show(Namespace(batch_id=batch_id, db=db)) == 0
        out = capsys.readouterr().out
        assert "move:" in out
        assert str(src) in out
        assert str(dst) in out

    def test_shows_tag_edit_with_snapshot(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        batch_id = _seed_tag_batch(db, mp3)

        assert undo._cmd_show(Namespace(batch_id=batch_id, db=db)) == 0
        out = capsys.readouterr().out
        assert "write_mood [snapshot]" in out
        assert str(mp3) in out

    def test_unknown_batch_errors(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        assert undo._cmd_show(Namespace(batch_id="deadbeef", db=db)) == 1
        assert "[ERROR] Unknown batch" in capsys.readouterr().err

    def test_shows_in_place_audio_record_as_audio_bytes(
        self, tmp_path: Path, capsys
    ) -> None:
        """The byte-level record must not be labelled a tag snapshot.

        ``[snapshot]`` in this listing means "pickled tags"; for a file a tool
        rewrote in place the payload is the whole original file, and the CLI
        says so, so nobody reads a restored-audio revert as a tags-only one.
        """
        db = tmp_path / "undo_log.db"
        wav = tmp_path / "hum.wav"
        wav.write_bytes(b"ORIGINAL")
        batch_id = _seed_overwrite_batch(db, wav)

        assert undo._cmd_show(Namespace(batch_id=batch_id, db=db)) == 0
        out = capsys.readouterr().out
        assert "noise_reduce_edit [audio-bytes]" in out
        assert "[snapshot]" not in out


class TestUndo:
    def test_reverts_move(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        src = tmp_path / "song.mp3"
        dst = tmp_path / "sorted" / "song.mp3"
        src.write_text("audio")
        dst.parent.mkdir()
        src.replace(dst)  # simulate the reorg: file now lives at dst

        batch_id = _seed_move_batch(db, src, dst)

        assert undo._cmd_undo(Namespace(batch_id=batch_id, db=db)) == 0
        out = capsys.readouterr().out
        assert not dst.exists()
        assert src.exists()
        assert src.read_text() == "audio"
        assert "1 reverted, 0 failed, 0 skipped" in out

    def test_reverts_tag_snapshot(self, tmp_path: Path) -> None:
        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        batch_id = _seed_tag_batch(db, mp3)

        handler = _StubHandler({})
        factory = MagicMock()
        factory.get_handler.return_value = handler
        with patch("audio_suite_shared.tag_helper_base.TagHandlerFactory", factory):
            assert undo._cmd_undo(Namespace(batch_id=batch_id, db=db)) == 0
        assert handler.raw_tags == {"TXXX:MOOD": "sad"}

    def test_unknown_batch_errors(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        assert undo._cmd_undo(Namespace(batch_id="deadbeef", db=db)) == 1
        assert "[ERROR] Unknown batch" in capsys.readouterr().err

    def test_copy_with_missing_target_skips(self, tmp_path: Path, capsys) -> None:
        db = tmp_path / "undo_log.db"
        src = tmp_path / "song.mp3"
        dst = tmp_path / "lost" / "song.mp3"
        batch_id = _seed_move_batch(db, src, dst, action="copy")
        dst.parent.mkdir()

        assert undo._cmd_undo(Namespace(batch_id=batch_id, db=db)) == 0
        assert "0 reverted, 0 failed, 1 skipped" in capsys.readouterr().out


class TestCliEntry:
    def test_help_exits_zero(self) -> None:
        import subprocess

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parents[2] / "utilities" / "undo.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "list" in result.stdout
        assert "undo" in result.stdout

    def test_list_subprocess(self, tmp_path: Path) -> None:
        import subprocess

        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        _seed_tag_batch(db, mp3)
        script = Path(__file__).resolve().parents[2] / "utilities" / "undo.py"
        result = subprocess.run(
            [sys.executable, str(script), "list", "--db", str(db)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "mood_analysis_batch_tagger/tag_edit" in result.stdout
        assert "[OK]" in result.stdout


class TestDbFlagPositioning:
    """``--db`` must work both before and after the subcommand (audit M16).

    Pre-fix, every subparser registered ``--db`` with ``default=None``, so
    after the top-level parser had consumed ``--db X`` the subparser's
    default clobbered the namespace attribute back to None —
    ``undo --db X show ID`` silently read the *default* database and
    reported the batch as unknown.
    """

    def _argv(self, *parts: str) -> list[str]:
        return ["undo.py", *parts]

    def test_show_honours_db_before_the_subcommand(
        self, tmp_path: Path, capsys
    ) -> None:
        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        batch_id = _seed_tag_batch(db, mp3)

        with patch.object(sys, "argv", self._argv("--db", str(db), "show", batch_id)):
            with pytest.raises(SystemExit) as exc:
                undo.main()

        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "write_mood" in out, (
            "the seeded record was not shown — the --db value given before "
            "the subcommand was lost"
        )

    def test_list_honours_db_before_the_subcommand(
        self, tmp_path: Path, capsys
    ) -> None:
        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        _seed_tag_batch(db, mp3)

        with patch.object(sys, "argv", self._argv("--db", str(db), "list")):
            with pytest.raises(SystemExit) as exc:
                undo.main()

        assert exc.value.code == 0
        assert "mood_analysis_batch_tagger/tag_edit" in capsys.readouterr().out

    def test_show_still_honours_db_after_the_subcommand(
        self, tmp_path: Path, capsys
    ) -> None:
        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        batch_id = _seed_tag_batch(db, mp3)

        with patch.object(sys, "argv", self._argv("show", batch_id, "--db", str(db))):
            with pytest.raises(SystemExit) as exc:
                undo.main()

        assert exc.value.code == 0
        assert "write_mood" in capsys.readouterr().out

    def test_subprocess_entry_point_honours_db_before_subcommand(
        self, tmp_path: Path
    ) -> None:
        """The real launch path, not just the in-process parser wiring.

        Payload is asserted on ``result.stdout`` only: ``capture_output``
        keeps stderr separate, so diagnostics can never corrupt the check.
        """
        import subprocess

        db = tmp_path / "undo_log.db"
        mp3 = tmp_path / "a.mp3"
        mp3.touch()
        batch_id = _seed_tag_batch(db, mp3)
        script = Path(__file__).resolve().parents[2] / "utilities" / "undo.py"

        result = subprocess.run(
            [sys.executable, str(script), "--db", str(db), "show", batch_id],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "write_mood" in result.stdout
        assert f"Unknown batch: {batch_id}" not in result.stdout
