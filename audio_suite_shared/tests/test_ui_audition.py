"""
test_ui_audition.py — Unit tests for audio_suite_shared.ui_audition.

Strategy
--------
Node: all widget construction (``add_audition_buttons``) is gated behind
``requires_display``.  The ``AuditionMixin`` state machine is tested with a
Mock-based root window so no real Tk is needed.

Changed in 2.7.0: ``TestMatchGains`` locks the attenuation-only arithmetic and
``TestMatchedAudition`` renders real tones and measures the previews it gets
back, rather than trusting the gain the code reports (F-S9).

Changed in 2.9.0: the module declares the session-scoped Tk root with
``clean_shared_root``, so the widgets its tests build there are destroyed after
each test and cannot reach another module's walk of the root.
"""

from __future__ import annotations

import math
import os
import sys
import tkinter as tk
import wave
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
    match_gains,
    set_result_available,
)

pytestmark = pytest.mark.usefixtures("clean_shared_root")

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
            "level_match_var",
            "blind_var",
        }

    def test_the_match_switches_start_off(self, tk_root: Any) -> None:
        widgets = self._build(tk_root, with_match_options=True)

        assert widgets["level_match_var"].get() is False
        assert widgets["blind_var"].get() is False

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


def _write_tone(path: Path, amplitude: float, *, seconds: float = 2.0) -> Path:
    """Write a real stereo tone at *amplitude* of full scale.

    Args:
        path: Destination ``.wav`` path.
        amplitude: Peak as a fraction of full scale (0.5 is -6.02 dBFS).
        seconds: Length in seconds.
    """
    rate = 44100
    frames = bytearray()
    for index in range(int(rate * seconds)):
        sample = int(amplitude * 32767 * math.sin(2 * math.pi * 440 * index / rate))
        frames += sample.to_bytes(2, "little", signed=True) * 2
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(bytes(frames))
    return path


class _Flag:
    """A stand-in for a Tk BooleanVar: only ``get`` is used."""

    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


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


# ---------------------------------------------------------------------------
# F-S9 — level-matched and blind A/B
# ---------------------------------------------------------------------------


class TestMatchGains:
    """The arithmetic of a fair A/B: attenuate the louder, never boost."""

    def test_the_louder_original_is_attenuated(self) -> None:
        assert match_gains(-10.0, -16.0) == (-6.0, 0.0)

    def test_the_louder_result_is_attenuated(self) -> None:
        assert match_gains(-16.0, -10.0) == (0.0, -6.0)

    def test_an_equal_pair_is_left_alone(self) -> None:
        assert match_gains(-14.0, -14.0) == (0.0, 0.0)

    def test_no_gain_is_ever_positive(self) -> None:
        for original, result in ((-3.0, -30.0), (-30.0, -3.0), (-9.0, -9.5)):
            gains = match_gains(original, result)
            assert max(gains) <= 0.0, (original, result, gains)

    def test_a_silent_file_is_refused(self) -> None:
        with pytest.raises(ValueError):
            match_gains(float("-inf"), -14.0)


class TestMatchedAudition:
    """The previews are measured, not the gain the code says it applied."""

    def test_the_two_previews_measure_within_a_tenth_of_a_lu(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        from audio_suite_shared.audio_probe import measure_loudness

        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)

        matched = app.prepare_matched_audition(original, result)

        assert matched is not None
        original_lufs = measure_loudness(str(matched.original)).integrated_lufs
        result_lufs = measure_loudness(str(matched.result)).integrated_lufs
        assert abs(original_lufs - result_lufs) <= 0.1
        assert matched.gain_original_db == pytest.approx(-6.02, abs=0.2)
        assert matched.gain_result_db == 0.0

    def test_the_sources_are_not_modified(self, app: _StubApp, tmp_path: Path) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)
        before = [
            (path.stat().st_size, path.stat().st_mtime_ns)
            for path in (original, result)
        ]

        app.prepare_matched_audition(original, result)

        after = [
            (path.stat().st_size, path.stat().st_mtime_ns)
            for path in (original, result)
        ]
        assert after == before

    def test_unmeasurable_audio_reports_why(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        broken = tmp_path / "notes.txt"
        broken.write_text("not audio", encoding="utf-8")

        matched = app.prepare_matched_audition(original, broken)

        assert matched is None
        assert _scheduled(app)[-1][2].startswith("Level match unavailable")

    def test_blind_labels_do_not_reveal_the_mapping(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)

        matched = app.prepare_matched_audition(original, result, blind=True)

        assert matched is not None and matched.blind
        assert app._play_original_btn.config.call_args.kwargs["text"].endswith("Play A")
        assert app._play_result_btn.config.call_args.kwargs["text"].endswith("Play B")
        caption = _scheduled(app)[-1][2].lower()
        assert caption.startswith("blind a/b"), caption
        assert "original" not in caption and "result" not in caption
        mapping = app.reveal_blind()
        assert mapping is not None
        assert sorted(mapping) == ["A", "B"]
        assert sorted(mapping.values()) == ["original", "result"]

    def _fake_matched(self, tmp_path: Path, *, blind: bool = False) -> Any:
        from audio_suite_shared.ui_audition import MatchedAudition

        preview_original = _write_tone(tmp_path / "matched_original.wav", 0.5)
        preview_result = _write_tone(tmp_path / "matched_result.wav", 0.5)
        return MatchedAudition(
            original=preview_original,
            result=preview_result,
            original_lufs=-9.7,
            result_lufs=-9.7,
            gain_original_db=0.0,
            gain_result_db=0.0,
            blind=blind,
        )

    def _played(self, app: _StubApp, monkeypatch: pytest.MonkeyPatch) -> list[Path]:
        played: list[Path] = []
        monkeypatch.setattr(
            "audio_suite_shared.ui_audition.audio_playback.play_audio",
            lambda path: played.append(Path(path)) or True,
        )
        return played

    def test_unchecked_plays_the_source_file(
        self, app: _StubApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)
        app._audition_original = original
        app._audition_result = result
        app._source_pair = (original, result)
        app._level_match_var = None
        played = self._played(app, monkeypatch)

        app._play_original()

        assert played == [original], "an unticked switch must change nothing"

    def test_checked_plays_the_matched_preview(
        self, app: _StubApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)
        matched = self._fake_matched(tmp_path)
        app._audition_original = original
        app._audition_result = result
        app._source_pair = (original, result)
        app._level_match_var = _Flag(True)
        app._blind_var = _Flag(False)
        monkeypatch.setattr(
            app, "prepare_matched_audition", lambda *a, **k: matched, raising=False
        )
        played = self._played(app, monkeypatch)

        app._play_original()

        assert played == [matched.original]
        assert "level matched" in _last_caption(app)

    def test_the_matched_pair_is_prepared_once(
        self, app: _StubApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)
        matched = self._fake_matched(tmp_path)
        calls: list[Any] = []
        app._audition_original = original
        app._audition_result = result
        app._source_pair = (original, result)
        app._level_match_var = _Flag(True)
        app._blind_var = _Flag(False)
        monkeypatch.setattr(
            app,
            "prepare_matched_audition",
            lambda *a, **k: calls.append(a) or matched,
            raising=False,
        )
        self._played(app, monkeypatch)

        app._play_original()
        app._play_result()

        assert len(calls) == 1, "a blind pair must not be re-randomised per click"

    def test_a_blind_click_uses_the_lettered_preview(
        self, app: _StubApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)
        result = _write_tone(tmp_path / "result.wav", 0.25)
        matched = self._fake_matched(tmp_path, blind=True)
        app._audition_original = original
        app._audition_result = result
        app._source_pair = (original, result)
        app._level_match_var = _Flag(True)
        app._blind_var = _Flag(True)
        app._blind_mapping = {"A": "result", "B": "original"}
        monkeypatch.setattr(
            app, "prepare_matched_audition", lambda *a, **k: matched, raising=False
        )
        played = self._played(app, monkeypatch)

        app._play_original()

        assert played == [matched.result], "A is the result in this mapping"
        assert "Playing B" in _last_caption(app)

    def test_a_plain_pair_has_nothing_to_reveal(
        self, app: _StubApp, tmp_path: Path
    ) -> None:
        original = _write_tone(tmp_path / "original.wav", 0.5)

        app.prepare_matched_audition(original, original)

        assert app.reveal_blind() is None
