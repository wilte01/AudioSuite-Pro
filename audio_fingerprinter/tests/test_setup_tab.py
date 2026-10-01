"""Tests for audio_fingerprinter.ui.setup_tab."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from audio_fingerprinter.ui.setup_tab import _SetupFrame, build


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def tk_vars(root: tk.Tk):
    return {
        "folder_path": tk.StringVar(root, value="/music"),
        "run_mode": tk.StringVar(root, value="Dry Run"),
        "auto_start_var": tk.BooleanVar(root, value=False),
        "auto_end_var": tk.BooleanVar(root, value=False),
        "clear_logs_var": tk.BooleanVar(root, value=False),
        "parallel_var": tk.BooleanVar(root, value=False),
        "lookup_enabled": tk.BooleanVar(root, value=True),
        "write_tags": tk.BooleanVar(root, value=False),
        "write_mbids": tk.BooleanVar(root, value=False),
        "mbid_region": tk.StringVar(root, value=""),
        "album_mode": tk.BooleanVar(root, value=False),
        "threshold": tk.StringVar(root, value="0.5"),
        "max_length": tk.StringVar(root, value="120"),
        "fpcalc_path": tk.StringVar(root, value=""),
        "api_key": tk.StringVar(root, value=""),
        "api_key_status": tk.StringVar(root, value=""),
    }


class TestBuild:
    def test_returns_dict_with_all_keys(self, root, tk_vars):
        result = build(
            root,
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
            clear_logs_var=tk_vars["clear_logs_var"],
            parallel_var=tk_vars["parallel_var"],
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse=MagicMock(),
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            on_start=MagicMock(),
        )
        assert isinstance(result, dict)
        assert "start_btn" in result
        assert "fpcalc_status_label" in result
        assert "update_fpcalc_status" in result
        assert "controls_panel" in result

    def test_layout_fits(self, root, tk_vars):
        result = build(
            root,
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
            clear_logs_var=tk_vars["clear_logs_var"],
            parallel_var=tk_vars["parallel_var"],
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse=MagicMock(),
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            on_start=MagicMock(),
        )
        assert result["start_btn"] is not None
        assert result["fpcalc_status_label"] is not None


class TestSetupFrameInit:
    def test_constructs(self, root, tk_vars):
        frame = _SetupFrame(
            root,
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            title="Audio Fingerprinter",
            start_text="START FINGERPRINTING",
            on_start=MagicMock(),
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
        )
        assert frame is not None
        assert hasattr(frame, "update_fpcalc_status")

    def test_has_fpcalc_status(self, root, tk_vars):
        frame = _SetupFrame(
            root,
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            title="Audio Fingerprinter",
            start_text="START FINGERPRINTING",
            on_start=MagicMock(),
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
        )
        assert isinstance(frame.fpcalc_status_label, tk.Label)


def _find_checkbuttons(widget: tk.Widget) -> list[tk.Checkbutton]:
    """Recursively collect every Checkbutton under a widget."""
    found: list[tk.Checkbutton] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            found.append(child)
        found.extend(_find_checkbuttons(child))
    return found


class TestAlbumModeCheckbox:
    def test_album_mode_checkbutton_bound_to_var(self, root, tk_vars):
        frame = _SetupFrame(
            root,
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            title="Audio Fingerprinter",
            start_text="START FINGERPRINTING",
            on_start=MagicMock(),
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
        )
        buttons = _find_checkbuttons(frame)
        album_buttons = [
            b for b in buttons if str(b.cget("variable")) == str(tk_vars["album_mode"])
        ]
        assert album_buttons, "Album Match checkbox must bind the album_mode var"
        assert any("Album Match" in str(b.cget("text")) for b in album_buttons)


class TestMbidCheckbox:
    def test_write_mbids_checkbutton_bound_to_var(self, root, tk_vars):
        frame = _SetupFrame(
            root,
            lookup_enabled=tk_vars["lookup_enabled"],
            write_tags=tk_vars["write_tags"],
            write_mbids=tk_vars["write_mbids"],
            mbid_region=tk_vars["mbid_region"],
            album_mode=tk_vars["album_mode"],
            threshold=tk_vars["threshold"],
            max_length=tk_vars["max_length"],
            fpcalc_path=tk_vars["fpcalc_path"],
            api_key=tk_vars["api_key"],
            api_key_status=tk_vars["api_key_status"],
            on_browse_fpcalc=MagicMock(),
            on_save_api_key=MagicMock(),
            on_clear_api_key=MagicMock(),
            title="Audio Fingerprinter",
            start_text="START FINGERPRINTING",
            on_start=MagicMock(),
            folder_path=tk_vars["folder_path"],
            run_mode=tk_vars["run_mode"],
            auto_start_var=tk_vars["auto_start_var"],
            auto_end_var=tk_vars["auto_end_var"],
        )
        buttons = _find_checkbuttons(frame)
        mbid_buttons = [
            b for b in buttons if str(b.cget("variable")) == str(tk_vars["write_mbids"])
        ]
        assert mbid_buttons, "MBID checkbox must bind the write_mbids var"
        assert any(
            "MusicBrainz identifiers" in str(b.cget("text")) for b in mbid_buttons
        )
