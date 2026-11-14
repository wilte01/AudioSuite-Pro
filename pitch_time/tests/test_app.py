"""Tests for the window's settings mapping and callback seams.

No real window: the setup tab's variables are the only state involved, and the
seams are checked by the queue they fill (the widget writes happen in the
poller, which the callback-payload contract covers).

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioConfigValueError
from pitch_time.app import PitchTimeApp
from pitch_time.core.engine import REPORT_NAMES, run_pitch_time
from pitch_time.core.models import MODE_PITCH, MODE_TEMPO, PitchTimeSettings

SAMPLE_RATE = 44_100


class _FakeVar:
    """A value holder with the two methods the wiring uses.

    ``MagicMock`` cannot model a widget variable written and then read: its
    ``get`` keeps the value the mock was created with, so a test that sets a
    value and asserts the *window* reads it back would pass without the write
    reaching anything.
    """

    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value


def _var(value: str) -> MagicMock:
    var = MagicMock()
    var.get.return_value = value
    return var


def _app(
    *, mode: str = MODE_TEMPO, rate: str = "1.25", semitones: str = "0.0"
) -> PitchTimeApp:
    app = object.__new__(PitchTimeApp)
    app.transform_mode = _var(mode)
    app.rate_var = _var(rate)
    app.semitones_var = _var(semitones)
    app._events = queue.SimpleQueue()
    return app


class TestSettings:
    def test_the_widgets_become_the_run_settings(self) -> None:
        settings = _app(rate="1.5")._settings()

        assert settings.mode == MODE_TEMPO
        assert settings.rate == pytest.approx(1.5)

    def test_a_pitch_mode_reads_the_semitone_field(self) -> None:
        settings = _app(mode=MODE_PITCH, semitones="-2")._settings()

        assert settings.mode == MODE_PITCH
        assert settings.semitones == pytest.approx(-2.0)

    def test_a_non_number_is_reported_as_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            _app(rate="soon")._settings()

    def test_an_out_of_range_rate_surfaces_the_config_error(self) -> None:
        with pytest.raises(AudioConfigValueError, match="between"):
            _app(rate="9")._settings()

    def test_a_semitone_launch_switches_the_mode(self) -> None:
        """The flag the driver sent *is* the mode the window shows."""
        app = object.__new__(PitchTimeApp)
        app.folder_path = _FakeVar("")
        app.rate_var = _FakeVar("1.0")
        app.semitones_var = _FakeVar("0.0")
        app.transform_mode = _FakeVar(MODE_TEMPO)
        app.run_mode = _FakeVar("Live Update")

        app._apply_cli_args(directory="", rate="", semitones="-3", dry_run=False)

        assert app.transform_mode.get() == MODE_PITCH
        assert app.semitones_var.get() == "-3"

    def test_a_neutral_setting_is_labelled_not_refused(self) -> None:
        app = _app(rate="1.0")
        app._settings_label = MagicMock()

        app._update_settings_label()

        assert (
            "no change requested" in app._settings_label.config.call_args.kwargs["text"]
        )


class TestCallbackSeams:
    def test_progress_is_queued_not_written(self) -> None:
        app = _app()

        app._on_progress(processed=1, total=2, display_text="song.wav")

        assert app._events.get_nowait() == (
            "progress",
            {"processed": 1, "total": 2, "display_text": "song.wav"},
        )

    def test_completion_is_queued_not_written(self) -> None:
        app = _app()

        app._on_complete(
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.2,
            written=1,
        )

        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["written"] == 1

    def test_an_error_is_queued_with_its_message(self) -> None:
        app = _app()

        app._on_error("the folder does not exist")

        assert app._events.get_nowait() == ("error", "the folder does not exist")


class TestCompletionSeam:
    """The real ``run_pitch_time`` publishes into the handler the window binds."""

    def test_the_published_payload_reaches_the_queued_completion(
        self, tmp_path: Path
    ) -> None:
        times = np.arange(int(SAMPLE_RATE * 0.5)) / SAMPLE_RATE
        samples = (0.3 * np.sin(2 * np.pi * 440.0 * times) * 32767).astype(np.int16)
        AudioSegment(
            data=samples.tobytes(),
            sample_width=2,
            frame_rate=SAMPLE_RATE,
            channels=1,
        ).export(str(tmp_path / "song.wav"), format="wav")
        app = _app()

        run_pitch_time(
            str(tmp_path),
            settings=PitchTimeSettings(rate=1.25),
            on_complete=app._on_complete,
        )

        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["total"] == 1
        assert payload["written"] == 1
        assert payload["mode"] == MODE_TEMPO

        report = tmp_path / REPORT_NAMES[False]
        assert report.is_file(), "the run wrote no report for the handler's run"
        text = report.read_text(encoding="utf-8")
        assert text.startswith("PITCH / TIME REPORT")
        assert "Tempo rate 1.25x" in text
        assert (tmp_path / "song_tempo_1.25.wav").is_file()

    def test_a_dropped_counter_raises_instead_of_defaulting(self) -> None:
        with pytest.raises(TypeError):
            _app()._on_complete(total=1, processed=1, skipped=0, errors=0)

    def test_a_growing_payload_does_not_raise(self) -> None:
        app = _app()

        app._on_complete(
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.1,
            future_field="x",
        )

        _kind, payload = app._events.get_nowait()
        assert payload["future_field"] == "x"
