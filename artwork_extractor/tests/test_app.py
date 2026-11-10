"""Tests for the Artwork Extractor window (``artwork_extractor.app``).

Changed in 2.6.0: new module — the Artwork Extractor's window.
"""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from artwork_extractor.app import ArtworkExtractorApp
from artwork_extractor.core.extract import run_extraction
from artwork_extractor.utils import cli_args
from audio_suite_shared.tag_helper_art import embed_artwork


def _jpeg_bytes() -> bytes:
    """Build JPEG bytes carrying a real APP0 segment and SOF0 frame header."""
    app0 = (
        b"\xff\xe0"
        + (16).to_bytes(2, "big")
        + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    )
    sof = (
        b"\xff\xc0"
        + (17).to_bytes(2, "big")
        + b"\x08"
        + (800).to_bytes(2, "big")
        + (1080).to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01"
    )
    return b"\xff\xd8" + app0 + sof


def _tagged_flac(path: Path) -> None:
    """Write a real FLAC carrying the test JPEG, or skip without an encoder."""
    import pytest
    from pydub import AudioSegment

    try:
        AudioSegment.silent(duration=500).export(str(path), format="flac")
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(f"this host cannot encode FLAC ({type(exc).__name__})")
    embed_artwork(str(path), _jpeg_bytes())


def _bare_app() -> ArtworkExtractorApp:
    """Return an app whose only real state is the worker queue."""
    app = object.__new__(ArtworkExtractorApp)
    app._events = queue.SimpleQueue()  # type: ignore[attr-defined]
    return app


def _controls_app() -> ArtworkExtractorApp:
    """Return an app whose run-control variables are mocks, not Tk variables."""
    app = object.__new__(ArtworkExtractorApp)
    for name in (
        "folder_path",
        "sidecar_name",
        "force_var",
        "recursive_var",
        "run_mode",
        "auto_start_var",
        "auto_end_var",
        "clear_logs_var",
        "parallel_var",
    ):
        setattr(app, name, MagicMock())
    return app


class TestTheDriverHandshake:
    """The window mirrors every run control the driver's argv carries."""

    def test_the_batch_argv_makes_the_window_start_and_close(
        self, tmp_path: Path
    ) -> None:
        parsed = cli_args.parse(
            [
                "Artwork_Extractor.pyw",
                str(tmp_path),
                "--live",
                "--start",
                "--end",
                "--name",
                "folder",
                "--force",
                "--recursive",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        app = _controls_app()

        ArtworkExtractorApp._apply_cli_args(
            app,
            directory=parsed.folder_path,
            sidecar_name=parsed.sidecar_name,
            force=parsed.force,
            recursive=parsed.recursive,
            dry_run=not parsed.live_mode,
            auto_start=parsed.auto_start,
            auto_end=parsed.auto_end,
            clear_logs=parsed.clear_logs,
            parallel=parsed.parallel_run,
        )

        app.folder_path.set.assert_called_once_with(str(tmp_path))  # type: ignore[attr-defined]
        app.sidecar_name.set.assert_called_once_with("folder")  # type: ignore[attr-defined]
        app.force_var.set.assert_called_once_with(True)  # type: ignore[attr-defined]
        app.recursive_var.set.assert_called_once_with(True)  # type: ignore[attr-defined]
        app.auto_start_var.set.assert_called_once_with(True)  # type: ignore[attr-defined]
        app.auto_end_var.set.assert_called_once_with(True)  # type: ignore[attr-defined]

    def test_a_launch_without_the_flags_leaves_them_off(self) -> None:
        app = _controls_app()

        ArtworkExtractorApp._apply_cli_args(
            app,
            directory="",
            sidecar_name="",
            force=False,
            recursive=False,
            dry_run=False,
            auto_start=False,
            auto_end=False,
            clear_logs=False,
            parallel=False,
        )

        assert not app.auto_start_var.set.called  # type: ignore[attr-defined]
        assert not app.auto_end_var.set.called  # type: ignore[attr-defined]
        assert not app.run_mode.set.called  # type: ignore[attr-defined]
        assert not app.force_var.set.called  # type: ignore[attr-defined]


class TestCompletionSeam:
    """The processor's payload, driven into the handler the window binds.

    This drives the real ``run_extraction`` into the bound ``_on_complete`` and
    asserts the sidecar and the report on disk plus the queued payload — never
    the fields the writer just set.
    """

    def test_the_run_publishes_the_counters_and_the_written_sidecar(
        self, tmp_path: Path
    ) -> None:
        _tagged_flac(tmp_path / "a.flac")
        app = _bare_app()
        received: list[dict[str, Any]] = []

        def handler(**payload: Any) -> None:
            received.append(payload)
            ArtworkExtractorApp._on_complete(app, **payload)

        run_extraction(str(tmp_path), on_complete=handler)

        assert received, "run_extraction published no completion payload"

        kind, queued = app._events.get_nowait()  # type: ignore[attr-defined]
        assert kind == "complete"
        assert queued["total"] == 1
        assert queued["processed"] == 1
        assert queued["skipped"] == 0
        assert queued["errors"] == 0
        assert queued["extracted"] == 1
        assert queued["dry_run"] is False

        assert (tmp_path / "cover.jpg").read_bytes() == _jpeg_bytes()

        report = Path(queued["report_path"])
        assert report.name == "artwork_extractor_sync_log.txt"
        assert "SUMMARY: files=1 extracted=1" in report.read_text(encoding="utf-8")
