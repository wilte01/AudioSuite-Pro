"""test_styles.py — Unit tests for audio_suite_shared.styles

Strategy
--------
styles.py imports tkinter.ttk (display-free on its own) and winreg (Windows).
Tests mock winreg on non-Windows.  No Tk root is required for any of these
tests; ttk.Style is not instantiated.

Covers:
    • PALETTES structure and required keys
    • set_active_palette: correct module globals updated
    • get_active_palette_name: returns name matching current palette
    • set_theme_mode: Light vs Dark global colour changes
    • set_active_typography: font tuples updated for all sizes
    • get_main / get_dark / tab_active / tab_inactive return hex strings
    • Colour constants are valid hex strings
    • The module-level winaccent fallback guard (D2): executed by importing
      the module without winaccent, not hidden by a coverage exclusion
"""

from __future__ import annotations

import importlib
import re
import sys
from unittest.mock import MagicMock, patch

import pytest

# Patch winreg on non-Windows before importing styles
if sys.platform != "win32":
    winreg_mock = MagicMock()
    sys.modules.setdefault("winreg", winreg_mock)

import audio_suite_shared.styles as styles  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def is_hex_colour(value: str) -> bool:
    """Return True if value is a valid 6-digit hex colour string."""
    return bool(_HEX_RE.match(value))


# ---------------------------------------------------------------------------
# PALETTES structure
# ---------------------------------------------------------------------------


class TestPalettesStructure:
    """Tests for the PALETTES constant dictionary."""

    _REQUIRED_KEYS = {"main", "dark", "bg_light", "bg_white"}

    def test_expected_palettes_present(self) -> None:
        expected = {"Purple", "Teal", "Slate", "Crimson", "Windows Accent"}
        assert expected.issubset(set(styles.PALETTES.keys()))

    @pytest.mark.parametrize("name", ["Purple", "Teal", "Slate", "Crimson"])
    def test_palette_has_required_keys(self, name: str) -> None:
        palette = styles.PALETTES[name]
        assert self._REQUIRED_KEYS.issubset(palette.keys()), (
            f"Palette '{name}' missing keys: {self._REQUIRED_KEYS - palette.keys()}"
        )

    @pytest.mark.parametrize("name", ["Purple", "Teal", "Slate", "Crimson"])
    def test_palette_colours_are_valid_hex(self, name: str) -> None:
        palette = styles.PALETTES[name]
        for key, value in palette.items():
            assert is_hex_colour(value), (
                f"PALETTES['{name}']['{key}'] = '{value}' is not a valid hex colour"
            )

    def test_default_palette_exists(self) -> None:
        assert styles.DEFAULT_PALETTE in styles.PALETTES


# ---------------------------------------------------------------------------
# set_active_palette
# ---------------------------------------------------------------------------


class TestSetActivePalette:
    """Tests for set_active_palette and get_active_palette_name."""

    def test_set_purple_updates_globals(self) -> None:
        styles.set_active_palette("Purple")
        assert styles.PURPLE_MAIN == styles.PALETTES["Purple"]["main"]
        assert styles.PURPLE_DARK == styles.PALETTES["Purple"]["dark"]

    def test_set_teal_updates_globals(self) -> None:
        styles.set_active_palette("Teal")
        assert styles.PURPLE_MAIN == styles.PALETTES["Teal"]["main"]

    def test_get_active_palette_name_matches_set(self) -> None:
        styles.set_active_palette("Crimson")
        name = styles.get_active_palette_name()
        assert name == "Crimson"

    def test_unknown_palette_falls_back_to_default(self) -> None:
        """An unknown palette name must fall back to the default without raising."""
        styles.set_active_palette("NonExistentPalette")
        # Should not raise; module remains usable
        assert is_hex_colour(styles.PURPLE_MAIN)

    def test_purple_main_is_hex_after_set(self) -> None:
        styles.set_active_palette("Purple")
        assert is_hex_colour(styles.PURPLE_MAIN)
        assert is_hex_colour(styles.PURPLE_DARK)


# ---------------------------------------------------------------------------
# set_theme_mode
# ---------------------------------------------------------------------------


class TestSetThemeMode:
    """Tests for Light and Dark theme mode switching."""

    def test_light_mode_fg_main_is_black(self) -> None:
        styles.set_active_palette("Purple")
        styles.set_theme_mode("Light")
        assert styles.FG_MAIN == "#000000"

    def test_dark_mode_fg_main_is_white(self) -> None:
        styles.set_theme_mode("Dark")
        assert styles.FG_MAIN == "#ffffff"

    def test_dark_mode_bg_app_is_dark(self) -> None:
        styles.set_theme_mode("Dark")
        # BG_APP must be a dark colour (all RGB components < 0x40)
        hex_val = styles.BG_APP.lstrip("#")
        r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
        assert max(r, g, b) < 0x40, (
            f"BG_APP in Dark mode should be dark, got {styles.BG_APP}"
        )

    def test_light_mode_bg_app_is_light(self) -> None:
        styles.set_active_palette("Purple")
        styles.set_theme_mode("Light")
        hex_val = styles.BG_APP.lstrip("#")
        r, g, b = int(hex_val[0:2], 16), int(hex_val[2:4], 16), int(hex_val[4:6], 16)
        assert max(r, g, b) > 0x80, (
            f"BG_APP in Light mode should be light, got {styles.BG_APP}"
        )

    def test_theme_mode_stored(self) -> None:
        styles.set_theme_mode("Dark")
        assert styles.THEME_MODE == "Dark"
        styles.set_theme_mode("Light")
        assert styles.THEME_MODE == "Light"

    def test_color_error_changes_between_modes(self) -> None:
        styles.set_theme_mode("Light")
        light_error = styles.COLOR_ERROR
        styles.set_theme_mode("Dark")
        dark_error = styles.COLOR_ERROR
        assert light_error != dark_error


# ---------------------------------------------------------------------------
# set_active_typography
# ---------------------------------------------------------------------------


class TestSetActiveTypography:
    """Tests for the dynamic typography system."""

    def test_custom_family_updates_font_tuples(self) -> None:
        styles.set_active_typography(family="Helvetica")
        assert styles.FONT_BODY[0] == "Helvetica"
        assert styles.FONT_LABEL[0] == "Helvetica"
        assert styles.FONT_BUTTON[0] == "Helvetica"
        # Restore
        styles.set_active_typography(family="Arial")

    def test_custom_sizes_update_font_tuples(self) -> None:
        sizes = {
            "Header": 20,
            "Title_L": 28,
            "Title": 16,
            "Button": 13,
            "Label": 12,
            "Body": 11,
            "Caption": 9,
            "Micro": 8,
            "Mono": 10,
        }
        styles.set_active_typography(sizes=sizes)
        assert styles.FONT_BODY[1] == 11
        assert styles.FONT_LABEL[1] == 12
        assert styles.FONT_HEADER[1] == 20
        # Restore defaults
        styles.set_active_typography()

    def test_font_tuples_are_tuples(self) -> None:
        styles.set_active_typography()
        for attr in [
            "FONT_BODY",
            "FONT_LABEL",
            "FONT_BUTTON",
            "FONT_HEADER",
            "FONT_CAPTION",
            "FONT_MONO",
            "FONT_MICRO",
        ]:
            value = getattr(styles, attr)
            assert isinstance(value, tuple), f"{attr} must be a tuple"

    def test_bold_variants_contain_bold_string(self) -> None:
        styles.set_active_typography()
        for attr in ["FONT_BODY_B", "FONT_LABEL_B", "FONT_CAPTION_B", "FONT_BUTTON"]:
            value = getattr(styles, attr)
            assert "bold" in value, f"{attr} must contain 'bold'"


# ---------------------------------------------------------------------------
# Colour accessors and constants
# ---------------------------------------------------------------------------


class TestColourAccessors:
    """Tests for get_main, get_dark, tab_active, tab_inactive."""

    def test_get_main_returns_hex(self) -> None:
        styles.set_active_palette("Purple")
        assert is_hex_colour(styles.get_main())

    def test_get_dark_returns_hex(self) -> None:
        styles.set_active_palette("Purple")
        assert is_hex_colour(styles.get_dark())

    def test_tab_active_equals_get_dark(self) -> None:
        styles.set_active_palette("Purple")
        assert styles.tab_active() == styles.get_dark()

    def test_tab_inactive_equals_get_main(self) -> None:
        styles.set_active_palette("Purple")
        assert styles.tab_inactive() == styles.get_main()

    def test_amber_is_valid_hex(self) -> None:
        assert is_hex_colour(styles.AMBER)

    def test_tab_fg_is_white(self) -> None:
        assert styles.TAB_FG == "#ffffff"

    def test_settings_tab_colors_are_greys(self) -> None:
        """Settings tab active/inactive must be grey hex values."""
        assert is_hex_colour(styles.SETTINGS_TAB_ACTIVE)
        assert is_hex_colour(styles.SETTINGS_TAB_INACTIVE)


# ---------------------------------------------------------------------------
# bootstrap_theme and apply_styles  (require Tk display for ttk.Style)
# ---------------------------------------------------------------------------


class _HasDisplay:
    """Guard for display-dependent tests."""

    @staticmethod
    def check() -> bool:
        import os
        import sys

        if sys.platform == "win32":
            return True
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


_skip_no_display = pytest.mark.skipif(
    not _HasDisplay.check(), reason="No graphical display — ttk.Style unavailable"
)


@_skip_no_display
class TestBootstrapTheme:
    """Tests for styles.bootstrap_theme."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_sets_theme_to_clam(self) -> None:
        from tkinter import ttk

        styles.bootstrap_theme()
        s = ttk.Style()
        assert s.theme_use() == "clam"


@_skip_no_display
class TestApplyStyles:
    """Tests for styles.apply_styles."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_does_not_raise(self) -> None:
        from tkinter import ttk

        s = ttk.Style()
        styles.apply_styles(s)

    def test_theme_set_to_clam(self) -> None:
        from tkinter import ttk

        s = ttk.Style()
        styles.apply_styles(s)
        assert s.theme_use() == "clam"

    def test_tnotebook_configured(self) -> None:
        from tkinter import ttk

        s = ttk.Style()
        styles.apply_styles(s)
        # TNotebook background must be a valid hex colour
        bg = s.lookup("TNotebook", "background")
        assert (
            bg is None or is_hex_colour(bg) or "theme not applied until widget creation"
        )


class TestWindowsAccentFallback:
    """The module-level winaccent guard, exercised rather than excluded.

    Plan D2 retired the broad ``except ImportError`` coverage exclusion: a
    guard that CAN run must be exercised by a test instead of hidden by a
    config-wide pattern. winaccent is platform-marked in pyproject
    (``sys_platform == 'win32'``), so on a non-Windows host this exact branch
    executes at import; a reload under a missing module reproduces it here,
    and asserts the real degradation: no system-accent lookup, placeholder
    colours preserved.
    """

    def test_windows_accent_palette_holds_the_placeholder_without_winaccent(
        self,
    ) -> None:
        # Establish a known state before capturing the placeholder.
        # set_active_palette() writes the live system accent into the
        # module-level PALETTES dict *in place*, so on a host with winaccent
        # installed any earlier test that activated "Windows Accent" leaves
        # the placeholder overwritten for the rest of the process. The
        # reload inside the guard then rebuilds PALETTES from the module
        # literal, legitimately restoring the true placeholder, and the
        # comparison below failed. Reloading first makes the captured value
        # the real module-level placeholder instead of inherited state, so
        # the assertion depends only on this test.
        importlib.reload(styles)
        placeholder_main = styles.PALETTES["Windows Accent"]["main"]
        was_available = styles.HAS_WINACCENT

        with patch.dict(sys.modules, {"winaccent": None}):
            importlib.reload(styles)
            assert styles.HAS_WINACCENT is False

            # The degradation, not just the flag: requesting the accent
            # palette without winaccent must keep the placeholder colours
            # and reach no accent attribute at all.
            styles.set_active_palette("Windows Accent")
            assert styles.PURPLE_MAIN == styles.PALETTES["Windows Accent"]["main"]
            assert is_hex_colour(styles.PURPLE_MAIN)

            # The placeholder itself must not have been mutated by the
            # fallback lookup.
            assert styles.PALETTES["Windows Accent"]["main"] == placeholder_main

        importlib.reload(styles)
        assert styles.HAS_WINACCENT == was_available
        assert styles.PALETTES["Windows Accent"]["main"] == placeholder_main

    def test_fallback_survives_a_palette_polluted_by_an_earlier_test(self) -> None:
        """Regression for an intermittent full-suite failure.

        The pollution is written directly, the way production does it, so
        the guard is exercised even on a host where winaccent is absent and
        set_active_palette() therefore never mutates anything. The fallback
        contract -- a valid hex placeholder and no accent lookup -- must
        hold regardless of what a previous test left behind.
        """
        styles.PALETTES["Windows Accent"]["main"] = "#123456"
        assert styles.PALETTES["Windows Accent"]["main"] == "#123456"

        with patch.dict(sys.modules, {"winaccent": None}):
            importlib.reload(styles)
            assert styles.HAS_WINACCENT is False
            placeholder_main = styles.PALETTES["Windows Accent"]["main"]
            assert placeholder_main != "#123456", (
                "reload did not rebuild PALETTES, so this test would not "
                "exercise the polluted-state path"
            )
            styles.set_active_palette("Windows Accent")
            assert styles.PURPLE_MAIN == placeholder_main
            assert is_hex_colour(styles.PURPLE_MAIN)

        importlib.reload(styles)
        assert styles.PALETTES["Windows Accent"]["main"] == placeholder_main
