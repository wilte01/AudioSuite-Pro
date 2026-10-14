"""
Tests for master_driver.ui.cards.*

Strategy
--------
All tkinter widgets are constructed against a real (but hidden) Tk root so
that pack/grid geometry calls and variable bindings execute without error.
A single ``root`` fixture creates the root once for the whole session; each
test gets a fresh ``tk.Frame`` parent so widgets from different tests cannot
interfere.

What is verified for each card
--------------------------------
1.  ``build()`` completes without raising any exception.
2.  The header Checkbutton/Radiobutton is wired to the correct state variable.
3.  The expand/collapse button toggles the body frame in and out.
4.  Parameter Entry / Combobox widgets are wired to the correct state variable.
5.  Edge-case: ``build()`` is idempotent — calling it twice on separate parents
    does not raise.

Because cards are pure UI composition (no business logic), these tests focus
on *construction correctness and widget-variable binding*, not on visual
appearance.

Changed in 1.0.1: updates the Library Statistics card fixture.
"""

import sys
import tkinter as tk
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Headless Tk setup
# ---------------------------------------------------------------------------
# The `root` fixture (session-scoped, real hidden Tk()) is provided by
# conftest.py and shared across all test files in this directory.


@pytest.fixture()
def parent(root):
    """Fresh Frame parent for each test so geometry state is isolated."""
    frame = tk.Frame(root)
    yield frame
    frame.destroy()


# ---------------------------------------------------------------------------
# AppState stub — real tk variables, no audio_suite_shared dependency
# ---------------------------------------------------------------------------


def _make_state(root_widget):
    """Build a minimal AppState-like namespace with real tk variables."""
    state = MagicMock()

    # Core tk variables (real, so pack/trace calls work)
    state.module_toggles = {
        key: tk.BooleanVar(root_widget, value=False)
        for key in (
            "scrubber",
            "album_genre",
            "genre_sync",
            "replaygain",
            "bpm",
            "tempo",
            "key",
            "mood_analyzer",
            "art",
            "lyrics_manager",
            "converter",
            "asx_extractor",
            "cd_ripper",
            "library_stats",
            "tag_field_updater",
            "tag_editor",
            "audio_enhancer",
            "audio_normalizer",
            "pop_click_remover",
            "silence_trimmer",
            "noise_reduction",
            "fingerprinter",
            "file_reorganizer",
            "mood_analysis_batch",
            "album_art_normalizer",
        )
    }

    state.scrubber_preserve_lyrics = tk.BooleanVar(root_widget, value=True)
    state.scrubber_preserve_album_artist = tk.BooleanVar(root_widget, value=True)
    state.scrubber_preserve_embedded_art = tk.BooleanVar(root_widget, value=True)
    state.album_genre_coverage = tk.StringVar(root_widget, value="50")
    state.rg_lufs = tk.StringVar(root_widget, value="-16.0")
    state.bpm_range_min = tk.StringVar(root_widget, value="75")
    state.bpm_range_max = tk.StringVar(root_widget, value="175")
    state.bpm_duration = tk.StringVar(root_widget, value="90")
    state.tempo_scheme = tk.StringVar(root_widget, value="Italian")
    state.key_duration = tk.StringVar(root_widget, value="90")
    state.key_parallel = tk.BooleanVar(root_widget, value=False)
    state.key_workers = tk.StringVar(root_widget, value="4")
    state.mood_duration = tk.StringVar(root_widget, value="90")
    state.mood_parallel = tk.BooleanVar(root_widget, value=False)
    state.mood_workers = tk.StringVar(root_widget, value="4")
    state.mood_analysis_batch_duration = tk.StringVar(root_widget, value="90")
    state.mood_analysis_batch_parallel = tk.BooleanVar(root_widget, value=False)
    state.mood_analysis_batch_workers = tk.StringVar(root_widget, value="4")
    state.art_normalizer_size = tk.StringVar(root_widget, value="800")
    state.art_res = tk.StringVar(root_widget, value="800")
    state.art_purge = tk.BooleanVar(root_widget, value=True)
    state.lyrics_provider = tk.StringVar(root_widget, value="lrclib")
    state.lyrics_request_timeout = tk.StringVar(root_widget, value="10.0")
    state.lyrics_skip_existing = tk.BooleanVar(root_widget, value=True)
    state.lyrics_plain_fallback = tk.BooleanVar(root_widget, value=True)
    state.lyrics_parallel = tk.BooleanVar(root_widget, value=False)
    state.lyrics_workers = tk.StringVar(root_widget, value="4")

    state.converter_toggle = tk.BooleanVar(root_widget, value=False)
    state.converter_output_format = tk.StringVar(root_widget, value="mp3")
    state.converter_quality = tk.StringVar(root_widget, value="highest")
    state.converter_delete_originals = tk.BooleanVar(root_widget, value=False)
    state.converter_output_dir = tk.StringVar(root_widget, value="")

    state.asx_extractor_toggle = tk.BooleanVar(root_widget, value=False)
    state.cd_ripper_toggle = tk.BooleanVar(root_widget, value=False)

    state.enhancer_output_dir = tk.StringVar(root_widget, value="")
    state.enhancer_preset = tk.StringVar(root_widget, value="Moderate")
    state.normalizer_target_lufs = tk.StringVar(root_widget, value="-14.0")
    state.normalizer_tolerance = tk.StringVar(root_widget, value="0.5")
    state.normalizer_mode = tk.StringVar(root_widget, value="normalise")
    state.declick_sensitivity = tk.StringVar(root_widget, value="0.25")
    state.declick_max_width = tk.StringVar(root_widget, value="5")
    state.trimmer_threshold = tk.StringVar(root_widget, value="-50")
    state.trimmer_apply_fade = tk.BooleanVar(root_widget, value=False)
    state.trimmer_fade_in_ms = tk.StringVar(root_widget, value="500")
    state.trimmer_fade_out_ms = tk.StringVar(root_widget, value="1000")

    state.nr_reduce_hum = tk.BooleanVar(root_widget, value=False)
    state.nr_hum_frequency = tk.StringVar(root_widget, value="60")
    state.nr_hum_harmonics = tk.StringVar(root_widget, value="8")
    state.nr_hum_quality = tk.StringVar(root_widget, value="30.0")
    state.nr_reduce_broadband = tk.BooleanVar(root_widget, value=False)
    state.nr_noise_start = tk.StringVar(root_widget, value="0")
    state.nr_noise_end = tk.StringVar(root_widget, value="500")
    state.nr_gate_threshold = tk.StringVar(root_widget, value="3.0")

    state.fingerprinter_lookup = tk.BooleanVar(root_widget, value=True)
    state.fingerprinter_write_tags = tk.BooleanVar(root_widget, value=False)
    state.fingerprinter_threshold = tk.StringVar(root_widget, value="0.5")
    state.fingerprinter_max_length = tk.StringVar(root_widget, value="120")
    state.fingerprinter_fpcalc = tk.StringVar(root_widget, value="")
    state.fingerprinter_api_key = tk.StringVar(root_widget, value="")

    state.library_stats_toggle = tk.BooleanVar(root_widget, value=False)
    state.library_stats_incremental = tk.StringVar(root_widget, value="full")
    state.library_stats_refresh = tk.BooleanVar(root_widget, value=False)
    state.library_stats_export_csv = tk.StringVar(root_widget, value="")
    state.library_stats_export_json = tk.StringVar(root_widget, value="")

    state.file_reorg_output_dir = tk.StringVar(root_widget, value="")
    state.file_reorg_action = tk.StringVar(root_widget, value="move")
    state.file_reorg_specific_pattern = tk.StringVar(root_widget, value="")
    state.file_reorg_various_pattern = tk.StringVar(root_widget, value="")

    state.palette_var = tk.StringVar(root_widget, value="Purple")
    state.theme_mode_var = tk.StringVar(root_widget, value="Light")
    state.font_family_var = tk.StringVar(root_widget, value="Arial")
    state.font_sizes_vars = {
        key: tk.IntVar(root_widget, value=default)
        for key, default in [
            ("Header", 16),
            ("Title_L", 22),
            ("Title", 14),
            ("Button", 11),
            ("Label", 10),
            ("Body", 9),
            ("Caption", 8),
            ("Micro", 7),
            ("Mono", 9),
        ]
    }

    # Format lists used by converter_card
    state.converter_lossy_formats = ["mp3", "aac", "m4a", "ogg", "opus", "wma"]
    state.converter_lossless_formats = ["flac", "wav", "alac", "ape", "wv"]
    state.converter_all_formats = (
        state.converter_lossy_formats + state.converter_lossless_formats
    )
    state.converter_available_formats = list(state.converter_all_formats)

    return state


# ---------------------------------------------------------------------------
# Lazy-import helpers so module-level imports don't fail when cards import
# audio_suite_shared.styles (mocked below).
# ---------------------------------------------------------------------------


def _import_card(module_path: str):
    import importlib

    return importlib.import_module(module_path)


# ---------------------------------------------------------------------------
# audio_suite_shared.styles stub so cards can be imported without the package
# ---------------------------------------------------------------------------


def _patch_styles():
    """
    Ensure audio_suite_shared.styles is importable.

    Tries the real package first. Only installs a stub if the real
    audio_suite_shared is genuinely unavailable (e.g. an isolated CI
    sandbox without the editable install) -- never overwrites a real,
    already-importable audio_suite_shared with a MagicMock.
    """
    try:
        import audio_suite_shared.styles  # noqa: F401

        return
    except ImportError:
        pass

    if "audio_suite_shared.styles" in sys.modules:
        return

    styles = MagicMock()
    styles.BG_LIGHT = "#f0f0f0"
    styles.BG_WHITE = "#ffffff"
    styles.BG_APP = "#e8e8e8"
    styles.FG_MAIN = "#000000"
    styles.FG_SUB = "#888888"
    styles.AMBER = "#f59e0b"
    styles.FONT_BODY = ("Arial", 9)
    styles.FONT_BODY_B = ("Arial", 9, "bold")
    styles.FONT_CAPTION = ("Arial", 8)
    styles.FONT_LABEL = ("Arial", 10)
    styles.FONT_LABEL_B = ("Arial", 10, "bold")
    styles.FONT_TITLE = ("Arial", 14, "bold")
    styles.FONT_MONO = ("Courier New", 9)
    styles.FONT_BUTTON = ("Arial", 11)
    styles.COLOR_ERROR = "#dc2626"
    styles.COLOR_SUCCESS = "#16a34a"
    styles.get_main = lambda: "#7c3aed"
    styles.get_dark = lambda: "#5b21b6"
    styles.PALETTES = {
        "Purple": {
            "main": "#7c3aed",
            "dark": "#5b21b6",
            "bg_light": "#ede9fe",
            "bg_white": "#ffffff",
        },
        "Blue": {
            "main": "#2563eb",
            "dark": "#1d4ed8",
            "bg_light": "#dbeafe",
            "bg_white": "#ffffff",
        },
    }
    shared_pkg = MagicMock()
    shared_pkg.styles = styles
    shared_pkg.exceptions = MagicMock()
    shared_pkg.suite_config = MagicMock()
    sys.modules["audio_suite_shared"] = shared_pkg
    sys.modules["audio_suite_shared.styles"] = styles
    sys.modules["audio_suite_shared.exceptions"] = MagicMock()
    sys.modules["audio_suite_shared.suite_config"] = MagicMock()


_patch_styles()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_checkbuttons(widget) -> list:
    """Recursively collect all Checkbutton widgets."""
    result = []
    if isinstance(widget, tk.Checkbutton):
        result.append(widget)
    for child in widget.winfo_children():
        result.extend(_find_checkbuttons(child))
    return result


def _find_entries(widget) -> list:
    result = []
    if isinstance(widget, tk.Entry):
        result.append(widget)
    for child in widget.winfo_children():
        result.extend(_find_entries(child))
    return result


def _find_buttons_with_textvariable(widget) -> list:
    """Find buttons that use textvariable (expand toggles)."""
    result = []
    if isinstance(widget, tk.Button):
        try:
            if widget.cget("textvariable"):
                result.append(widget)
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        result.extend(_find_buttons_with_textvariable(child))
    return result


def _find_labels(widget) -> list:
    """Recursively collect all Label widgets."""
    result = []
    if isinstance(widget, tk.Label):
        result.append(widget)
    for child in widget.winfo_children():
        result.extend(_find_labels(child))
    return result


def _find_widgets_by_class(widget, cls) -> list:
    """Recursively collect widgets of a given class (e.g., tk.Scale)."""
    result = []
    if isinstance(widget, cls):
        result.append(widget)
    for child in widget.winfo_children():
        result.extend(_find_widgets_by_class(child, cls))
    return result


# ---------------------------------------------------------------------------
# album_genre_card
# ---------------------------------------------------------------------------


class TestAlbumGenreCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import album_genre_card

        return album_genre_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_album_genre_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        toggle_name = str(state.module_toggles["album_genre"])
        assert any(toggle_name in v for v in variables)

    def test_coverage_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.album_genre_coverage) in v for v in var_names)

    def test_expand_button_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        assert len(_find_buttons_with_textvariable(parent)) >= 1

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# replaygain_card
# ---------------------------------------------------------------------------


class TestReplayGainCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import replaygain_card

        return replaygain_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_replaygain_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        toggle_name = str(state.module_toggles["replaygain"])
        assert any(toggle_name in v for v in variables)

    def test_expand_button_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        assert len(_find_buttons_with_textvariable(parent)) >= 1

    def test_slider_and_readout_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        # Find Scale widgets
        scales = _find_widgets_by_class(parent, tk.Scale)
        assert len(scales) >= 1
        # Find Labels with textvariable referencing state.rg_lufs
        labels = _find_labels(parent)
        var_names = [str(label.cget("textvariable")) for label in labels]
        assert any(str(state.rg_lufs) in v for v in var_names)

    def test_slider_movement_updates_rg_lufs(self, parent, root, _import):
        """Moving the Scale slider updates state.rg_lufs via LUFS_OPTIONS."""
        state = _make_state(root)
        _import.build(parent, state)
        scales = _find_widgets_by_class(parent, tk.Scale)
        assert len(scales) >= 1
        scale = scales[0]
        # LUFS_OPTIONS = (-12.0, -14.0, -16.0, -18.0, -23.0)
        # index 4 => -23.0
        cmd = scale.cget("command")
        scale.tk.call(cmd, "4")
        assert state.rg_lufs.get() == "-23.0"


# ---------------------------------------------------------------------------
# bpm_card
# ---------------------------------------------------------------------------


class TestBpmCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import bpm_card

        return bpm_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_bpm_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["bpm"]) in v for v in variables)

    def test_range_entries_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        # Min, max, duration = 3 entries expected
        assert len(entries) >= 3

    def test_min_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.bpm_range_min) in v for v in var_names)

    def test_max_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.bpm_range_max) in v for v in var_names)

    def test_duration_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.bpm_duration) in v for v in var_names)


# ---------------------------------------------------------------------------
# art_card
# ---------------------------------------------------------------------------


class TestArtCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import art_card

        return art_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_art_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["art"]) in v for v in variables)

    def test_purge_checkbutton_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.art_purge) in v for v in variables)

    def test_resolution_combobox_wired_to_art_res(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state)
        combos = []

        def _collect(w):
            if isinstance(w, ttk.Combobox):
                combos.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        combo_var_names = [str(c.cget("textvariable")) for c in combos]
        assert any(str(state.art_res) in v for v in combo_var_names)


# ---------------------------------------------------------------------------
# genre_sync_card
# ---------------------------------------------------------------------------


class TestGenreSyncCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import genre_sync_card

        return genre_sync_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_genre_sync_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["genre_sync"]) in v for v in variables)


# ---------------------------------------------------------------------------
# key_card
# ---------------------------------------------------------------------------


class TestKeyCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import key_card

        return key_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_key_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["key"]) in v for v in variables)

    def test_duration_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.key_duration) in v for v in var_names)


# ---------------------------------------------------------------------------
# mood_analyzer_card
# ---------------------------------------------------------------------------


class TestMoodAnalyzerCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import mood_analyzer_card

        return mood_analyzer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_mood_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["mood_analyzer"]) in v for v in variables)

    def test_duration_and_workers_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        var_names = [str(e.cget("textvariable")) for e in _find_entries(parent)]
        assert any(str(state.mood_duration) in v for v in var_names)
        assert any(str(state.mood_workers) in v for v in var_names)

    def test_parallel_checkbutton_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.mood_parallel) in v for v in variables)


# ---------------------------------------------------------------------------
# tempo_card
# ---------------------------------------------------------------------------


class TestTempoCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import tempo_card

        return tempo_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_tempo_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["tempo"]) in v for v in variables)


# ---------------------------------------------------------------------------
# asx_card
# ---------------------------------------------------------------------------


class TestAsxCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import asx_card

        return asx_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_asx_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.asx_extractor_toggle) in v for v in variables)


# ---------------------------------------------------------------------------
# audio_enhancer_card
# ---------------------------------------------------------------------------


class TestAudioEnhancerCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import audio_enhancer_card

        return audio_enhancer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_enhancer_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["audio_enhancer"]) in v for v in variables)

    def test_output_dir_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.enhancer_output_dir) in v for v in var_names)

    def test_expand_button_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        assert len(_find_buttons_with_textvariable(parent)) >= 1

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# audio_normalizer_card
# ---------------------------------------------------------------------------


class TestAudioNormalizerCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import audio_normalizer_card

        return audio_normalizer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_normalizer_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["audio_normalizer"]) in v for v in variables
        )

    def test_lufs_combobox_wired_to_state(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state)
        combos = []

        def _collect(w):
            if isinstance(w, ttk.Combobox):
                combos.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        combo_var_names = [str(c.cget("textvariable")) for c in combos]
        assert any(str(state.normalizer_target_lufs) in v for v in combo_var_names)

    def test_tolerance_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.normalizer_tolerance) in v for v in var_names)

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# pop_click_remover_card
# ---------------------------------------------------------------------------


class TestPopClickRemoverCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import pop_click_remover_card

        return pop_click_remover_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_declick_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["pop_click_remover"]) in v for v in variables
        )

    def test_sensitivity_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.declick_sensitivity) in v for v in var_names)

    def test_width_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.declick_max_width) in v for v in var_names)

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# silence_trimmer_card
# ---------------------------------------------------------------------------


class TestSilenceTrimmerCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import silence_trimmer_card

        return silence_trimmer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_trimmer_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["silence_trimmer"]) in v for v in variables)

    def test_threshold_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.trimmer_threshold) in v for v in var_names)

    def test_apply_fade_checkbutton_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.trimmer_apply_fade) in v for v in variables)

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# cd_ripper_card
# ---------------------------------------------------------------------------


class TestCdRipperCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import cd_ripper_card

        return cd_ripper_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_cd_ripper_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.cd_ripper_toggle) in v for v in variables)


# ---------------------------------------------------------------------------
# tag_field_updater_card
# ---------------------------------------------------------------------------


class TestTagFieldUpdaterCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import tag_field_updater_card

        return tag_field_updater_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_tag_field_updater_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["tag_field_updater"]) in v for v in variables
        )

    def test_expand_button_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        assert len(_find_buttons_with_textvariable(parent)) >= 1

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


class TestTagEditorCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import tag_editor_card

        return tag_editor_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_tag_editor_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["tag_editor"]) in v for v in variables)

    def test_expand_button_present(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        assert len(_find_buttons_with_textvariable(parent)) >= 1

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# scrubber_card
# ---------------------------------------------------------------------------


class TestScrubberCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import scrubber_card

        return scrubber_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_scrubber_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["scrubber"]) in v for v in variables)

    def test_preserve_lyrics_checkbutton_wired(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.scrubber_preserve_lyrics) in v for v in variables)

    def test_preserve_album_artist_checkbutton_wired(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.scrubber_preserve_album_artist) in v for v in variables)

    def test_preserve_embedded_art_checkbutton_wired(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.scrubber_preserve_embedded_art) in v for v in variables)

    def test_expand_button_can_be_invoked(self, parent, root, _import):
        """The expand/collapse button invokes without error."""
        state = _make_state(root)
        _import.build(parent, state)
        expand_btns = _find_buttons_with_textvariable(parent)
        assert len(expand_btns) >= 1
        for _ in range(3):
            expand_btns[0].invoke()


# ---------------------------------------------------------------------------
# converter_card
# ---------------------------------------------------------------------------


class TestConverterCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import converter_card

        return converter_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)

    def test_build_with_on_toggle_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(
            parent, state, on_browse_output=lambda: None, on_toggle=lambda: None
        )

    def test_converter_checkbutton_wired_to_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.converter_toggle) in v for v in variables)

    def test_delete_originals_checkbutton_wired(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.converter_delete_originals) in v for v in variables)

    def test_output_dir_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.converter_output_dir) in v for v in var_names)

    def test_detected_label_attached_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        assert hasattr(state, "_converter_detected_label")

    def test_format_menu_attached_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        assert hasattr(state, "_converter_format_menu")

    def test_quality_combobox_wired_to_converter_quality(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        combos = []

        def _collect(w):
            if isinstance(w, ttk.Combobox):
                combos.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        combo_var_names = [str(c.cget("textvariable")) for c in combos]
        assert any(str(state.converter_quality) in v for v in combo_var_names)

    def test_delete_originals_and_output_dir_both_remain_independently_settable(
        self, parent, root, _import, tmp_path
    ):
        """
        Regression: this card previously disabled/cleared one field when
        the other was set, mirroring a CLI restriction (validate_args in
        cli_args.py) that has since been removed -- file_processor.py's
        delete step removes the source file independent of where the
        converted output lands, so the combination is valid. Master Driver
        must not impose a restriction the tool itself doesn't have.
        """
        state = _make_state(root)
        _import.build(parent, state, on_browse_output=lambda: None)
        state.converter_output_dir.set(str(tmp_path))
        state.converter_delete_originals.set(True)
        assert state.converter_output_dir.get() == str(tmp_path)
        assert state.converter_delete_originals.get() is True


# ---------------------------------------------------------------------------
# undo_tag_edits_card
# ---------------------------------------------------------------------------


class TestUndoTagEditsCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import undo_tag_edits_card

        return undo_tag_edits_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state, on_open=lambda: None)

    def test_open_button_triggered(self, parent, root, _import):
        """The Open Undo button must invoke the supplied callback."""
        state = _make_state(root)
        clicked = {"count": 0}

        def on_open():
            clicked["count"] += 1

        _import.build(parent, state, on_open=on_open)

        buttons = []

        def _collect(w):
            if isinstance(w, tk.Button):
                buttons.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        open_btn = next(b for b in buttons if b.cget("text") == "Open Undo")
        open_btn.invoke()
        assert clicked["count"] == 1

    def test_no_checkbutton_rendered(self, parent, root, _import):
        """Undo is opened on demand, never as part of a batch run."""
        state = _make_state(root)
        _import.build(parent, state, on_open=lambda: None)
        assert _find_checkbuttons(parent) == []

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state, on_open=lambda: None)
        _import.build(p2, state, on_open=lambda: None)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# lyrics_manager_card
# ---------------------------------------------------------------------------


class TestLyricsManagerCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import lyrics_manager_card

        return lyrics_manager_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_lyrics_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["lyrics_manager"]) in v for v in variables)

    def test_provider_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.lyrics_provider) in v for v in var_names)

    def test_timeout_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.lyrics_request_timeout) in v for v in var_names)

    def test_checkbuttons_include_lyrics_options(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.lyrics_skip_existing) in v for v in variables)
        assert any(str(state.lyrics_plain_fallback) in v for v in variables)
        assert any(str(state.lyrics_parallel) in v for v in variables)

    def test_workers_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.lyrics_workers) in v for v in var_names)

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


# ---------------------------------------------------------------------------
# theme_card
# ---------------------------------------------------------------------------


class TestThemeCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import theme_card

        return theme_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_three_radio_options_created(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        radios = []

        def _collect(w):
            if isinstance(w, tk.Radiobutton):
                radios.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(radios) == 3

    def test_radio_values_are_light_dark_system(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        radios = []

        def _collect(w):
            if isinstance(w, tk.Radiobutton):
                radios.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        values = {str(r.cget("value")) for r in radios}
        assert values == {"Light", "Dark", "System"}


# ---------------------------------------------------------------------------
# palette_card
# ---------------------------------------------------------------------------


class TestPaletteCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import palette_card

        return palette_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_radio_buttons_use_palette_var(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        radios = []

        def _collect(w):
            if isinstance(w, tk.Radiobutton):
                radios.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(radios) >= 1
        palette_var_name = str(state.palette_var)
        for rb in radios:
            assert palette_var_name in str(rb.cget("variable"))

    def test_radio_count_matches_palettes(self, parent, root, _import):
        from audio_suite_shared.styles import PALETTES

        state = _make_state(root)
        _import.build(parent, state)
        radios = []

        def _collect(w):
            if isinstance(w, tk.Radiobutton):
                radios.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(radios) == len(PALETTES)

    def test_windows_accent_row_builds_when_winaccent_is_missing(
        self, parent, root, _import, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The.function-level winaccent fallback runs instead of being excluded.

        Plan D2 retired the broad ``except ImportError`` coverage exclusion:
        this card's per-palette import guard is exercisable, so the test
        executes it via a missing module and asserts the real degradation —
        the panel still builds all palette rows with the placeholder colours.
        """
        from audio_suite_shared.styles import PALETTES

        monkeypatch.setitem(sys.modules, "winaccent", None)
        state = _make_state(root)
        state.palette_var.set("Windows Accent")
        _import.build(parent, state)
        radios = []

        def _collect(w):
            if isinstance(w, tk.Radiobutton):
                radios.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(radios) == len(PALETTES)


# ---------------------------------------------------------------------------
# typography_card
# ---------------------------------------------------------------------------


class TestTypographyCard:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import typography_card

        return typography_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_nine_spinboxes_created(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state)
        spinboxes = []

        def _collect(w):
            if isinstance(w, ttk.Spinbox):
                spinboxes.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(spinboxes) == 9

    def test_font_combo_wired_to_font_family_var(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state)
        combos = []

        def _collect(w):
            if isinstance(w, ttk.Combobox):
                combos.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        assert len(combos) >= 1
        combo_var_names = [str(c.cget("textvariable")) for c in combos]
        assert any(str(state.font_family_var) in v for v in combo_var_names)


# ---------------------------------------------------------------------------
# Consolidated shell (iteration-7 B2): the simple-card family must execute
# its build() and wire the correct toggle/state vars — the audit A4's
# "file-exists check" failure mode is a test failure after this item.
# ---------------------------------------------------------------------------


class TestNoiseReductionCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import noise_reduction_card

        return noise_reduction_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def checkbutton_refuses_toggle_key_or_attr_name(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["noise_reduction"]) in v for v in variables)

    def test_build_idempotent(self, root, _import):
        state = _make_state(root)
        p1 = tk.Frame(root)
        p2 = tk.Frame(root)
        _import.build(p1, state)
        _import.build(p2, state)
        p1.destroy()
        p2.destroy()


class TestLibraryStatsCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import library_stats_card

        return library_stats_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_library_stats_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.library_stats_toggle) in v for v in variables)


class TestFingerprinterCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import fingerprinter_card

        return fingerprinter_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_fingerprinter_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.module_toggles["fingerprinter"]) in v for v in variables)

    def test_lookup_and_threshold_wired(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(str(state.fingerprinter_lookup) in v for v in variables)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.fingerprinter_threshold) in v for v in var_names)


class TestFileReorganizerCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import file_reorganizer_card

        return file_reorganizer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_file_reorganizer_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["file_reorganizer"]) in v for v in variables
        )

    def test_output_dir_entry_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.file_reorg_output_dir) in v for v in var_names)


class TestMoodAnalysisBatchCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import mood_analysis_batch_card

        return mood_analysis_batch_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_mood_batch_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["mood_analysis_batch"]) in v for v in variables
        )

    def test_duration_and_workers_wired_to_state(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        entries = _find_entries(parent)
        var_names = [str(e.cget("textvariable")) for e in entries]
        assert any(str(state.mood_analysis_batch_duration) in v for v in var_names)
        assert any(str(state.mood_analysis_batch_workers) in v for v in var_names)


class TestAlbumArtNormalizerCardExecuted:
    @staticmethod
    @pytest.fixture()
    def _import():
        from master_driver.ui.cards import album_art_normalizer_card

        return album_art_normalizer_card

    def test_build_does_not_raise(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)

    def test_checkbutton_uses_album_art_normalizer_toggle(self, parent, root, _import):
        state = _make_state(root)
        _import.build(parent, state)
        btns = _find_checkbuttons(parent)
        variables = [str(b.cget("variable")) for b in btns]
        assert any(
            str(state.module_toggles["album_art_normalizer"]) in v for v in variables
        )

    def test_size_combobox_wired_to_state(self, parent, root, _import):
        from tkinter import ttk

        state = _make_state(root)
        _import.build(parent, state)
        combos = []

        def _collect(w):
            if isinstance(w, ttk.Combobox):
                combos.append(w)
            for child in w.winfo_children():
                _collect(child)

        _collect(parent)
        combo_var_names = [str(c.cget("textvariable")) for c in combos]
        assert any(str(state.art_normalizer_size) in v for v in combo_var_names)
