"""Tests for the window's settings mapping, order and callback seams.

No real window: the setup tab's variables are the only state involved, and the
seams are checked by the queue they fill (the widget writes happen in the
poller, which the callback-payload contract covers).

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

import queue
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydub import AudioSegment

from audio_joiner.app import AudioJoinerApp, plan_total
from audio_joiner.core.join import REPORT_NAMES, run_join
from audio_joiner.core.models import JoinSettings
from audio_suite_shared.exceptions import AudioConfigValueError

SAMPLE_RATE = 44_100


def _var(value: str) -> MagicMock:
    var = MagicMock()
    var.get.return_value = value
    return var


def _app(**overrides: str) -> AudioJoinerApp:
    app = object.__new__(AudioJoinerApp)
    app.gap_ms = _var(overrides.get("gap_ms", "0"))
    app.crossfade_ms = _var(overrides.get("crossfade_ms", "0"))
    app.copy_compatible = MagicMock()
    app.copy_compatible.get.return_value = True
    app._events = queue.SimpleQueue()
    return app


class TestSettings:
    def test_the_widgets_become_the_run_settings(self) -> None:
        settings = _app(gap_ms="250")._settings()

        assert settings.gap_ms == 250
        assert settings.crossfade_ms == 0
        assert settings.copy_when_compatible is True

    def test_a_gap_and_a_crossfade_surface_the_config_error(self) -> None:
        with pytest.raises(AudioConfigValueError, match="not both"):
            _app(gap_ms="100", crossfade_ms="100")._settings()

    def test_a_non_number_is_reported_as_a_value_error(self) -> None:
        with pytest.raises(ValueError):
            _app(gap_ms="soon")._settings()


class TestOrder:
    @staticmethod
    def _ordered(names: list[str], *, selection: int = 0, delta: int = 1):
        app = object.__new__(AudioJoinerApp)
        app._segments = [Path(name) for name in names]
        app._durations = {}
        app._segment_list = MagicMock()
        app._segment_list.curselection.return_value = (selection,)
        app._planned_label = MagicMock()
        app.gap_ms = _var("0")
        app.crossfade_ms = _var("0")
        app.copy_compatible = MagicMock()
        app.copy_compatible.get.return_value = True
        app._move(delta)
        return [path.name for path in app._segments]

    def test_moving_down_swaps_with_the_next_entry(self) -> None:
        assert self._ordered(["a.wav", "b.wav"]) == ["b.wav", "a.wav"]

    def test_moving_up_swaps_with_the_previous_entry(self) -> None:
        assert self._ordered(["a.wav", "b.wav"], selection=1, delta=-1) == [
            "b.wav",
            "a.wav",
        ]

    def test_moving_past_either_end_changes_nothing(self) -> None:
        assert self._ordered(["a.wav", "b.wav"], selection=0, delta=-1) == [
            "a.wav",
            "b.wav",
        ]
        assert self._ordered(["a.wav", "b.wav"], selection=1, delta=1) == [
            "a.wav",
            "b.wav",
        ]

    def test_the_planned_length_sums_the_measured_segments(self) -> None:
        segments = [Path("a.wav"), Path("b.wav")]
        durations = {segments[0]: 400, segments[1]: 600}

        assert plan_total(durations, segments, JoinSettings(gap_ms=200)) == 1200

    def test_an_unmeasured_segment_is_reported_not_guessed(self) -> None:
        segments = [Path("a.wav"), Path("b.wav")]

        with pytest.raises(AudioConfigValueError, match="could not be measured"):
            plan_total({segments[0]: 400}, segments, JoinSettings())


class TestCallbackSeams:
    def test_progress_is_queued_not_written(self) -> None:
        app = _app()

        app._on_progress(processed=1, total=2, display_text="[a.wav] read")

        assert app._events.get_nowait() == (
            "progress",
            {"processed": 1, "total": 2, "display_text": "[a.wav] read"},
        )

    def test_completion_is_queued_not_written(self) -> None:
        app = _app()

        app._on_complete(
            total=2,
            processed=2,
            skipped=0,
            errors=0,
            duration_secs=0.2,
            output="/out/joined.wav",
        )

        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["output"] == "/out/joined.wav"

    def test_an_error_is_queued_with_its_message(self) -> None:
        app = _app()

        app._on_error("a join needs two files")

        assert app._events.get_nowait() == ("error", "a join needs two files")


class TestCompletionSeam:
    """The real ``run_join`` publishes into the handler the window binds."""

    def test_the_published_payload_reaches_the_queued_completion(
        self, tmp_path: Path
    ) -> None:
        for name, frequency in (("a.wav", 440), ("b.wav", 880)):
            times = np.arange(int(SAMPLE_RATE * 0.3)) / SAMPLE_RATE
            samples = (0.3 * np.sin(2 * np.pi * frequency * times) * 32767).astype(
                np.int16
            )
            AudioSegment(
                data=samples.tobytes(),
                sample_width=2,
                frame_rate=SAMPLE_RATE,
                channels=1,
            ).export(str(tmp_path / name), format="wav")
        app = _app()

        run_join(
            str(tmp_path),
            order="a.wav,b.wav",
            settings=JoinSettings(),
            on_complete=app._on_complete,
        )

        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["total"] == 2
        assert payload["segments"] == 2
        assert payload["duration_ms"] == 600

        report = tmp_path / REPORT_NAMES[False]
        assert report.is_file(), "the run wrote no report for the handler's run"
        text = report.read_text(encoding="utf-8")
        assert text.startswith("AUDIO JOINER REPORT")
        assert "Planned length: 00:00.600" in text

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
