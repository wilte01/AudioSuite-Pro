"""Tests for album_art_normalizer/cli.py — the ``audiosuite artnormalize`` command.

Changed in 1.0.1: fixed os.path patch in TestGuiRunModeIsHonoured._start() to use
patch("os.path.exists") instead of patch.object(app_mod, "os.path", ...).

Audit A1 (iteration 7, Stage 0) recorded two halves of one user-visible lie:

1. The unified usage in ``audio_suite_shared/cli_app.py`` advertised
   ``audiosuite artnormalize /path --size 800 [--dry]`` while the command
   declared no ``--dry``, so the documented invocation exited 2 with
   ``Error: No such option: --dry``.
2. ``album_art_normalizer/app.py`` rendered a "Dry Run" / "Live Update" choice
   in the GUI, stored it in ``self.run_mode``, and then never read it — the
   run always wrote.

The engine half of (1) is locked in ``test_album_art_normalizer.py``
(``TestDryRunWritesNothing``), which measures the write sites.  This module
locks the *seam*: the flag resolves, and it arrives at ``run_normalization``
as ``is_dry_run=True``, plus the real end-to-end outcome on a real MP3 whose
APIC frame genuinely needs resizing.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from PIL import Image

from album_art_normalizer.core import file_processor
from audio_suite_shared.cli_app import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _make_mp3_with_oversized_art(
    directory: Path, name: str = "track.mp3", size: int = 500
) -> Path:
    """A real MP3 carrying a real APIC frame that genuinely needs resizing.

    A mocked tag object would leave the dry-run assertion vacuous: the thing
    being tested is whether *bytes on disk* move, so the fixture has to have
    real bytes that a real writer would change.
    """
    from pydub import AudioSegment

    path = directory / name
    AudioSegment.silent(duration=500, frame_rate=44100).export(
        str(path), format="mp3", bitrate="192k"
    )

    img = Image.new("RGB", (size, size), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)

    from mutagen.id3 import APIC, ID3

    tags = ID3(str(path))
    tags.add(
        APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=buf.getvalue())
    )
    tags.save()
    return path


def _fingerprint(path: Path) -> tuple[str, float]:
    """SHA-256 and mtime — the two properties an embed would disturb."""
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime


# ── The CLI → core seam ───────────────────────────────────────────────────────


class TestDryFlagReachesCore:
    """``--dry`` must resolve *and* arrive at ``run_normalization``."""

    @staticmethod
    def _run(runner: CliRunner, music: Path, *extra: str) -> object:
        # The CLI imports the name inside the function body, so the patch
        # target is the defining module (AGENTS.md, "Mock patch target follows
        # the import, not the caller").
        with patch.object(file_processor, "run_normalization") as mock_run:
            result = runner.invoke(cli, ["artnormalize", str(music), *extra])
        assert mock_run.call_count == 1, (
            f"run_normalization was called {mock_run.call_count} times: {result.output}"
        )
        return mock_run.call_args.kwargs

    def test_dry_flag_resolves_and_exits_zero(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """The audit's exact repro: exit 0, not exit 2 / 'No such option'."""
        with patch.object(file_processor, "run_normalization"):
            result = runner.invoke(cli, ["artnormalize", str(tmp_path), "--dry"])
        assert result.exit_code == 0, result.output
        assert "No such option" not in result.output

    def test_dry_reaches_the_core_as_is_dry_run(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        assert self._run(runner, tmp_path, "--dry")["is_dry_run"] is True

    def test_live_reaches_the_core_as_is_dry_run_false(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        assert self._run(runner, tmp_path, "--live")["is_dry_run"] is False

    def test_default_is_live(self, runner: CliRunner, tmp_path: Path) -> None:
        """Omitting the flag must keep today's write behaviour."""
        assert self._run(runner, tmp_path)["is_dry_run"] is False

    def test_target_size_is_forwarded(self, runner: CliRunner, tmp_path: Path) -> None:
        kwargs = self._run(runner, tmp_path, "--size", "1200")
        assert kwargs["target_size"] == (1200, 1200)


# ── The real outcome ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestDryRunRealOutcome:
    """A real MP3 through the real chain: measure the outcome, not the flag."""

    def test_dry_run_leaves_the_embedded_art_untouched(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        music = tmp_path / "music"
        music.mkdir()
        source = _make_mp3_with_oversized_art(music)
        before = _fingerprint(source)

        result = runner.invoke(cli, ["artnormalize", str(music), "--dry"])

        assert result.exit_code == 0, result.output
        assert _fingerprint(source) == before, (
            "a dry run rewrote the MP3 (SHA-256 or mtime changed)"
        )
        # It still measured: the file counts as a previewed update, 0 errors.
        assert "0 errors" in result.output, result.output
        assert "1 skipped" not in result.output, (
            f"a dry run must still report what it would change: {result.output}"
        )

    def test_live_run_really_replaces_the_embedded_art(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """The control: without this, the dry-run assertion could pass
        vacuously because the tool never writes anything at all."""
        from mutagen.id3 import ID3

        music = tmp_path / "music"
        music.mkdir()
        source = _make_mp3_with_oversized_art(music)
        before = _fingerprint(source)

        result = runner.invoke(cli, ["artnormalize", str(music)])

        assert result.exit_code == 0, result.output
        assert _fingerprint(source) != before, "a live run must rewrite the MP3"
        apic = ID3(str(source)).getall("APIC")[0]
        assert Image.open(io.BytesIO(apic.data)).size == (800, 800)

    def test_dry_run_records_no_undo_snapshot(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """A preview must not pollute the shared undo history: the CLI opens
        ``active_batch("album_art_normalizer", "tag_edit")``, so a dry run that
        recorded entries would leave a phantom undo entry the user can restore
        from — and restoring it would write the *old* art over a file the user
        never changed.

        The root conftest's session-scoped ``_isolated_undo_db`` fixture already
        points ``AUDIOSUITE_UNDO_DB`` at a scratch database, so this reads that
        one rather than the per-user production log.
        """
        import os

        from audio_suite_shared import batch_undo

        music = tmp_path / "music"
        music.mkdir()
        _make_mp3_with_oversized_art(music)
        undo_db = Path(os.environ["AUDIOSUITE_UNDO_DB"])

        # The undo DB is session-scoped and shared, so a sibling test's live
        # run is still in it.  Snapshot the ids first and assert only about the
        # batches this invocation creates — otherwise the assertion silently
        # depends on test order.
        before_ids = {
            b.batch_id
            for b in batch_undo.list_recent_batches(limit=50, db_path=undo_db)
        }

        result = runner.invoke(cli, ["artnormalize", str(music), "--dry"])

        assert result.exit_code == 0, result.output
        # Sanity: the run really did work. Without this the assertion below
        # would also hold for a run that processed nothing (which is exactly
        # how the slot_queue TypeError hid - see TestCliCommandsActuallyRun).
        assert "1 skipped" not in result.output, result.output

        new_batches = [
            b
            for b in batch_undo.list_recent_batches(limit=50, db_path=undo_db)
            if b.batch_id not in before_ids
        ]
        assert all(b.record_count == 0 for b in new_batches), (
            f"a dry run recorded undo entries: {[b.record_count for b in new_batches]}"
        )


# ── The GUI's dead run_mode selector ─────────────────────────────────────────


class TestGuiRunModeIsHonoured:
    """``run_mode`` was rendered and stored but never read — always wrote."""

    @staticmethod
    def _app() -> object:
        """A stub app carrying only the state start_processing() reads."""
        from album_art_normalizer import RESOLUTION_MAP

        app = object.__new__(type("App", (), {}))
        app.run_mode = MagicMock()
        app.resolution = MagicMock()
        # Derived from the real map: its keys use U+00D7 (×), not "x", and
        # start_processing() rejects any key it does not contain.
        app.resolution.get.return_value = next(
            k for k, v in RESOLUTION_MAP.items() if v == (800, 800)
        )
        app.folder_path = MagicMock()
        app.folder_path.get.return_value = "C:/music"
        # `target=self._run_normalization` is evaluated eagerly, so the stub
        # must carry it even though the thread body never runs.
        app._run_normalization = MagicMock()
        app.start_btn = MagicMock()
        app.overall_status = MagicMock()
        app._tab_processing = None
        app.notebook = MagicMock()
        return app

    def _start(self, mode: str) -> object:
        from album_art_normalizer import app as app_mod

        app = self._app()
        app.run_mode.get.return_value = mode
        with (
            patch.object(app_mod.messagebox, "showerror") as showerror,
            patch("os.path.exists", return_value=True),
            patch("os.path.isdir", return_value=True),
            patch.object(app_mod, "threading") as threading,
        ):
            threading.Thread.return_value.start = MagicMock()
            app_mod.ArtNormalizerApp.start_processing(app)
        showerror.assert_not_called()
        # The thread is launched as Thread(target=..., args=(folder, target,
        # dry_run), daemon=True), so the triple lives under the "args" keyword;
        # the third element is the whole point of this test.
        return threading.Thread.call_args.kwargs["args"][2]

    def test_dry_run_mode_reaches_the_thread_as_true(self) -> None:
        assert self._start("Dry Run") is True

    def test_live_update_mode_reaches_the_thread_as_false(self) -> None:
        assert self._start("Live Update") is False
