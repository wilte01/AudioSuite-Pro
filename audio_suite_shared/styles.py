"""
styles.py — Canonical colour palettes and ttk style setup for the Audio Suite.
"""

import logging
import sys
import tkinter as tk
from tkinter import ttk

_log = logging.getLogger(f"audio_suite.{__name__}")

try:
    import winaccent

    HAS_WINACCENT = True
except ImportError:
    HAS_WINACCENT = False

# ── Available palettes ────────────────────────────────────────────────────────
PALETTES = {
    "Purple": {
        "main": "#7b4db8",
        "dark": "#5e3a8c",
        "bg_light": "#f0f0f0",
        "bg_white": "#ffffff",
    },
    "Teal": {
        "main": "#0d7377",
        "dark": "#095355",
        "bg_light": "#f0f4f4",
        "bg_white": "#ffffff",
    },
    "Slate": {
        "main": "#4a5568",
        "dark": "#2d3748",
        "bg_light": "#f1f2f4",
        "bg_white": "#ffffff",
    },
    "Crimson": {
        "main": "#9b1c1c",
        "dark": "#771414",
        "bg_light": "#f7f0f0",
        "bg_white": "#ffffff",
    },
    "Windows Accent": {
        "main": "#7b4db8",  # Initial fallback (Purple)
        "dark": "#5e3a8c",
        "bg_light": "#f0f0f0",
        "bg_white": "#ffffff",
    },
}

DEFAULT_PALETTE = "Purple"

# ── Typography ──────────────────────────────────────────────────────────────
# Centralizing font families and semantic styles
FONT_FAMILY_MAIN = "Arial"
FONT_FAMILY_MONO = "Courier"
BASE_FONT_SIZE = 9

FONT_TITLE = (FONT_FAMILY_MAIN, 14, "bold")
FONT_LABEL = (FONT_FAMILY_MAIN, 10)
FONT_LABEL_B = (FONT_FAMILY_MAIN, 10, "bold")
FONT_BUTTON = (FONT_FAMILY_MAIN, 11, "bold")
FONT_HEADER = (FONT_FAMILY_MAIN, 16, "bold")
FONT_TITLE_L = (FONT_FAMILY_MAIN, 22, "bold")
FONT_BODY = (FONT_FAMILY_MAIN, 9)
FONT_BODY_B = (FONT_FAMILY_MAIN, 9, "bold")
FONT_BODY_I = (FONT_FAMILY_MAIN, 9, "italic")
FONT_CAPTION = (FONT_FAMILY_MAIN, 8)
FONT_CAPTION_B = (FONT_FAMILY_MAIN, 8, "bold")
FONT_CAPTION_I = (FONT_FAMILY_MAIN, 8, "italic")
FONT_MICRO = (FONT_FAMILY_MAIN, 7)
FONT_MONO = (FONT_FAMILY_MONO, 9)


# ── Dynamic Typography state ────────────────────────────────────────────────
def set_active_typography(
    family: str | None = None, sizes: dict[str, int] | None = None
) -> None:
    global FONT_FAMILY_MAIN
    global FONT_TITLE, FONT_LABEL, FONT_LABEL_B, FONT_BUTTON, FONT_HEADER, FONT_TITLE_L
    global \
        FONT_BODY, \
        FONT_BODY_B, \
        FONT_BODY_I, \
        FONT_CAPTION, \
        FONT_CAPTION_B, \
        FONT_CAPTION_I
    global FONT_MICRO, FONT_MONO

    if family:
        FONT_FAMILY_MAIN = family

    if not sizes:
        sizes = {
            "Header": 16,
            "Title_L": 22,
            "Title": 14,
            "Button": 11,
            "Label": 10,
            "Body": 9,
            "Caption": 8,
            "Micro": 7,
            "Mono": 9,
        }

    s_micro = sizes.get("Micro", 7)
    s_caption = sizes.get("Caption", 8)
    s_body = sizes.get("Body", 9)
    s_label = sizes.get("Label", 10)
    s_button = sizes.get("Button", 11)
    s_title = sizes.get("Title", 14)
    s_header = sizes.get("Header", 16)
    s_title_l = sizes.get("Title_L", 22)
    s_mono = sizes.get("Mono", 9)

    FONT_MICRO = (FONT_FAMILY_MAIN, s_micro)

    FONT_CAPTION = (FONT_FAMILY_MAIN, s_caption)
    FONT_CAPTION_B = (FONT_FAMILY_MAIN, s_caption, "bold")
    FONT_CAPTION_I = (FONT_FAMILY_MAIN, s_caption, "italic")

    FONT_BODY = (FONT_FAMILY_MAIN, s_body)
    FONT_BODY_B = (FONT_FAMILY_MAIN, s_body, "bold")
    FONT_BODY_I = (FONT_FAMILY_MAIN, s_body, "italic")
    FONT_MONO = (FONT_FAMILY_MONO, s_mono)

    FONT_LABEL = (FONT_FAMILY_MAIN, s_label)
    FONT_LABEL_B = (FONT_FAMILY_MAIN, s_label, "bold")

    FONT_BUTTON = (FONT_FAMILY_MAIN, s_button, "bold")

    FONT_TITLE = (FONT_FAMILY_MAIN, s_title, "bold")
    FONT_HEADER = (FONT_FAMILY_MAIN, s_header, "bold")
    FONT_TITLE_L = (FONT_FAMILY_MAIN, s_title_l, "bold")


# ── Active palette state ──────────────────────────────────────────────────────
_active = PALETTES[DEFAULT_PALETTE].copy()

# Live Windows Accent colours, read from the registry by set_active_palette().
# Kept out of PALETTES on purpose -- see _resolve_palette().
_WINACCENT_LIVE: dict[str, str] = {}

PURPLE_MAIN = _active["main"]
PURPLE_DARK = _active["dark"]
BG_LIGHT = _active["bg_light"]
BG_WHITE = _active["bg_white"]

# Theme Mode state
THEME_MODE = "Light"  # "Light", "Dark", "System"
FG_MAIN = "#000000"
FG_SUB = "#555555"
BG_APP = "#f4f4f9"
BG_HEADER = "#e8e8f0"
BG_ITEM = "#ffffff"
COLOR_ERROR = "#cc0000"
COLOR_SUCCESS = "#28a745"


def _get_system_theme() -> str:
    """Detect the OS Light/Dark preference.

    On Windows this reads the registry.  On macOS/Linux the preference cannot
    be detected reliably without additional dependencies, so 'Light' is
    returned as a safe default.
    """
    if sys.platform != "win32":
        return "Light"
    try:
        import winreg  # Available only on Windows

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        )
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return "Light" if value == 1 else "Dark"
    except (OSError, tk.TclError) as _exc:
        _log.debug("Could not detect theme mode: %s", _exc)
        return "Light"


def set_theme_mode(mode: str) -> None:
    """Updates the global theme mode and adapts BG/FG colors."""
    global THEME_MODE, BG_LIGHT, BG_WHITE, FG_MAIN, FG_SUB
    global BG_APP, BG_HEADER, BG_ITEM, COLOR_ERROR, COLOR_SUCCESS
    THEME_MODE = mode

    effective_mode = mode
    if mode == "System":
        effective_mode = _get_system_theme()

    if effective_mode == "Dark":
        BG_LIGHT = "#121212"
        BG_WHITE = "#1e1e1e"
        FG_MAIN = "#ffffff"
        FG_SUB = "#aaaaaa"
        BG_APP = "#1a1a1e"
        BG_HEADER = "#2d2d33"
        BG_ITEM = "#25252b"
        COLOR_ERROR = "#ff6b6b"
        COLOR_SUCCESS = "#51cf66"
    else:
        # Revert to palette values or Light defaults
        palette = _resolve_palette(get_active_palette_name())
        BG_LIGHT = palette["bg_light"]
        BG_WHITE = palette["bg_white"]
        FG_MAIN = "#000000"
        FG_SUB = "#555555"
        BG_APP = "#f4f4f9"
        BG_HEADER = "#e8e8f0"
        BG_ITEM = "#ffffff"
        COLOR_ERROR = "#cc0000"
        COLOR_SUCCESS = "#28a745"


from . import suite_config  # noqa: E402

# pylint: enable=wrong-import-position


def set_active_palette(name: str) -> None:
    global _active, PURPLE_MAIN, PURPLE_DARK, BG_LIGHT, BG_WHITE

    # If using Windows Accent, try to get actual system colors.
    # The live colours go into _WINACCENT_LIVE, never into PALETTES: the
    # registry is re-read on every selection, so writing them back into the
    # table would let one session's accent leak into the next one's fallback
    # and into the picker swatches (iteration-6 B4).
    resolved = name
    if name == "Windows Accent" and HAS_WINACCENT:
        try:
            _WINACCENT_LIVE.clear()
            _WINACCENT_LIVE.update(
                {
                    "main": winaccent.accent_normal,
                    "dark": winaccent.accent_dark,
                    "bg_light": winaccent.accent_light,
                    "bg_white": "#ffffff",
                }
            )
        except (OSError, tk.TclError) as _exc:
            _log.debug(
                "winaccent palette detection failed, using saved preference: %s", _exc
            )
            _WINACCENT_LIVE.clear()
            resolved = suite_config.load_palette()
            if resolved == "Windows Accent":
                resolved = DEFAULT_PALETTE

    _active = _resolve_palette(resolved).copy()
    PURPLE_MAIN = _active["main"]
    PURPLE_DARK = _active["dark"]

    # Refresh theme mode to ensure BG colors match the palette vs theme
    set_theme_mode(THEME_MODE)


def _resolve_palette(name: str) -> dict[str, str]:
    """Return the colours *name* resolves to right now.

    Every reader goes through here so the Windows Accent swatch and the
    applied theme can never disagree: the live accent values live in
    :data:`_WINACCENT_LIVE` (empty until a selection has probed the
    registry) and are never written back into :data:`PALETTES`.

    Args:
        name: A :data:`PALETTES` key.

    Returns:
        The live accent mapping when *name* is ``"Windows Accent"`` and the
        registry has been read; otherwise the table entry, falling back to
        :data:`DEFAULT_PALETTE` for an unknown name.  Always a fresh dict, so
        a caller cannot reach back into :data:`_WINACCENT_LIVE` or
        :data:`PALETTES` and mutate shared state by accident.
    """
    if name == "Windows Accent" and _WINACCENT_LIVE:
        return dict(_WINACCENT_LIVE)
    return dict(PALETTES.get(name, PALETTES[DEFAULT_PALETTE]))


def get_active_palette_name() -> str:
    # Check if it's the current Windows Accent colors
    if HAS_WINACCENT:
        try:
            wa = _resolve_palette("Windows Accent")
            # If the current main color matches the WA placeholder, then it's WA
            if _active.get("main") == wa.get("main") and wa.get("main") is not None:
                return "Windows Accent"
        except (OSError, tk.TclError) as _exc:
            _log.warning("Swallowed exception: %s", _exc, exc_info=True)

    for name, values in PALETTES.items():
        if name == "Windows Accent":
            continue
        if values["main"] == _active["main"]:
            return name
    return DEFAULT_PALETTE


def bootstrap_theme() -> None:
    """
    Call this IMMEDIATELY after tk.Tk() is created, before any other imports
    or widget construction.  On Windows, simply importing ttk causes the
    native 'vista' theme to register itself.  Once any ttk widget is created
    under 'vista', colour overrides are silently ignored.

    Calling this function forces 'clam' to be the active theme before Windows
    has a chance to lock in 'vista', so all subsequent style configuration
    (apply_styles, etc.) takes effect correctly.
    """
    s = ttk.Style()
    s.theme_use("clam")


def apply_styles(style: ttk.Style) -> None:
    style.theme_use("clam")
    style.configure("TNotebook", background=BG_LIGHT)
    style.configure(
        "TNotebook.Tab", background=PURPLE_MAIN, foreground="white", padding=[15, 5]
    )
    style.map("TNotebook.Tab", background=[("selected", PURPLE_DARK)])
    style.configure(
        "Suite.Horizontal.TProgressbar", troughcolor=BG_LIGHT, background=PURPLE_MAIN
    )
    # Generic frame style for background consistency
    style.configure("TFrame", background=BG_WHITE)
    style.configure("TLabel", background=BG_WHITE, foreground=FG_MAIN)

    # Text entry and combo styling
    style.configure(
        "TEntry", fieldbackground=BG_WHITE, foreground=FG_MAIN, insertcolor=FG_MAIN
    )
    style.configure(
        "TCombobox", fieldbackground=BG_WHITE, foreground=FG_MAIN, insertcolor=FG_MAIN
    )
    style.configure(
        "TSpinbox", fieldbackground=BG_WHITE, foreground=FG_MAIN, insertcolor=FG_MAIN
    )

    # Map for Combobox to handle selection colors better in Dark Mode
    style.map("TCombobox", fieldbackground=[("readonly", BG_WHITE)])
    style.map("TCombobox", foreground=[("readonly", FG_MAIN)])


# ── Master Driver Specific Constants & Helpers ──────────────────────────────
# These are consolidated here to provide a consistent suite-wide UI standard.

AMBER = "#d97706"
# BG_APP is now dynamic above
# BG_WHITE is already defined above as "#ffffff"


def get_main() -> str:
    """Returns the main color of the currently active palette."""
    return PURPLE_MAIN


def get_dark() -> str:
    """Returns the dark color of the currently active palette."""
    return PURPLE_DARK


def tab_active() -> str:
    """Returns the darker shade for selected sidebar tabs."""
    return PURPLE_DARK


def tab_inactive() -> str:
    """Returns the main shade for unselected sidebar tabs."""
    return PURPLE_MAIN


TAB_FG = "#ffffff"

# Settings tab specific neutral greys
SETTINGS_TAB_ACTIVE = "#444444"
SETTINGS_TAB_INACTIVE = "#888888"
