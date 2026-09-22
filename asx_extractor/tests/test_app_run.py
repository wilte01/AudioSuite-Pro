"""
Tests for asx_extractor.app.ASXExtractorTool._run()

Covers the orchestration fix for the silent-swallow bug in file_ops:
a copy_audio_file() / remove_asx_file() failure must now be reflected
in the extraction log as a failure, and a copy failure must prevent
the corresponding ASX playlist from being removed.

ASXExtractorTool requires a live tk.Tk() + bootstrap_tool_app() to
construct normally, which pulls in window geometry, styles, and other
display-dependent machinery unrelated to _run()'s pure orchestration
logic. To keep this test fast, deterministic, and free of a real Tk
event loop, we bypass __init__ via __new__ and stub only the
attributes _run() actually touches.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from asx_extractor.app import ASXExtractorTool


def _make_stub_tool(folder: Path, mode: str) -> ASXExtractorTool:
    """Build an ASXExtractorTool instance with only the attributes
    _run() depends on, bypassing the real (Tk-dependent) __init__."""
    tool = ASXExtractorTool.__new__(ASXExtractorTool)

    tool.current_folder = MagicMock()
    tool.current_folder.get.return_value = str(folder)

    tool.asx_action_mode = MagicMock()
    tool.asx_action_mode.get.return_value = mode

    # self.root.after(delay, callback) must actually invoke callback
    # synchronously so the test doesn't need a real Tk event loop.
    tool.root = MagicMock()
    tool.root.after.side_effect = lambda _delay, callback=None: (
        callback() if callable(callback) else None
    )

    tool._update_step = MagicMock()
    tool._btn_log = MagicMock()
    tool.notebook = MagicMock()
    tool._tab_review = MagicMock()
    tool.auto_end = False
    tool.auto_end_var = MagicMock()
    tool.auto_end_var.get.return_value = False

    return tool


def _write_asx(path: Path, href: str) -> Path:
    path.write_text(f'<ASX><Entry><ref href="{href}"/></Entry></ASX>', encoding="utf-8")
    return path


class TestRunCopyFailureHandling:
    """Covers the fix: a failed copy must not be reported as a success,
    and must prevent removal of the corresponding ASX file."""

    def test_successful_copy_and_removal_reports_success(self, tmp_path):
        """Models the realistic case: the ASX playlist lives in
        source_dir, but its referenced audio lives elsewhere (e.g. a
        separate music library folder) — extraction pulls it in."""
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        audio = library_dir / "track.mp3"
        audio.write_bytes(b"x")

        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        asx = _write_asx(source_dir / "track.asx", str(audio.resolve()))

        tool = _make_stub_tool(source_dir, "Execute Extraction (Permanent)")

        with (
            patch("asx_extractor.core.file_ops.SEND2TRASH_AVAILABLE", False),
            patch("asx_extractor.app.active_batch", MagicMock()),
        ):
            tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (1)" in log_text
        assert "FAILURES (0)" in log_text
        assert not asx.exists()  # removed
        assert (source_dir / "track.mp3").exists()  # copied in

    def test_audio_already_colocated_with_asx_is_a_same_file_edge_case(self, tmp_path):
        """Edge case only — not a real-world scenario for this tool.
        Confirmed intended use: every .asx always points to a real
        audio file living OUTSIDE source_dir; extraction pulls it in,
        then the .asx is deleted. The audio and its .asx never
        legitimately share a directory.

        This test exists only to document behaviour if a malformed or
        mistaken ASX happens to reference a file already inside
        source_dir: copy_audio_file hits shutil.SameFileError (copying
        a file onto itself). This is now correctly surfaced as a
        failure rather than the old behaviour of silently swallowing
        it and deleting the ASX regardless."""
        audio = tmp_path / "track.mp3"
        audio.write_bytes(b"x")
        asx = _write_asx(tmp_path / "track.asx", str(audio.resolve()))

        tool = _make_stub_tool(tmp_path, "Execute Extraction (Permanent)")

        with (
            patch("asx_extractor.core.file_ops.SEND2TRASH_AVAILABLE", False),
            patch("asx_extractor.app.active_batch", MagicMock()),
        ):
            tool._run()

        log_text = (tmp_path / "Extraction_Log.txt").read_text()
        assert "FAILURES (1)" in log_text
        assert "COPY FAILED" in log_text
        assert asx.exists()  # not removed — copy never succeeded

    def test_copy_failure_prevents_asx_removal_and_is_logged_as_failure(self, tmp_path):
        """Reproduces the silent-swallow bug scenario: copy_audio_file
        fails (destination directory vanishes mid-run). Before the fix,
        this was reported as a success and the ASX was deleted anyway,
        permanently losing the playlist with nothing copied. After the
        fix, it must be a logged failure and the ASX must survive."""
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        audio = library_dir / "track.mp3"
        audio.write_bytes(b"x")

        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        asx = _write_asx(source_dir / "track.asx", str(audio.resolve()))

        tool = _make_stub_tool(source_dir, "Execute Extraction (Permanent)")

        with (
            patch("asx_extractor.app.file_ops.copy_audio_file", return_value=False),
            patch("asx_extractor.app.file_ops.remove_asx_file") as mock_remove,
            patch("asx_extractor.app.active_batch", MagicMock()),
        ):
            tool._run()
            mock_remove.assert_not_called()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (0)" in log_text
        assert "FAILURES (1)" in log_text
        assert "COPY FAILED" in log_text
        assert asx.exists()  # never removed — the bug this guards against

    def test_asx_removal_failure_is_logged_as_failure_not_success(self, tmp_path):
        """If the copy succeeds but the ASX removal fails (e.g. file
        locked), the item must be logged as a failure, not silently
        counted as a success."""
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        audio = library_dir / "track.mp3"
        audio.write_bytes(b"x")

        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        _write_asx(source_dir / "track.asx", str(audio.resolve()))

        tool = _make_stub_tool(source_dir, "Execute Extraction (Permanent)")

        with (
            patch("asx_extractor.app.file_ops.copy_audio_file", return_value=True),
            patch("asx_extractor.app.file_ops.remove_asx_file", return_value=False),
            patch("asx_extractor.app.active_batch", MagicMock()),
        ):
            tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (0)" in log_text
        assert "FAILURES (1)" in log_text
        assert "ASX REMOVAL FAILED" in log_text


class TestRunDirectoryScan:
    """Covers gaps in the Step 1 scan logic: extension case-insensitivity,
    non-.asx files being ignored, empty directories, and multi-file
    aggregation — none of which were previously exercised end-to-end."""

    def test_uppercase_asx_extension_is_detected(self, tmp_path):
        # app.py filters with f.suffix.lower() == ".asx" — an uppercase
        # .ASX file (plausible on Windows) was never actually tested.
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        audio = library_dir / "track.mp3"
        audio.write_bytes(b"x")

        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        _write_asx(source_dir / "TRACK.ASX", str(audio.resolve()))

        tool = _make_stub_tool(source_dir, "Dry Run (Simulated)")
        tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (1)" in log_text

    def test_non_asx_files_are_ignored(self, tmp_path):
        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        (source_dir / "notes.txt").write_text("not an asx file")
        (source_dir / "cover.jpg").write_bytes(b"\xff\xd8")

        tool = _make_stub_tool(source_dir, "Dry Run (Simulated)")
        tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (0)" in log_text
        assert "FAILURES (0)" in log_text

    def test_empty_directory_writes_zero_zero_log(self, tmp_path):
        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()

        tool = _make_stub_tool(source_dir, "Dry Run (Simulated)")
        tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (0)" in log_text
        assert "FAILURES (0)" in log_text
        assert "No successful extractions" in log_text
        assert "No failures detected" in log_text

    def test_multiple_asx_files_all_aggregated(self, tmp_path):
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()

        # Two that will succeed, one that will fail (missing audio).
        for name in ("a", "b"):
            audio = library_dir / f"{name}.mp3"
            audio.write_bytes(b"x")
            _write_asx(source_dir / f"{name}.asx", str(audio.resolve()))
        missing = library_dir / "ghost.mp3"
        _write_asx(source_dir / "c.asx", str(missing.resolve()))

        tool = _make_stub_tool(source_dir, "Dry Run (Simulated)")
        tool._run()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (2)" in log_text
        assert "FAILURES (1)" in log_text
        assert "c.asx" in log_text
        assert "FILE NOT FOUND" in log_text

    def test_dry_run_never_calls_copy_or_remove(self, tmp_path):
        library_dir = tmp_path / "Library"
        library_dir.mkdir()
        audio = library_dir / "track.mp3"
        audio.write_bytes(b"x")

        source_dir = tmp_path / "Playlists"
        source_dir.mkdir()
        _write_asx(source_dir / "track.asx", str(audio.resolve()))

        tool = _make_stub_tool(source_dir, "Dry Run (Simulated)")

        with (
            patch("asx_extractor.app.file_ops.copy_audio_file") as mock_copy,
            patch("asx_extractor.app.file_ops.remove_asx_file") as mock_remove,
        ):
            tool._run()
            mock_copy.assert_not_called()
            mock_remove.assert_not_called()

        log_text = (source_dir / "Extraction_Log.txt").read_text()
        assert "SUCCESSFUL EXTRACTIONS (1)" in log_text
