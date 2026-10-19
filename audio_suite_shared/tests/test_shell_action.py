"""Tests for audio_suite_shared.shell_action (Sprint 4 Item 4.1).

The action's real workers are mocked, so no audio is decoded and no tag is
written; the tests pin the *contract* D60 defines: one file only, no
overwrite, nothing written under ``--dry``, and tag writes inside an undo
batch.

Changed in 1.4.0: new suite (PLAN D58/D60).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from audio_suite_shared import shell_action

_CONVERT = "music_format_converter.core.file_processor.process_single_file"
_BPM = "bpm_analyzer.core.file_processor.process_single_file"
_KEY = "key_detector.core.file_processor.process_single_file"
_MOOD = "mood_analyzer.core.file_processor.process_single_file"


def _audio(tmp_path: Path, name: str = "song.mp3") -> Path:
    path = tmp_path / name
    path.write_bytes(b"fake audio")
    return path


class TestArgumentValidation:
    def test_unknown_verb_exits_with_usage(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            shell_action.main(["not-a-verb", str(_audio(tmp_path))])
        assert excinfo.value.code == 2

    def test_missing_file_returns_one(self, tmp_path: Path) -> None:
        assert shell_action.main(["analyze_bpm", str(tmp_path / "gone.mp3")]) == 1

    def test_unsupported_extension_returns_one(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.txt"
        path.write_text("not audio", encoding="utf-8")
        assert shell_action.main(["analyze_bpm", str(path)]) == 1


class TestConvert:
    def test_refuses_to_overwrite_an_existing_output(self, tmp_path: Path) -> None:
        source = _audio(tmp_path, "song.mp3")
        (tmp_path / "song.flac").write_bytes(b"existing")
        with patch(_CONVERT) as process:
            code = shell_action.main(["convert_flac", str(source)])
        assert code == 2
        process.assert_not_called()

    def test_dry_run_asks_the_worker_for_a_dry_run(self, tmp_path: Path) -> None:
        source = _audio(tmp_path, "song.wav")
        with (
            patch(_CONVERT) as process,
            patch(
                "music_format_converter.core.file_processor."
                "MusicFormatConverterProcessor"
            ),
        ):
            code = shell_action.main(["convert_mp3", str(source), "--dry"])
        assert code == 0
        assert process.call_args.args[6] is True

    def test_live_run_converts_only_the_selected_file(self, tmp_path: Path) -> None:
        source = _audio(tmp_path, "song.wav")
        _audio(tmp_path, "other.wav")
        with (
            patch(_CONVERT) as process,
            patch(
                "music_format_converter.core.file_processor."
                "MusicFormatConverterProcessor"
            ),
        ):
            code = shell_action.main(["convert_mp3", str(source)])
        assert code == 0
        assert process.call_args.args[0] == "song.wav"
        assert process.call_args.args[1] == str(tmp_path)
        assert process.call_args.args[3] == "mp3"
        assert process.call_args.args[6] is False


class TestAnalysis:
    @pytest.mark.parametrize(
        ("verb", "worker", "tool"),
        [
            ("analyze_bpm", _BPM, "bpm_analyzer"),
            ("analyze_key", _KEY, "key_detector"),
            ("analyze_mood", _MOOD, "mood_analyzer"),
        ],
    )
    def test_tag_writes_run_inside_an_undo_batch(
        self, tmp_path: Path, verb: str, worker: str, tool: str
    ) -> None:
        source = _audio(tmp_path)
        with (
            patch(worker) as process,
            patch("audio_suite_shared.shell_action.active_batch") as batch,
        ):
            code = shell_action.main([verb, str(source)])
        assert code == 0
        assert process.call_count == 1
        batch.assert_called_once_with(tool, "tag_edit")

    def test_dry_run_is_forwarded_to_the_worker(self, tmp_path: Path) -> None:
        source = _audio(tmp_path)
        with patch(_BPM) as process:
            shell_action.main(["analyze_bpm", str(source), "--dry"])
        assert process.call_args.kwargs["is_dry_run"] is True

    def test_reported_error_returns_nonzero(self, tmp_path: Path) -> None:
        source = _audio(tmp_path)

        def worker(**kwargs):
            kwargs["on_progress"](
                n_skipped=0,
                n_errors=1,
                display_text="[ERROR] song.mp3",
                log_text="[ERROR]\n",
            )

        with patch(_BPM, side_effect=worker):
            code = shell_action.main(["analyze_bpm", str(source)])
        assert code == 1

    def test_worker_receives_the_selected_basename(self, tmp_path: Path) -> None:
        source = _audio(tmp_path)
        with patch(_KEY) as process:
            shell_action.main(["analyze_key", str(source)])
        assert process.call_args.kwargs["name"] == "song.mp3"
        assert process.call_args.kwargs["dir_path"] == str(tmp_path)
