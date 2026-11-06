"""Tests for the window's settings mapping and callback seams.

No real window: the setup tab's variables are the only state involved, and the
seams are checked by the queue they fill (the widget writes happen in the
poller, which the callback-payload contract covers).

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioConfigValueError
from track_splitter.app import BOUNDARY_LABELS, TrackSplitterApp
from track_splitter.core.models import SplitSettings
from track_splitter.core.splitter import REPORT_NAME, run_split

SAMPLE_RATE = 44_100


def _var(value: str) -> MagicMock:
    var = MagicMock()
    var.get.return_value = value
    return var


def _app(**overrides: str) -> TrackSplitterApp:
    app = object.__new__(TrackSplitterApp)
    app.min_silence = _var(overrides.get("min_silence", "700"))
    app.silence_db = _var(overrides.get("silence_db", "-45"))
    app.min_track = _var(overrides.get("min_track", "5000"))
    label = overrides.get("boundary", next(iter(BOUNDARY_LABELS)))
    app.boundary_label = _var(label)
    app.naming = _var(overrides.get("naming", "{track:02d} - {title}"))
    app.write_cue = MagicMock()
    app.write_cue.get.return_value = True
    app._events = queue.SimpleQueue()
    return app


class TestSettings:
    def test_the_widgets_become_the_run_settings(self) -> None:
        app = _app(min_silence="500", silence_db="-40", min_track="2000")
        settings = app._settings()

        assert settings.min_silence_ms == 500
        assert settings.silence_db == -40.0
        assert settings.min_track_ms == 2000
        assert settings.naming_pattern == "{track:02d} - {title}"
        assert settings.write_cue is True

    def test_every_boundary_label_maps_to_its_rule(self) -> None:
        for label, rule in BOUNDARY_LABELS.items():
            assert _app(boundary=label)._settings().boundary == rule

    def test_a_non_number_is_reported_as_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            _app(min_silence="soon")._settings()

    def test_an_unusable_setting_surfaces_the_config_error(self) -> None:
        with pytest.raises(AudioConfigValueError):
            _app(silence_db="0")._settings()

    def test_an_unknown_label_falls_back_to_the_first_rule(self) -> None:
        app = _app(boundary="nonsense")
        assert app._settings().boundary in BOUNDARY_LABELS.values()


class TestCallbackSeams:
    def test_progress_is_queued_not_written(self) -> None:
        app = _app()
        app._on_progress(processed=1, total=2, display_text="[a.wav] 3 tracks")
        assert app._events.get_nowait() == (
            "progress",
            {"processed": 1, "total": 2, "display_text": "[a.wav] 3 tracks"},
        )

    def test_completion_is_queued_not_written(self) -> None:
        app = _app()
        app._on_complete(
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.4,
            tracks=3,
            output_dir="/out",
        )
        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["tracks"] == 3

    def test_an_error_is_queued_with_its_message(self) -> None:
        app = _app()
        app._on_error("no audio files found")
        assert app._events.get_nowait() == ("error", "no audio files found")


class TestCompletionSeam:
    """The real ``run_split`` publishes into the handler the window binds."""

    @staticmethod
    def _library(folder: Path) -> Path:
        """Write one tone/gap/tone recording and return its folder."""
        times = np.arange(int(SAMPLE_RATE * 0.4)) / SAMPLE_RATE
        tone = (0.3 * np.sin(2 * np.pi * 440 * times) * 32767).astype(np.int16)
        audio = (
            AudioSegment(
                data=tone.tobytes(),
                sample_width=2,
                frame_rate=SAMPLE_RATE,
                channels=1,
            )
            + AudioSegment.silent(duration=800, frame_rate=SAMPLE_RATE)
            + AudioSegment(
                data=tone.tobytes(),
                sample_width=2,
                frame_rate=SAMPLE_RATE,
                channels=1,
            )
        )
        audio.export(str(folder / "gig.wav"), format="wav")
        return folder

    def test_the_published_payload_reaches_the_queued_completion(
        self, tmp_path: Path
    ) -> None:
        self._library(tmp_path)
        app = _app()

        run_split(
            str(tmp_path),
            settings=SplitSettings(
                min_silence_ms=400, silence_db=-40.0, min_track_ms=200
            ),
            on_complete=app._on_complete,
        )

        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["total"] == 1
        assert payload["processed"] == 1
        assert payload["skipped"] == 0
        assert payload["tracks"] == 2
        assert payload["files_written"] == 2

        report = tmp_path / REPORT_NAME
        assert report.is_file(), "the run wrote no report for the handler's run"
        text = report.read_text(encoding="utf-8")
        assert text.startswith("TRACK SPLITTER REPORT")
        assert "Tracks: 2" in text

    def test_a_dropped_counter_raises_instead_of_defaulting(self) -> None:
        app = _app()
        with pytest.raises(TypeError):
            app._on_complete(total=1, processed=1, skipped=0, errors=0)

    def test_a_growing_payload_does_not_raise(self) -> None:
        app = _app()
        app._on_complete(
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.5,
            future_field="x",
        )
        _kind, payload = app._events.get_nowait()
        assert payload["future_field"] == "x"
