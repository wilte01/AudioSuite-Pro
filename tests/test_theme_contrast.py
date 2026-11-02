"""tests/test_theme_contrast.py — repo-wide theme-conformance locks (T-02).

The class this closes: a widget is given a themed ``bg`` and no foreground, so
Tk keeps its own default (the symbolic ``SystemWindowText``, black) and the text
measures 1.26:1 on the dark body.  Nothing else in the gate can see it — the
module compiles, ruff, mypy and the whole suite stay green while the window is
unreadable — so the two halves of this module are the only evidence.

The two halves are complementary on purpose:

- **Static** (:class:`TestWidgetColourKeywords`) walks every first-party UI
  module and asserts each constructor carries the colour keywords for the states
  it can be seen in.  It covers widgets no runtime test builds (a dialog opened
  on demand, a tab no test constructs).
- **Runtime** (:class:`TestBuiltSurfacesFollowTheTheme`) builds the real Master
  Driver window and the shared Setup-tab skeleton in the four theme states and
  reads the *effective* colours back off every widget.  It covers what the AST
  cannot see: a keyword whose value is wrong for the theme.

Both read the effective pair back off the widget and resolve it through
``winfo_rgb()``, because a symbolic name is exactly what the bug leaves behind;
asserting the ``styles`` constants would pass on the broken build.

Changed in 2.3.1: the sweep and its lock for text colour against the theme
(PLAN_restoration_2026-10-31.md T-02), generalising T-01's card contrast helper
and T-03's locked-strip assertions into one repo-wide contract.
"""

from __future__ import annotations

import ast
import tkinter as tk
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pytest

from audio_suite_shared import styles

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories this walk does not own.  Deliberately a fresh set: reusing a
#: constant whose purpose is the opposite (a scan that excludes ``tests`` while
#: needing to scan them, or vice versa) drops every candidate before matching
#: and passes vacuously forever (AGENTS.md, *Never Lose a Rule to a Scripted
#: Edit*).  ``tests`` is here because a test's own stub widgets are not the
#: product, and this module measures those separately below.
_NOT_SOURCE = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "documentation",
        "plugins",
        "tests",
    }
)

#: Widget classes that paint text the user reads.
_TEXT_BEARING = frozenset(
    {
        "Button",
        "Checkbutton",
        "Entry",
        "Label",
        "Menubutton",
        "Message",
        "Radiobutton",
        "Text",
    }
)

#: Classes whose indicator square is a separate surface from the background.
_TOGGLES = frozenset({"Checkbutton", "Radiobutton"})

#: Classes with a ``-disabledforeground`` option.  ``tk.Text`` is absent on
#: purpose: it has no disabled colours at all and keeps painting its foreground.
_DISABLEABLE = frozenset(
    {
        "Button",
        "Checkbutton",
        "Entry",
        "Label",
        "Listbox",
        "Menubutton",
        "Message",
        "Radiobutton",
        "Spinbox",
    }
)

#: WCAG AA for body text, and its 3:1 counterpart for a UI component (the tick
#: inside a checkbutton's indicator square).
_MIN_TEXT_CONTRAST = 4.5
_MIN_INDICATOR_CONTRAST = 3.0

#: ``(theme mode, what the OS reports)``.  ``None`` leaves the real probe in
#: place; the two ``System`` states patch ``styles._get_system_theme`` rather
#: than ``os.name`` (AGENTS.md, *Verification Tooling Traps*).
_THEME_STATES: tuple[tuple[str, str | None], ...] = (
    ("Light", None),
    ("Dark", None),
    ("System", "Light"),
    ("System", "Dark"),
)
_STATE_IDS = ("Light", "Dark", "System->Light", "System->Dark")


# ── The static half: constructors carry their colour keywords ────────────────


def _class_name(call: ast.Call) -> str | None:
    """The capitalised attribute a call is made through, e.g. ``Label``."""
    node: ast.expr = call.func
    while isinstance(node, ast.Attribute):
        if node.attr[:1].isupper():
            return node.attr
        node = node.value
    return None


def _options(call: ast.Call) -> dict[str, ast.expr]:
    """The call's keyword arguments by name (``**mapping`` keys are ignored)."""
    return {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def _carries_text(call: ast.Call) -> bool:
    """True when the constructor visibly carries text of its own."""
    options = _options(call)
    text = options.get("text")
    if isinstance(text, ast.Constant) and isinstance(text.value, str):
        return bool(text.value.strip())
    return "textvariable" in options


def _constructed_disabled(call: ast.Call) -> bool:
    """True when the constructor itself asks for the disabled state."""
    state = _options(call).get("state")
    return isinstance(state, ast.Constant) and state.value == "disabled"


def _scan_source(source: str, filename: str) -> tuple[list[str], int]:
    """Colour-keyword violations in *source*, and constructors inspected.

    Args:
        source: Python source to parse.
        filename: Name to quote in a violation, so the failure names a file.

    Returns:
        ``(violations, inspected)`` — human-readable violation lines, and how
        many widget constructors the walk actually looked at (the caller
        asserts this is non-empty, so an empty scan fails instead of passing).
    """
    tree = ast.parse(source)
    violations: list[str] = []
    inspected = 0

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _class_name(node)
        if name not in _TEXT_BEARING and name not in _DISABLEABLE:
            continue
        inspected += 1
        options = _options(node)
        themed = bool({"bg", "background"} & options.keys())
        has_foreground = bool({"fg", "foreground"} & options.keys())
        where = f"{filename}:{node.lineno} tk.{name}"

        # A themed background with no foreground: the 1.26:1 defect.
        if (
            themed
            and name in _TEXT_BEARING
            and _carries_text(node)
            and not has_foreground
        ):
            violations.append(
                f"{where}: themed background, no foreground "
                f"(text keeps Tk's SystemWindowText)"
            )
        # The indicator square is a second surface the background does not
        # reach; its default is the symbolic SystemWindow in both themes.
        if themed and name in _TOGGLES and "selectcolor" not in options:
            violations.append(
                f"{where}: themed background, no selectcolor "
                f"(indicator keeps Tk's SystemWindow)"
            )
        # A widget built disabled paints with Tk's own grey, not the theme's.
        if (
            name in _DISABLEABLE
            and _constructed_disabled(node)
            and "disabledforeground" not in options
        ):
            violations.append(
                f"{where}: constructed disabled, no disabledforeground "
                f"(paints Tk's SystemDisabledText)"
            )

    return violations, inspected


def _source_files() -> list[Path]:
    """Every first-party Python module the sweep owns, in a stable order."""
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.py")
        if not (_NOT_SOURCE & set(path.relative_to(REPO_ROOT).parts))
    )


class TestWidgetColourKeywords:
    """Every themed widget constructor states the colour of its own text."""

    def test_every_themed_widget_carries_its_text_colours(self) -> None:
        files = _source_files()
        # A scan that found no files would pass vacuously; the tree holds
        # hundreds, so this is a floor, not a target.
        assert len(files) > 300, f"the walk found only {len(files)} modules"

        violations: list[str] = []
        inspected = 0
        for path in files:
            found, count = _scan_source(
                path.read_text(encoding="utf-8"),
                path.relative_to(REPO_ROOT).as_posix(),
            )
            violations.extend(found)
            inspected += count

        assert inspected > 300, f"the walk inspected only {inspected} constructors"
        assert not violations, (
            f"{len(violations)} widget constructor(s) set a themed background and "
            f"no colour for a state they can be seen in:\n  " + "\n  ".join(violations)
        )

    def test_the_walk_reaches_the_swept_modules(self) -> None:
        """The exclusion set must not swallow the modules the sweep fixes."""
        scanned = {path.relative_to(REPO_ROOT).as_posix() for path in _source_files()}
        for expected in (
            "master_driver/ui/cards/_card_base.py",
            "master_driver/ui_panels.py",
            "cd_ripper/ui/results_tab.py",
            "audio_suite_shared/ui_common.py",
            "audio_suite_shared/styles.py",
        ):
            assert expected in scanned, expected

    def test_the_checker_flags_a_broken_constructor(self) -> None:
        """The harness has to be able to fail, so prove it does.

        Five violations: the checkbutton is missing both its foreground and
        its ``selectcolor``, the label its foreground, and the disabled
        button both its foreground and its disabled foreground.
        """
        source = (
            "import tkinter as tk\n"
            "tk.Checkbutton(parent, text='Parallel Processing', bg='#1e1e1e')\n"
            "tk.Label(parent, text='Rip Complete!', bg='#ffffff')\n"
            "tk.Button(parent, text='Go', bg='#7b4db8', state='disabled')\n"
            "tk.Label(parent, text='', bg='#ffffff')\n"
            "tk.Label(parent, text='Fine', bg='#ffffff', fg='#ffffff')\n"
        )
        violations, inspected = _scan_source(source, "<probe>")
        assert inspected == 5
        assert len(violations) == 5, violations

    def test_text_colors_covers_every_family(self) -> None:
        """The helper is the sweep's contract; a dropped key is a silent hole."""
        required = {
            "label": {"background", "foreground", "disabledforeground"},
            "toggle": {
                "background",
                "foreground",
                "activebackground",
                "activeforeground",
                "selectcolor",
                "disabledforeground",
            },
            "field": {
                "background",
                "foreground",
                "insertbackground",
                "disabledbackground",
                "disabledforeground",
            },
            "accent": {
                "background",
                "foreground",
                "activebackground",
                "activeforeground",
                "disabledforeground",
            },
        }
        assert set(required) == set(styles.TEXT_COLOR_KINDS)
        for kind, keys in required.items():
            mapping = styles.text_colors(kind)  # type: ignore[arg-type]
            assert set(mapping) == keys, kind
            if kind != "accent":
                # The accent family fills with the palette main colour,
                # which is the point of it; the rest sit on a card.
                assert mapping["background"] == styles.BG_WHITE, kind

        assert (
            styles.text_colors("toggle", background=styles.BG_LIGHT)["selectcolor"]
            == styles.BG_LIGHT
        )
        assert styles.text_colors("accent")["background"] == styles.get_main()
        assert styles.text_colors("accent")["foreground"] == "#ffffff"
        with pytest.raises(ValueError):
            styles.text_colors("nonsense")


# ── The runtime half: the built surfaces, in all four theme states ───────────


def _resolved_rgb(widget: tk.Misc, colour: str) -> tuple[int, int, int]:
    """The 8-bit RGB a colour name paints as, symbolic names included."""
    red, green, blue = widget.winfo_rgb(colour)
    return (red // 256, green // 256, blue // 256)


def _relative_luminance(colour: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an 8-bit sRGB triple."""
    linear: list[float] = []
    for value in colour:
        scaled = value / 255
        linear.append(
            scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(widget: tk.Misc, foreground: str, background: str) -> float:
    """How far *foreground* sits from *background* on *widget*'s display."""
    lighter, darker = sorted(
        (
            _relative_luminance(_resolved_rgb(widget, foreground)),
            _relative_luminance(_resolved_rgb(widget, background)),
        ),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _is_symbolic(colour: str) -> bool:
    """True for a Tk system colour, which ignores the suite theme entirely."""
    return colour.startswith("System")


def _shows_text(widget: tk.Misc) -> bool:
    """True when *widget* paints text the user reads."""
    keys = widget.keys()
    if "text" in keys and str(widget.cget("text")).strip():
        return True
    if "textvariable" in keys and str(widget.cget("textvariable")).strip():
        return True
    return widget.winfo_class() in {"Entry", "Text"}


def _paints(widget: tk.Misc) -> bool:
    """True for a widget with text or an indicator the theme owns."""
    return _shows_text(widget) or widget.winfo_class() in _TOGGLES


def _walk(widget: tk.Misc) -> Iterator[tk.Misc]:
    """Every widget at or under *widget*."""
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


def _measured_states(widget: tk.Misc) -> list[tuple[str, str, str, float]]:
    """``(state, foreground, background, minimum)`` pairs *widget* can show."""
    keys = widget.keys()
    if "foreground" not in keys or "background" not in keys:
        return []

    foreground = str(widget.cget("foreground"))
    background = str(widget.cget("background"))
    # A ttk widget reports no per-widget colours at all: its pair lives on
    # the style map, which T-03's locked-strip test reads via style.lookup.
    if not foreground.strip() or not background.strip():
        return []
    states: list[tuple[str, str, str, float]] = []

    if _shows_text(widget):
        states.append(("normal", foreground, background, _MIN_TEXT_CONTRAST))
        # The active colours are painted by a widget with an active binding;
        # Tk gives every Label a symbolic default it never draws, so measuring
        # those would report a colour the user cannot see.  Buttons do draw
        # theirs on hover, which is a separate sweep (plan section 7).
        if widget.winfo_class() in _TOGGLES and (
            "activeforeground" in keys and "activebackground" in keys
        ):
            active_foreground = str(widget.cget("activeforeground"))
            active_background = str(widget.cget("activebackground"))
            if active_foreground.strip() and active_background.strip():
                states.append(
                    (
                        "active",
                        active_foreground,
                        active_background,
                        _MIN_TEXT_CONTRAST,
                    )
                )

    # The tick inside a toggle's box is drawn in the foreground on selectcolor.
    if widget.winfo_class() in _TOGGLES and "selectcolor" in keys:
        selectcolor = str(widget.cget("selectcolor"))
        if selectcolor.strip():
            states.append(
                ("indicator", foreground, selectcolor, _MIN_INDICATOR_CONTRAST)
            )

    # Only a widget that is *currently* disabled paints its disabled colours;
    # requiring them everywhere would sweep 80 entries no run locks.
    if (
        "disabledforeground" in keys
        and "state" in keys
        and str(widget.cget("state")) == "disabled"
    ):
        disabled_background = (
            str(widget.cget("disabledbackground"))
            if "disabledbackground" in keys
            else background
        )
        states.append(
            (
                "disabled",
                str(widget.cget("disabledforeground")),
                disabled_background,
                _MIN_TEXT_CONTRAST,
            )
        )
    return states


def _symbolic_options(widget: tk.Misc) -> list[str]:
    """Theme-owned options *widget* still leaves on a symbolic Tk colour.

    Only a widget whose background the code themed is checked: a widget that
    passed no background at all keeps Tk's own surface, which is a different
    (and much larger) question than the one this lock answers.
    """
    if not _paints(widget):
        return []
    keys = widget.keys()
    if "background" not in keys or _is_symbolic(str(widget.cget("background"))):
        return []
    options = ["background", "foreground"]
    if widget.winfo_class() in _TOGGLES:
        options.extend(["activebackground", "activeforeground", "selectcolor"])
    if "state" in keys and str(widget.cget("state")) == "disabled":
        options.extend(["disabledforeground", "disabledbackground"])
    return [
        f"{option}={widget.cget(option)}"
        for option in options
        if option in keys and _is_symbolic(str(widget.cget(option)))
    ]


@contextmanager
def _theme(
    mode: str, os_theme: str | None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Run inside one theme state with the shipped palette, then restore both.

    The palette is pinned because a live Windows-accent palette left active by
    another module's tests is read from the OS registry, and its tint decides
    ``BG_LIGHT``/``BG_READONLY``: the same assertion would otherwise measure a
    different suite depending on test order.  Contrast across every palette is
    a separate sweep.
    """
    if os_theme is not None:
        monkeypatch.setattr(styles, "_get_system_theme", lambda: os_theme)
    theme_before = styles.THEME_MODE
    palette_before = styles.get_active_palette_name()
    styles.set_active_palette(styles.DEFAULT_PALETTE)
    styles.set_theme_mode(mode)
    try:
        yield
    finally:
        styles.set_theme_mode(theme_before)
        styles.set_active_palette(palette_before)


@contextmanager
def _driver_window(
    root: tk.Tk, mode: str, os_theme: str | None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tk.Misc]:
    """The real Master Driver window, built inside one theme state."""
    monkeypatch.setattr(
        "master_driver.app._suite_config.load_last_directory", lambda: ""
    )
    monkeypatch.setattr(
        "master_driver.app._suite_config.load_palette", lambda: styles.DEFAULT_PALETTE
    )
    monkeypatch.setattr("master_driver.app._suite_config.load_theme_mode", lambda: mode)
    with _theme(mode, os_theme, monkeypatch):
        from master_driver.app import AudioSuiteDriver

        top = tk.Toplevel(root)
        top.withdraw()
        try:
            yield AudioSuiteDriver(top).root
        finally:
            top.destroy()


@contextmanager
def _setup_tab(
    root: tk.Tk, mode: str, os_theme: str | None, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tk.Misc]:
    """The shared Setup-tab skeleton, built inside one theme state.

    This is the frame 18 of the 19 tools embed verbatim, so its own title,
    preset row and start button are shared surfaces rather than one tool's.
    """
    from audio_suite_shared import ui_common

    class _SampleSetupTab(ui_common.BaseSetupFrame):
        """The skeleton with an empty option body."""

        def _build_options(self) -> None:
            """No tool-specific options: the shared widgets are the subject."""

    with _theme(mode, os_theme, monkeypatch):
        frame = _SampleSetupTab(
            root,
            title="Sample Tool",
            start_text="BEGIN SAMPLE",
            on_start=lambda: None,
            folder_path=tk.StringVar(root),
            run_mode=tk.StringVar(root, value="Dry Run"),
            auto_start_var=tk.BooleanVar(root),
            auto_end_var=tk.BooleanVar(root),
            clear_logs_var=tk.BooleanVar(root),
            parallel_var=tk.BooleanVar(root),
        )
        try:
            yield frame
        finally:
            frame.destroy()


def _assert_surface_follows_the_theme(surface: tk.Misc, state_label: str) -> None:
    """Every widget under *surface* is legible and off Tk's symbolic colours."""
    measured = [
        (
            widget,
            name,
            foreground,
            background,
            minimum,
            _contrast_ratio(widget, foreground, background),
        )
        for widget in _walk(surface)
        for name, foreground, background, minimum in _measured_states(widget)
    ]
    symbolic = [
        (widget, options)
        for widget in _walk(surface)
        if (options := _symbolic_options(widget))
    ]

    assert measured, f"{state_label}: no text-bearing widget was measured"
    failures = [
        f"{widget.winfo_class()} {_describe(widget)} ({name}): "
        f"{foreground} on {background} = {ratio:.2f}:1 (needs {minimum}:1)"
        for widget, name, foreground, background, minimum, ratio in measured
        if ratio < minimum
    ]
    assert not failures, f"{state_label} — text below its minimum:\n  " + "\n  ".join(
        failures
    )
    offenders = [
        f"{widget.winfo_class()} {_describe(widget)}: {', '.join(options)}"
        for widget, options in symbolic
    ]
    assert not offenders, (
        f"{state_label} — themed widget(s) still on a symbolic Tk colour, which "
        f"is fixed for both themes:\n  " + "\n  ".join(offenders)
    )


def _describe(widget: tk.Misc) -> str:
    """A short identification of *widget* for a failure line."""
    keys = widget.keys()
    text = str(widget.cget("text")) if "text" in keys else ""
    if not text.strip() and "textvariable" in keys:
        text = f"<{widget.cget('textvariable')}>"
    first_line = text.splitlines()[0] if text.splitlines() else ""
    return repr(first_line[:48])


class TestBuiltSurfacesFollowTheTheme:
    """The windows the user actually sees, measured in all four theme states."""

    @pytest.mark.parametrize(("mode", "os_theme"), _THEME_STATES, ids=_STATE_IDS)
    def test_the_master_driver_window(
        self,
        root: tk.Tk,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        os_theme: str | None,
    ) -> None:
        with _driver_window(root, mode, os_theme, monkeypatch) as window:
            _assert_surface_follows_the_theme(window, _state_label(mode, os_theme))

    @pytest.mark.parametrize(("mode", "os_theme"), _THEME_STATES, ids=_STATE_IDS)
    def test_the_shared_setup_tab(
        self,
        root: tk.Tk,
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        os_theme: str | None,
    ) -> None:
        with _setup_tab(root, mode, os_theme, monkeypatch) as frame:
            _assert_surface_follows_the_theme(frame, _state_label(mode, os_theme))

    def test_the_system_dark_state_really_goes_dark(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard: the ``System``->Dark case must not measure the Light palette."""
        monkeypatch.setattr(styles, "_get_system_theme", lambda: "Dark")
        theme_before = styles.THEME_MODE
        with _theme("System", "Dark", monkeypatch):
            assert styles.BG_WHITE == "#1e1e1e"
            assert styles.FG_MAIN == "#ffffff"
        assert styles.THEME_MODE == theme_before


def _state_label(mode: str, os_theme: str | None) -> str:
    """A readable name for one theme state, for failure messages."""
    return f"{mode} (OS reports {os_theme})" if os_theme else mode
