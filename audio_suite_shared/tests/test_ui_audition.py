"""
test_ui_audition.py — Unit tests for audio_suite_shared.ui_audition.

Strategy
--------
Node: all widget construction (``add_audition_buttons``) is gated behind
``requires_display``.  The ``AuditionMixin`` state machine is tested with a
Mock-based root window so no real Tk is needed.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.ui_audition import (
    _LOCKED_MSG,
    _NO_SOURCE_MSG,
    _READY_MSG,
    AuditionMixin,
    add_audition_buttons,
    set_result_available,
)

_EXTS: tuple[str, ...] = (".mp3", ".wav")


def _has_display() -> bool:
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


requires_display = pytest.mark.skipif(
    not _has_display(), reason="No graphical display — Tkinter unavailable"
)


# ---------------------------------------------------------------------------
# add_audition_buttons / set_result_available (real widgets)
# ---------------------------------------------------------------------------


@requires_display
class TestAddAuditionButtons:
    def _build(self, tk_root: Any, **kwargs: Any) -> dict[str, Any]:
        return add_audition_buttons(tk_root, lambda: None, lambda: None, **kwargs)

    def test_returns_expected_keys(self, tk_root: Any) -> None:
        widgets = self._build(tk_root)
        assert set(widgets) == {
            "play_original_btn",
            "play_result_btn",
            "caption_var",
        }

    def test_play_result_disabled_by_default(self, tk_root: Any) -> None:
        widgets = self._build(tk_root)
        assert str(widgets["play_result_btn"]["state"]) == "disabled"
        assert str(widgets["play_original_btn"]["state"]) == "normal"

    def test_play_result_enabled_when_available(self, tk_root: Any) -> None:
        widgets = self._build(tk_root, result_available=True)
        assert str(widgets["play_result_btn"]["state"]) == "normal"

    def test_default_caption_is_ready(self, tk_root: Any) -> None:
        widgets = self._build(tk_root)
        assert widgets["caption_var"].get() == _READY_MSG

    def test_caption_var_reused_when_provided(self, tk_root: Any) -> None:
        caption_var = tk.StringVar(value="custom")
        widgets = self._build(tk_root, caption_var=caption_var)
        assert widgets["caption_var"] is caption_var
        assert caption_var.get() == "custom"

    def test_set_result_available_toggles(self, tk_root: Any) -> None:
        widgets = self._build(tk_root)
        set_result_available(widgets["play_result_btn"], True)
        assert str(widgets["play_result_btn"]["state"]) == "normal"
        set_result_available(widgets["play_result_btn"], False)
        assert str(widgets["play_result_btn"]["state"]) == "disabled"


class _StubApp(AuditionMixin):
    pass


@pytest.fixture
def app() -> _StubApp:
    instance = _StubApp()
    instance.root = MagicMock()
    instance._play_original_btn = MagicMock()
    instance._play_result_btn = MagicMock()
    instance._audition_caption_var = MagicMock()
    instance._audition_original = None
    instance._audition_result = None
    return instance


def _scheduled(app: _StubApp) -> list[tuple[int, object, str]]:
    """All (delay, callback, caption) tuples queued via the mocked root."""
    calls = []
    for call in app.root.after.call_args_list:
        args = call[0]
        if (
            len(args) == 3
            and args[0] == 0
            and callable(args[1])
            and isinstance(args[2], str)
        ):
            calls.append((args[0], args[1], args[2]))
    return calls


def _last_caption(app: _StubApp) -> str:
    calls = app._audition_caption_var.set.call_args_list
    return calls[-1][0][0] if calls else ""


# ---------------------------------------------------------------------------
# AuditionMixin — lifecycle and state (no real display required)
# ---------------------------------------------------------------------------


class TestSetupAudition:
    def test_binds_widgets_and_close_handler(self, app: _StubApp) -> None:
        original_btn = MagicMock()
        result_btn = MagicMock()
        caption_var = MagicMock()
        widgets = {
            "play_original_btn": original_btn,
            "play_result_btn": result_btn,
            "audition_caption_var": caption_var,
        }
        app.setup_audition(widgets)
        assert app._play_original_btn is original_btn
        assert app._play_result_btn is result_btn
        assert app._audition_caption_var is caption_var
        assert app._audition_original is None
        assert app._audition_result is None
        app.root.protocol.assert_called_once_with(
            "WM_DELETE_WINDOW", app._audition_close
        )

    def test_set_audition_state_stores_pair_and_schedules(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        original = tmp_path / "a.mp3"
        result = tmp_path / "b.mp3"
        app.set_audition_state(original, result, "ready")
        assert app._audition_original == original
        assert app._audition_result == result
        assert _scheduled(app) == [(0, app._apply_audition_state, "ready")]

    def test_apply_audition_state_widgets(self, app: _StubApp, tmp_path: Path) -> None:
        original = tmp_path / "a.mp3"
        result = tmp_path / "b.mp3"
        app.set_audition_state(original, result, "ready")
        app._apply_audition_state("ready")
        app._play_original_btn.config.assert_called_once_with(state="normal")
        app._play_result_btn.config.assert_called_once_with(state="normal")
        app._audition_caption_var.set.assert_called_once_with("ready")

    def test_apply_audition_state_disables_when_empty(self, app: _StubApp) -> None:
        app.set_audition_state(None, None, "empty")
        app._apply_audition_state("empty")
        app._play_original_btn.config.assert_called_once_with(state="disabled")
        app._play_result_btn.config.assert_called_once_with(state="disabled")
        app._audition_caption_var.set.assert_called_once_with("empty")

    def test_clear_audition_locks(self, app: _StubApp, tmp_path: Path) -> None:
        app._audition_original = tmp_path / "a.mp3"
        app._audition_result = tmp_path / "b.mp3"
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.clear_snapshots"
        ) as mock_clear:
            app.clear_audition()
        mock_clear.assert_called_once()
        assert app._audition_original is None
        assert app._audition_result is None
        assert _scheduled(app) == [(0, app._apply_audition_state, _LOCKED_MSG)]


class TestPrepareInPlace:
    def test_captures_snapshot_with_default_result(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        source = tmp_path / "track.mp3"
        source.write_bytes(b"audio")
        snapshot = tmp_path / "snap" / "track_orig.mp3"
        with (
            patch("audio_suite_shared.ui_audition.audio_playback.clear_snapshots"),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.peek_first_audio",
                return_value=source,
            ),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.create_original_snapshot",
                return_value=snapshot,
            ),
        ):
            app.prepare_in_place_audition(source, _EXTS)
        assert app._audition_original == snapshot
        assert app._audition_result == source
        scheduled = _scheduled(app)
        assert scheduled[0][1] == app._apply_audition_state
        assert "Original captured: track.mp3" in scheduled[0][2]

    def test_result_path_override(self, app: _StubApp, tmp_path: Path) -> None:
        source = tmp_path / "track.mp3"
        source.write_bytes(b"audio")
        snapshot = tmp_path / "snap" / "track_orig.mp3"
        result = tmp_path / "enhanced" / "out.mp3"
        with (
            patch("audio_suite_shared.ui_audition.audio_playback.clear_snapshots"),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.peek_first_audio",
                return_value=source,
            ),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.create_original_snapshot",
                return_value=snapshot,
            ),
        ):
            app.prepare_in_place_audition(source, _EXTS, result_path=result)
        assert app._audition_result == result

    def test_no_source_reports_caption(self, app: _StubApp, tmp_path: Path) -> None:
        with (
            patch("audio_suite_shared.ui_audition.audio_playback.clear_snapshots"),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.peek_first_audio",
                return_value=None,
            ),
        ):
            app.prepare_in_place_audition(tmp_path, _EXTS)
        assert app._audition_original is None
        assert app._audition_result is None
        assert _scheduled(app)[0][2] == _NO_SOURCE_MSG

    def test_snapshot_failure_reports_caption(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        source = tmp_path / "track.mp3"
        source.write_bytes(b"audio")
        with (
            patch("audio_suite_shared.ui_audition.audio_playback.clear_snapshots"),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.peek_first_audio",
                return_value=source,
            ),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.create_original_snapshot",
                return_value=None,
            ),
        ):
            app.prepare_in_place_audition(source, _EXTS)
        assert _scheduled(app)[0][2] == _NO_SOURCE_MSG


class TestPlayButtons:
    def test_play_original_success(self, app: _StubApp, tmp_path: Path) -> None:
        original = tmp_path / "track_orig.mp3"
        original.write_bytes(b"audio")
        app._audition_original = original
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.play_audio",
            return_value=True,
        ) as mock_play:
            app._play_original()
        mock_play.assert_called_once_with(original)
        assert _last_caption(app) == "Playing original — track_orig.mp3"

    def test_play_original_missing_path(self, app: _StubApp, tmp_path: Path) -> None:
        app._audition_original = tmp_path / "gone.mp3"
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.play_audio"
        ) as mock_play:
            app._play_original()
        mock_play.assert_not_called()
        assert _last_caption(app) == "Original not available."

    def test_play_original_none(self, app: _StubApp) -> None:
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.play_audio"
        ) as mock_play:
            app._play_original()
        mock_play.assert_not_called()
        assert _last_caption(app) == "Original not available."

    def test_play_original_failure_uses_describe(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        original = tmp_path / "track_orig.mp3"
        original.write_bytes(b"audio")
        app._audition_original = original
        with (
            patch(
                "audio_suite_shared.ui_audition.audio_playback.play_audio",
                return_value=False,
            ),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.describe_failure",
                return_value="boom",
            ),
        ):
            app._play_original()
        assert _last_caption(app) == "boom"

    def test_play_result_success(self, app: _StubApp, tmp_path: Path) -> None:
        result = tmp_path / "track.mp3"
        result.write_bytes(b"audio")
        app._audition_result = result
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.play_audio",
            return_value=True,
        ) as mock_play:
            app._play_result()
        mock_play.assert_called_once_with(result)
        assert _last_caption(app) == "Playing result — track.mp3"

    def test_play_result_missing_path(self, app: _StubApp) -> None:
        app._audition_result = Path("gone.mp3")
        with patch(
            "audio_suite_shared.ui_audition.audio_playback.play_audio"
        ) as mock_play:
            app._play_result()
        mock_play.assert_not_called()
        assert _last_caption(app) == "Result not available."

    def test_play_result_failure_uses_describe(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        result = tmp_path / "track.mp3"
        result.write_bytes(b"audio")
        app._audition_result = result
        with (
            patch(
                "audio_suite_shared.ui_audition.audio_playback.play_audio",
                return_value=False,
            ),
            patch(
                "audio_suite_shared.ui_audition.audio_playback.describe_failure",
                return_value="boom",
            ),
        ):
            app._play_result()
        assert _last_caption(app) == "boom"


class TestAuditionClose:
    def test_stops_playback_and_destroys(self, app: _StubApp) -> None:
        with (
            patch(
                "audio_suite_shared.ui_audition.audio_playback.stop_playback"
            ) as mock_stop,
            patch(
                "audio_suite_shared.ui_audition.audio_playback.clear_snapshots"
            ) as mock_clean,
        ):
            app._audition_close()
        mock_stop.assert_called_once()
        mock_clean.assert_called_once()
        app.root.destroy.assert_called_once()
