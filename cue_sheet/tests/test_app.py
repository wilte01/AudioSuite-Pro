"""Tests for the CUE Sheet Generator window (``cue_sheet.app``).

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any

from cue_sheet.app import CueSheetApp
from cue_sheet.core.export import run_export


def _silent_wav(path: Path) -> None:
    """Write a short silent WAV so the folder scan finds one track."""
    import wave

    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(8000)
        handle.writeframes(b"\x00\x00" * 800)


def _bare_app() -> CueSheetApp:
    """Return an app whose only real state is the worker queue."""
    app = object.__new__(CueSheetApp)
    app._events = queue.SimpleQueue()  # type: ignore[attr-defined]
    return app


class TestCompletionSeam:
    """The processor's payload, driven into the handler the window binds.

    The processor owns the payload and the handler mirrors it by hand, so this
    drives the real ``run_export`` into the bound ``_on_complete`` and asserts
    the sheet on disk plus the queued payload -- never the fields the writer
    just set.
    """

    def test_the_run_publishes_the_counters_and_the_written_sheet(
        self, tmp_path: Path
    ) -> None:
        _silent_wav(tmp_path / "01 - First.wav")
        _silent_wav(tmp_path / "02 - Second.wav")
        app = _bare_app()
        received: list[dict[str, Any]] = []

        def handler(**payload: Any) -> None:
            received.append(payload)
            CueSheetApp._on_complete(app, **payload)

        run_export(str(tmp_path), on_complete=handler)

        assert received, "run_export published no completion payload"

        kind, queued = app._events.get_nowait()  # type: ignore[attr-defined]
        assert kind == "complete"
        assert queued["total"] == 2
        assert queued["processed"] == 2
        assert queued["skipped"] == 0
        assert queued["errors"] == 0
        assert queued["tracks"] == 2
        assert queued["dry_run"] is False

        sheet = Path(queued["output"])
        assert sheet == tmp_path / "album.cue"
        text = sheet.read_text(encoding="utf-8")
        assert text.count("  TRACK ") == 2

        report = Path(queued["report_path"])
        assert report.name == "cue_sheet_sync_log.txt"
        assert "SUMMARY: tracks=2" in report.read_text(encoding="utf-8")

    def test_a_dry_run_publishes_without_writing_the_sheet(
        self, tmp_path: Path
    ) -> None:
        _silent_wav(tmp_path / "01 - Only.wav")
        app = _bare_app()

        run_export(
            str(tmp_path),
            dry_run=True,
            on_complete=lambda **payload: CueSheetApp._on_complete(app, **payload),
        )

        _kind, queued = app._events.get_nowait()  # type: ignore[attr-defined]
        assert queued["dry_run"] is True
        assert not Path(queued["output"]).exists(), "a dry run wrote the sheet"
        report = Path(queued["report_path"])
        assert report.name == "cue_sheet_dry_run_log.txt"
        assert "Mode: DRY RUN" in report.read_text(encoding="utf-8")
