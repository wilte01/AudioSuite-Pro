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


class _RaisingWinAccent:
    """Stand-in for winaccent whose colour lookups raise, as a real one does
    when the registry is unavailable.

    A MagicMock with ``accent_normal = OSError(...)`` does not work: the code
    *reads the attribute*, so storing an exception instance silently yields
    the exception object instead of raising, and the failure path under test
    would never run.
    """

    @property
    def accent_normal(self) -> str:
        raise OSError("registry unavailable")

    @property
    def accent_dark(self) -> str:
        raise OSError("registry unavailable")

    @property
    def accent_light(self) -> str:
        raise OSError("registry unavailable")


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
class TestWindowsAccentIsNotWrittenBackIntoPalettes:
    """Iteration-6 B4: the live accent lives beside PALETTES, not inside it.

    The old code did ``PALETTES["Windows Accent"].update(...)``, so probing
    the registry rewrote the module table. Two consequences made that a real
    defect rather than a style preference: a failed probe on a later run fell
    back to the *previous session's* accent instead of the placeholder, and
    the picker's Windows Accent swatch showed whatever accent was last read
    rather than the one in force.
    """

    @pytest.fixture(autouse=True)
    @staticmethod
    def _restore_palette_state():
        """Snapshot and restore the module state these tests mutate.

        Snapshot/restore, never importlib.reload: reload rebuilds PALETTES
        but does NOT undo an in-place dict mutation a test made, which is
        exactly the cross-test pollution B4 removes.
        """
        saved_live = dict(styles._WINACCENT_LIVE)
        saved_active = dict(styles._active)
        saved_wa = dict(styles.PALETTES["Windows Accent"])
        saved_main = styles.PURPLE_MAIN
        saved_dark = styles.PURPLE_DARK
        yield
        styles._WINACCENT_LIVE.clear()
        styles._WINACCENT_LIVE.update(saved_live)
        styles._active.clear()
        styles._active.update(saved_active)
        styles.PALETTES["Windows Accent"].clear()
        styles.PALETTES["Windows Accent"].update(saved_wa)
        styles.PURPLE_MAIN = saved_main
        styles.PURPLE_DARK = saved_dark

    def test_probing_does_not_mutate_the_palettes_table(self) -> None:
        """The core B4 property: the registry read leaves PALETTES untouched."""
        fake = MagicMock()
        fake.accent_normal = "#aabbcc"
        fake.accent_dark = "#112233"
        fake.accent_light = "#ddeeff"

        before = dict(styles.PALETTES["Windows Accent"])
        with (
            patch.object(styles, "HAS_WINACCENT", True),
            patch.object(styles, "winaccent", fake, create=True),
        ):
            styles.set_active_palette("Windows Accent")

        assert styles.PALETTES["Windows Accent"] == before
        # ...while the accent really is applied.
        assert styles.PURPLE_MAIN == "#aabbcc"
        assert styles.PURPLE_DARK == "#112233"

    def test_resolver_serves_the_live_accent_so_the_swatch_is_current(self) -> None:
        """The picker reads the resolver, so it must return the live values."""
        fake = MagicMock()
        fake.accent_normal = "#010203"
        fake.accent_dark = "#040506"
        fake.accent_light = "#070809"

        with (
            patch.object(styles, "HAS_WINACCENT", True),
            patch.object(styles, "winaccent", fake, create=True),
        ):
            styles.set_active_palette("Windows Accent")

        assert styles._resolve_palette("Windows Accent") == {
            "main": "#010203",
            "dark": "#040506",
            "bg_light": "#070809",
            "bg_white": "#ffffff",
        }

    def test_resolver_returns_a_copy_so_a_caller_cannot_corrupt_the_store(self):
        """Both branches must hand back a fresh dict.

        Returning the table entry by reference would let a caller that
        mutates what it is given (a swatch builder, a caller poking a shade)
        write straight into PALETTES -- the same class of bug as the in-place
        update B4 removed, one level down.
        """
        live = styles._resolve_palette("Windows Accent")
        live["main"] = "#000000"
        assert styles._resolve_palette("Windows Accent")["main"] != "#000000"

        purple = styles._resolve_palette("Purple")
        purple["main"] = "#000000"
        assert styles.PALETTES["Purple"]["main"] != "#000000"

    def test_resolver_returns_table_entries_for_ordinary_palettes(self) -> None:
        for name in styles.PALETTES:
            if name == "Windows Accent":
                continue
            assert styles._resolve_palette(name) == styles.PALETTES[name]

    def test_unknown_name_falls_back_to_the_default_palette(self) -> None:
        assert (
            styles._resolve_palette("Nonexistent")
            == styles.PALETTES[styles.DEFAULT_PALETTE]
        )

    def test_a_failed_probe_does_not_leak_the_previous_accent(self) -> None:
        """A stale live value must not survive into the fallback path.

        This is the leak the in-place mutation caused: after a good probe, a
        later failed probe fell back to ``_WINACCENT_LIVE`` and applied the
        previous session's accent.
        """
        fake = MagicMock()
        fake.accent_normal = "#aabbcc"
        fake.accent_dark = "#112233"
        fake.accent_light = "#ddeeff"
        with (
            patch.object(styles, "HAS_WINACCENT", True),
            patch.object(styles, "winaccent", fake, create=True),
        ):
            styles.set_active_palette("Windows Accent")
        assert styles._WINACCENT_LIVE

        boom = _RaisingWinAccent()
        with (
            patch.object(styles, "HAS_WINACCENT", True),
            patch.object(styles, "winaccent", boom),
            patch.object(styles.suite_config, "load_palette", return_value="Teal"),
        ):
            styles.set_active_palette("Windows Accent")

        # The stale accent is gone, and the saved preference is applied.
        assert styles._WINACCENT_LIVE == {}
        assert styles.PURPLE_MAIN == styles.PALETTES["Teal"]["main"]

    def test_get_active_palette_name_still_reports_windows_accent(self) -> None:
        """Selecting the accent must still be reported back as selected."""
        fake = MagicMock()
        fake.accent_normal = "#aabbcc"
        fake.accent_dark = "#112233"
        fake.accent_light = "#ddeeff"
        with (
            patch.object(styles, "HAS_WINACCENT", True),
            patch.object(styles, "winaccent", fake, create=True),
        ):
            styles.set_active_palette("Windows Accent")

            assert styles.get_active_palette_name() == "Windows Accent"

    def test_placeholder_is_restored_for_readers_when_no_probe_has_run(self) -> None:
        """Before any probe, the WA entry is the static placeholder."""
        styles._WINACCENT_LIVE.clear()
        assert (
            styles._resolve_palette("Windows Accent")
            == styles.PALETTES["Windows Accent"]
        )


class TestBootstrapTheme:
    """Tests for styles.bootstrap_theme."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_tk(tk_root):
        return tk_root

    def test_sets_theme_to_clam(self) -> None:
        from tkinter import ttk

        styles.bootstrap_theme()
        s = ttk.Style()
        assert s.theme_use() == "clam"


@_skip_no_display
class TestApplyStyles:
    """Tests for styles.apply_styles."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def setup_tk(tk_root):
        return tk_root

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
        # Establish a known state before capturing the placeholder. B4 removed
        # set_active_palette()'s in-place write into PALETTES, so production
        # no longer pollutes the table; a test still can (see the next test),
        # and reload is how this one gets a genuinely module-level value
        # rather than whatever the previous test left behind. Reloading first
        # makes the comparison depend only on this test.
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

        The pollution is written directly. B4 removed the production writer
        (``set_active_palette`` no longer updates PALETTES in place), but a
        direct write is still possible, and the guard must not depend on that
        being true forever. The fallback contract -- a valid hex placeholder
        and no accent lookup -- must hold regardless of what a previous test
        left behind.
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
