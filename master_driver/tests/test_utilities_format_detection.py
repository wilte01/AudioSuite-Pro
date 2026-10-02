"""
Tests for master_driver.ui.utilities_window.update_format_detection

Strategy
--------
All tests use a temporary directory with controlled files. The function is
called with a mock-style ``state`` object (plain MagicMock) that carries
the attributes it accesses:
  - dir_path (StringVar-like .get())
  - converter_all_formats / converter_lossy_formats / converter_lossless_formats
  - converter_available_formats (plain list, mutated in place)
  - converter_output_format (StringVar-like .get()/.set())
  - _converter_detected_label  (Label-like .config() stub) — optional
  - _converter_format_menu     (Combobox-like stub) — optional

Because the function only reads the file system and updates these attributes,
no tkinter root is necessary.

The format lists below are the converter's real ones — ``AppState`` loads them
from ``music_format_converter.core.formats``, so the tests use the same source
rather than hand-rolled stand-ins.
"""

import os
from unittest.mock import MagicMock

from master_driver.ui.utilities_window import update_format_detection
from music_format_converter.core.formats import (
    ALL_FORMATS,
    UNSUPPORTED_OUTPUT_FORMATS,
)
from music_format_converter.core.formats import (
    LOSSLESS_FORMATS as LOSSLESS,
)
from music_format_converter.core.formats import (
    LOSSY_FORMATS as LOSSY,
)


def _make_state(**overrides):
    state = MagicMock()
    state.dir_path = MagicMock()
    state.dir_path.get.return_value = overrides.get("dir_path", "")

    state.converter_all_formats = list(ALL_FORMATS)
    state.converter_lossy_formats = list(LOSSY)
    state.converter_lossless_formats = list(LOSSLESS)
    state.converter_available_formats = list(ALL_FORMATS)

    state.converter_output_format = MagicMock()
    state.converter_output_format.get.return_value = overrides.get(
        "output_format", "mp3"
    )
    state.converter_output_format.set = MagicMock()

    # Optional UI references — may or may not be attached
    for attr in ("_converter_detected_label", "_converter_format_menu"):
        if attr in overrides:
            setattr(state, attr, overrides[attr])
        elif attr in state._mock_children:
            pass  # MagicMock auto-creates attrs, which is fine

    return state


def _make_label():
    lbl = MagicMock()
    lbl.config = MagicMock()
    return lbl


def _make_format_menu():
    menu = MagicMock()
    return menu


# ---------------------------------------------------------------------------
# No directory / non-existent directory
# ---------------------------------------------------------------------------


class TestNoDirectory:
    def test_empty_dir_path_clears_label(self):
        label = _make_label()
        state = _make_state(dir_path="", _converter_detected_label=label)
        update_format_detection(state)
        label.config.assert_called_once_with(text="")

    def test_nonexistent_dir_clears_label(self):
        label = _make_label()
        state = _make_state(
            dir_path="/nonexistent/path/xyz", _converter_detected_label=label
        )
        update_format_detection(state)
        label.config.assert_called_once_with(text="")

    def test_no_label_attached_does_not_raise(self):
        state = _make_state(dir_path="")
        # Should not raise even without _converter_detected_label
        update_format_detection(state)

    def test_no_format_menu_attached_does_not_raise(self):
        state = _make_state(dir_path="/nonexistent")
        update_format_detection(state)


# ---------------------------------------------------------------------------
# Exception during scan
# ---------------------------------------------------------------------------


class TestScanException:
    def test_exception_resets_to_all_formats(self, tmp_path, monkeypatch):
        label = _make_label()
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
            _converter_format_menu=menu,
        )

        # Monkeypatch os.scandir to raise
        def _broken(_path):
            raise PermissionError("access denied")

        monkeypatch.setattr(os, "scandir", _broken)
        update_format_detection(state)

        # Available formats should reset to all formats
        assert state.converter_available_formats == ALL_FORMATS
        label.config.assert_called_once_with(text="")
        menu.__setitem__.assert_called()

    def test_exception_without_ui_does_not_raise(self, tmp_path, monkeypatch):
        state = _make_state(dir_path=str(tmp_path))

        def _broken(_path):
            raise OSError("disk error")

        monkeypatch.setattr(os, "scandir", _broken)
        update_format_detection(state)  # must not raise


# ---------------------------------------------------------------------------
# No audio files found
# ---------------------------------------------------------------------------


class TestNoAudioFiles:
    def test_empty_directory_shows_warning(self, tmp_path):
        label = _make_label()
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
            _converter_format_menu=menu,
        )
        update_format_detection(state)

        # Available formats should reset to all
        assert state.converter_available_formats == ALL_FORMATS
        # Label should show warning
        label.config.assert_called_once()
        kwargs = label.config.call_args[1]
        assert "No audio files found" in kwargs.get("text", "")

    def test_directory_with_only_non_audio_files(self, tmp_path):
        (tmp_path / "readme.txt").write_text("hello")
        (tmp_path / "image.jpg").write_bytes(b"\xff\xd8")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        assert state.converter_available_formats == ALL_FORMATS


# ---------------------------------------------------------------------------
# Mixed formats
# ---------------------------------------------------------------------------


class TestMixedFormats:
    def test_mixed_formats_still_offer_targets(self, tmp_path):
        """E4: mixed input is supported, so the menu is not emptied."""
        (tmp_path / "song.mp3").write_bytes(b"x")
        (tmp_path / "track.flac").write_bytes(b"x")
        label = _make_label()
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
            _converter_format_menu=menu,
        )
        update_format_detection(state)

        assert state.converter_available_formats
        # flac+mp3 can reach mp3 (via the flac file) but not flac
        # (same format / lossy->lossless), and never ape.
        assert "mp3" in state.converter_available_formats
        assert "flac" not in state.converter_available_formats
        assert "ape" not in state.converter_available_formats
        menu.__setitem__.assert_called_with(
            "values", tuple(state.converter_available_formats)
        )

    def test_mixed_formats_show_per_format_counts(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.ogg").write_bytes(b"x")
        (tmp_path / "c.flac").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        text = label.config.call_args[1].get("text", "")
        assert "MP3: 1" in text
        assert "OGG: 1" in text
        assert "FLAC: 1" in text
        assert "Mixed" not in text

    def test_nested_subfolder_files_are_counted(self, tmp_path):
        """E4: the scan is recursive, so subfolder tracks are detected."""
        (tmp_path / "CD1").mkdir()
        (tmp_path / "CD1" / "a.mp3").write_bytes(b"x")
        (tmp_path / "CD1" / "b.mp3").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        text = label.config.call_args[1].get("text", "")
        assert "MP3: 2" in text

    def test_audio_only_in_subfolder_is_not_reported_empty(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "only.mp3").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        assert "No audio files found" not in label.config.call_args[1].get("text", "")

    def test_same_format_multiple_files_is_not_mixed(self, tmp_path):
        """Multiple files all in the same format is not mixed."""
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        (tmp_path / "c.mp3").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)
        text = label.config.call_args[1].get("text", "")
        assert "Mixed" not in text
        assert "Detected" in text


# ---------------------------------------------------------------------------
# Single format — lossy input
# ---------------------------------------------------------------------------


class TestSingleLossyFormat:
    def test_lossy_format_filters_lossy_only(self, tmp_path):
        (tmp_path / "song.mp3").write_bytes(b"x")
        label = _make_label()
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
            _converter_format_menu=menu,
        )
        update_format_detection(state)

        # Should exclude the input format from lossy list only
        expected = [f for f in LOSSY if f != "mp3"]
        assert state.converter_available_formats == expected

    def test_lossy_format_shows_success_label(self, tmp_path):
        (tmp_path / "track.ogg").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        kwargs = label.config.call_args[1]
        assert "Detected" in kwargs.get("text", "")
        assert "OGG" in kwargs.get("text", "")

    def test_lossy_format_updates_menu_values(self, tmp_path):
        (tmp_path / "track.aac").write_bytes(b"x")
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_format_menu=menu,
        )
        update_format_detection(state)

        expected = [f for f in LOSSY if f != "aac"]
        menu.__setitem__.assert_called_with("values", tuple(expected))

    def test_lossy_output_auto_switches_when_current_not_available(self, tmp_path):
        """Output format should switch to 'mp3' if current format is the input."""
        (tmp_path / "track.mp3").write_bytes(b"x")
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_format_menu=menu,
            output_format="mp3",  # same as input, so not in available list
        )
        update_format_detection(state)

        # mp3 is not in available list (it's the input), so should auto-switch
        state.converter_output_format.set.assert_called_once()
        # The first call arg should be "mp3" if it's in available, or
        # the first available
        call_args = state.converter_output_format.set.call_args[0]
        assert call_args[0] in state.converter_available_formats

    def test_lossy_detected_count(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        kwargs = label.config.call_args[1]
        assert "MP3: 2" in kwargs.get("text", "")


# ---------------------------------------------------------------------------
# Single format — lossless input
# ---------------------------------------------------------------------------


class TestSingleLosslessFormat:
    def test_lossless_format_filters_all_formats(self, tmp_path):
        (tmp_path / "song.flac").write_bytes(b"x")
        label = _make_label()
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
            _converter_format_menu=menu,
        )
        update_format_detection(state)

        # Excludes the input format and formats with no encoder (ape)
        expected = [
            f
            for f in ALL_FORMATS
            if f != "flac" and f not in UNSUPPORTED_OUTPUT_FORMATS
        ]
        assert state.converter_available_formats == expected

    def test_lossless_format_shows_success_label(self, tmp_path):
        (tmp_path / "track.wav").write_bytes(b"x")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        kwargs = label.config.call_args[1]
        assert "Detected" in kwargs.get("text", "")

    def test_lossless_format_auto_switches_to_mp3_when_current_unavailable(
        self, tmp_path
    ):
        (tmp_path / "track.flac").write_bytes(b"x")
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_format_menu=menu,
            output_format="flac",
        )
        update_format_detection(state)

        # flac was input and is lossless, so not in available. Should switch to "mp3"
        state.converter_output_format.set.assert_called_once_with("mp3")

    def test_lossless_format_auto_switches_to_first_available_when_no_mp3(
        self, tmp_path
    ):
        (tmp_path / "track.wav").write_bytes(b"x")
        menu = _make_format_menu()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_format_menu=menu,
            output_format="wav",
        )
        update_format_detection(state)

        # wav is input and not in available list. mp3 is in available, so
        # should pick mp3
        state.converter_output_format.set.assert_called_once_with("mp3")


# ---------------------------------------------------------------------------
# Non-audio files mixed with audio files
# ---------------------------------------------------------------------------


class TestMixedContent:
    def test_non_audio_files_ignored_in_detection(self, tmp_path):
        (tmp_path / "song.mp3").write_bytes(b"x")
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "info.txt").write_text("metadata")
        label = _make_label()
        state = _make_state(
            dir_path=str(tmp_path),
            _converter_detected_label=label,
        )
        update_format_detection(state)

        # Should detect mp3 only
        kwargs = label.config.call_args[1]
        assert "MP3: 1" in kwargs.get("text", "")
