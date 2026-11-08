"""The window's non-display half: settings, and the three callback seams.

The app is built with ``object.__new__`` and mock variables, so no real display
is needed; the widget wiring itself is exercised by the shared shell contract.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import channel_ops
from audio_suite_shared.exceptions import AudioConfigValueError
from channel_tools.app import OPERATION_LABELS, ChannelToolsApp
from channel_tools.core.models import ChannelSettings
from channel_tools.core.processor import run_channels


def _var(value: Any) -> MagicMock:
    var = MagicMock()
    var.get.return_value = value
    return var


def _app(
    *,
    operation: str | None = None,
    width: str = "100",
    channel: str = "Left",
    invert: str = "Both sides",
) -> ChannelToolsApp:
    app = object.__new__(ChannelToolsApp)
    label = operation or next(iter(OPERATION_LABELS))
    app.operation_label = _var(label)
    app.width_percent = _var(width)
    app.channel_label = _var(channel)
    app.invert_label = _var(invert)
    app._events = queue.SimpleQueue()
    return app


class TestSettings:
    """The combobox labels resolve to the shared operation ids."""

    def test_labels_map_onto_the_shared_ids(self) -> None:
        settings = _app()._settings()
        label = next(iter(OPERATION_LABELS))
        assert settings.operation == OPERATION_LABELS[label]

    def test_the_width_is_read_as_a_number(self) -> None:
        app = _app(
            operation="Stereo width (scale the side signal, then decode)", width="50"
        )
        assert app._settings().width_percent == 50.0

    def test_a_non_numeric_width_is_refused(self) -> None:
        with pytest.raises(ValueError):
            _app(width="wide")._settings()

    def test_a_width_out_of_range_is_refused(self) -> None:
        app = _app(
            operation="Stereo width (scale the side signal, then decode)",
            width="900",
        )
        with pytest.raises(AudioConfigValueError, match="Stereo width"):
            app._settings()

    def test_the_channel_and_invert_labels_resolve(self) -> None:
        app = _app(
            operation="Dual mono (one channel copied to both)",
            channel="Right",
            invert="Left only",
        )
        settings = app._settings()
        assert settings.source_channel == "right"
        assert settings.invert_target == "left"


class TestCompletionPayloads:
    """A payload with extra fields is absorbed, and its extras survive."""

    def test_the_completion_payload_keeps_the_tools_fields(self) -> None:
        app = _app()
        app._on_complete(
            total=2,
            processed=2,
            skipped=1,
            errors=0,
            duration_secs=0.5,
            succeeded=1,
            report="report.txt",
            rule="mono sum: 0.5 x (L + R)",
        )
        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["total"] == 2
        assert payload["succeeded"] == 1
        assert payload["report"] == "report.txt"

    def test_progress_and_error_payloads_cross_the_queue(self) -> None:
        app = _app()
        app._on_progress(
            processed=1,
            total=3,
            succeeded=1,
            skipped=0,
            errors=0,
            display_text="[FIXED] song.wav",
        )
        app._on_error("the folder does not exist")
        assert app._events.get_nowait()[0] == "progress"
        kind, message = app._events.get_nowait()
        assert kind == "error"
        assert message == "the folder does not exist"


class TestCompletionSeam:
    """The real ``run_channels`` publishes into the handler the window binds."""

    def test_the_published_payload_reaches_the_queued_completion(
        self, tmp_path: Path
    ) -> None:
        from pydub import AudioSegment
        from pydub.generators import Sine

        left = Sine(440).to_audio_segment(duration=200, volume=-10)
        right = Sine(220).to_audio_segment(duration=200, volume=-10)
        AudioSegment.from_mono_audiosegments(left, right).export(
            str(tmp_path / "song.wav"), format="wav"
        )
        app = _app()
        run_channels(
            str(tmp_path),
            settings=ChannelSettings(),
            dry_run=False,
            on_complete=app._on_complete,
        )
        kind, payload = app._events.get_nowait()
        assert kind == "complete"
        assert payload["total"] == 1
        assert payload["succeeded"] == 1
        assert payload["report"].endswith("channel_tools_sync_log.txt")


class TestOperationTable:
    """The combobox lists every shared operation exactly once."""

    def test_every_operation_has_one_label(self) -> None:
        assert set(OPERATION_LABELS.values()) == set(channel_ops.OPERATION_IDS)
        assert len(OPERATION_LABELS) == len(channel_ops.OPERATIONS)
