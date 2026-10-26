"""Tests for ``audio_suite_shared.whats_new`` - the in-app release notes.

Three layers are pinned separately, because each has its own failure mode:

* the **parser** (Tk-free) must take only the requested version's section and
  rejoin wrapped entries, or the panel shows the wrong release;
* the **pending rule** must offer the panel once per version, stay silent for
  a Master Driver launch, and never claim to have shown notes it could not
  find;
* the **pending range** must cover every release newer than the recorded
  version, so an update skipped across two releases still reports both, and
  must not dump the whole history on a first launch;
* the **panel** must actually render the sections (version labels, headings,
  entries, bold lead-ins) and record the version only when it is closed;
* the **full history** must cover every released section - not just the
  pending ones - newest first, and closing it must record nothing as seen.

The end-to-end case uses a temporary changelog rather than the shipped one, so
it tests the widget rather than the current release; a separate test asserts
the shipped changelog really does carry the running version's notes, which is
what makes the panel useful after an update.

Changed in 1.3.0: new suite for the in-app release-notes panel.
Changed in 2.1.5: covers the full-history window - ``full_changelog``'s
newest-first ordering and its exclusion of ``[Unreleased]``, the panel's Full
Changelog button, and the rule that closing the archive records nothing as
seen.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk

import pytest

from audio_suite_shared import whats_new
from audio_suite_shared.project_version import declared_version

#: The real config accessors, captured before the autouse fixture stubs them,
#: so the round-trip test can exercise the actual persistence path.
_REAL_LOAD = whats_new.suite_config.load_value
_REAL_SAVE = whats_new.suite_config.save_value

CHANGELOG_TEXT = """\
# Changelog

## [Unreleased]

Nothing yet.

## [9.9.2] - 2027-02-01

### Added

- **The middle thing.** It bridges two releases.

## [9.9.1] - 2027-01-01

### Added

- **The newest thing.** It renders a spectrum
  and explains it.

### Fixed

- **A closed defect.** It stayed closed.

## [9.9.0] - 2026-12-01

### Added

- **The older thing.** It is not part of the newer section.
"""


@pytest.fixture(autouse=True)
def isolated_config(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep the panel's seen-version out of the real shared config.

    The teardown drops the module's in-memory snapshot as well: the round-trip
    test loads a temporary config, and leaving that snapshot behind would
    leak its contents into whatever test reads the config next.
    """
    monkeypatch.setattr(
        whats_new.suite_config, "load_value", lambda key, default=None: default
    )
    monkeypatch.setattr(whats_new.suite_config, "save_value", lambda key, value: None)
    yield
    whats_new.suite_config._invalidate_cache()


@pytest.fixture()
def changelog(tmp_path: Path) -> Path:
    """A changelog with two released versions and an open Unreleased."""
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG_TEXT, encoding="utf-8")
    return path


def _widgets(root: tk.Misc) -> list[tk.Misc]:
    """Return every descendant widget of *root*."""
    found: list[tk.Misc] = []
    for child in root.winfo_children():
        found.append(child)
        found.extend(_widgets(child))
    return found


def _text_of(parent: tk.Misc) -> str:
    """Return the read-only text widget's content."""
    texts = [widget for widget in _widgets(parent) if isinstance(widget, tk.Text)]
    assert len(texts) == 1, f"expected exactly one text widget, found {len(texts)}"
    return texts[0].get("1.0", "end")


class TestSectionExtraction:
    """Only the requested version's body is returned."""

    def test_returns_the_requested_section(self) -> None:
        body = whats_new.section_body(CHANGELOG_TEXT, "9.9.1")

        assert body is not None
        assert "The newest thing" in body
        assert "The older thing" not in body

    def test_stops_at_the_next_version_heading(self) -> None:
        body = whats_new.section_body(CHANGELOG_TEXT, "9.9.0")

        assert body is not None
        assert "The older thing" in body
        assert "The newest thing" not in body

    def test_missing_version_has_no_body(self) -> None:
        assert whats_new.section_body(CHANGELOG_TEXT, "9.9.9") is None

    def test_blank_section_has_no_body(self) -> None:
        text = (
            "# Changelog\n\n## [9.9.1] - 2027-01-01\n\n"
            "## [9.9.0] - 2026-12-01\n\n- Old.\n"
        )

        assert whats_new.section_body(text, "9.9.1") is None


class TestBlockParsing:
    """Entries survive wrapping and lose only their Markdown markers."""

    def test_headings_and_bullets_are_separated(self) -> None:
        body = whats_new.section_body(CHANGELOG_TEXT, "9.9.1")
        assert body is not None

        blocks = whats_new.parse_blocks(body)

        assert [(block.style, block.text) for block in blocks][:2] == [
            ("heading", "Added"),
            ("bullet", "It renders a spectrum and explains it."),
        ]
        assert blocks[1].lead == "The newest thing."
        assert ("heading", "Fixed") in [(block.style, block.text) for block in blocks]

    def test_continuation_lines_are_rejoined(self) -> None:
        body = whats_new.section_body(CHANGELOG_TEXT, "9.9.1")
        assert body is not None

        blocks = whats_new.parse_blocks(body)

        bullet = next(block for block in blocks if block.lead == "The newest thing.")
        assert bullet.text == "It renders a spectrum and explains it."
        assert "\n" not in bullet.text

    def test_inline_markdown_is_stripped(self) -> None:
        blocks = whats_new.parse_blocks(
            "### Added\n\n- **Bold lead.** Plain **emphasis** and a "
            "[link](https://example.com) stay readable.\n"
        )

        assert blocks[1].lead == "Bold lead."
        assert "**" not in blocks[1].text
        assert "Plain emphasis" in blocks[1].text
        assert "link" in blocks[1].text
        assert "https://example.com" not in blocks[1].text

    def test_wrapped_prose_becomes_one_paragraph(self) -> None:
        blocks = whats_new.parse_blocks(
            "The suite now does a thing that wraps\nacross two source lines.\n"
        )

        assert blocks == [
            whats_new.Block(
                "paragraph",
                "The suite now does a thing that wraps across two source lines.",
            )
        ]


class TestPendingRule:
    """The panel is offered once per version and never to an unattended run."""

    def test_offers_notes_for_an_unseen_version(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)

        notes = whats_new.pending_notes("9.9.1", argv=["prog"], changelog=changelog)

        assert notes is not None
        assert notes.version == "9.9.1"
        assert notes.blocks

    def test_already_seen_version_is_not_offered(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)
        monkeypatch.setattr(
            whats_new.suite_config,
            "load_value",
            lambda key, default=None: "9.9.1",
        )

        assert (
            whats_new.pending_notes("9.9.1", argv=["prog"], changelog=changelog) is None
        )

    def test_driver_launch_is_not_offered(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)

        notes = whats_new.pending_notes(
            "9.9.1", argv=["prog", "--live", "D:/music"], changelog=changelog
        )

        assert notes is None

    def test_environment_can_disable_the_panel(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(whats_new.DISABLE_ENV, "0")

        assert (
            whats_new.pending_notes("9.9.1", argv=["prog"], changelog=changelog) is None
        )

    def test_missing_section_is_not_offered(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)

        assert (
            whats_new.pending_notes("9.9.9", argv=["prog"], changelog=changelog) is None
        )

    def test_force_ignores_the_seen_version(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            whats_new.suite_config,
            "load_value",
            lambda key, default=None: "9.9.1",
        )

        notes = whats_new.pending_notes(
            "9.9.1", argv=["prog", "--live"], changelog=changelog, force=True
        )

        assert notes is not None

    def test_mark_seen_records_the_version(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: dict[str, object] = {}
        monkeypatch.setattr(
            whats_new.suite_config,
            "save_value",
            lambda key, value: recorded.update({key: value}),
        )

        whats_new.mark_seen("9.9.1")

        assert recorded == {whats_new.SEEN_VERSION_KEY: "9.9.1"}


class TestVersionOrdering:
    """Changelog headings are ordered numerically, never by their text."""

    def test_numeric_key_ignores_a_suffix(self) -> None:
        assert whats_new.version_key("1.3.0") == (1, 3, 0)
        assert whats_new.version_key("1.3.0-rc1") == (1, 3, 0)

    def test_unreleased_has_no_key(self) -> None:
        assert whats_new.version_key("Unreleased") is None
        assert whats_new.version_key("") is None

    def test_sections_are_listed_in_document_order(self) -> None:
        assert whats_new.released_versions(CHANGELOG_TEXT) == [
            "Unreleased",
            "9.9.2",
            "9.9.1",
            "9.9.0",
        ]


class TestPendingRange:
    """Every release since the recorded version is shown, newest first."""

    def test_two_skipped_releases_are_both_included(self, changelog: Path) -> None:
        notes = whats_new.notes_since("9.9.2", "9.9.0", changelog)

        assert notes is not None
        assert notes.version == "9.9.2"
        assert notes.versions == ("9.9.2", "9.9.1")
        assert notes.blocks[0] == whats_new.Block("version", "9.9.2")
        assert "The middle thing." in [block.lead for block in notes.blocks]
        assert "The older thing." not in [block.lead for block in notes.blocks]

    def test_newest_release_comes_first(self, changelog: Path) -> None:
        notes = whats_new.notes_since("9.9.2", "9.8.0", changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2", "9.9.1", "9.9.0")
        headings = [b.text for b in notes.blocks if b.style == "version"]
        assert headings == ["9.9.2", "9.9.1", "9.9.0"]
        assert [b.lead for b in notes.blocks if b.style == "bullet"] == [
            "The middle thing.",
            "The newest thing.",
            "A closed defect.",
            "The older thing.",
        ]

    def test_first_launch_shows_only_the_running_release(self, changelog: Path) -> None:
        notes = whats_new.notes_since("9.9.2", "", changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2",)
        assert [b.style for b in notes.blocks] == ["heading", "bullet"]

    def test_already_seen_version_shows_the_running_release(
        self, changelog: Path
    ) -> None:
        """The Help menu still has something to reopen after the panel was seen."""
        notes = whats_new.notes_since("9.9.2", "9.9.2", changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2",)

    def test_downgrade_shows_only_the_running_release(self, changelog: Path) -> None:
        notes = whats_new.notes_since("9.9.1", "9.9.2", changelog)

        assert notes is not None
        assert notes.versions == ("9.9.1",)

    def test_unparseable_seen_version_shows_only_the_running_release(
        self, changelog: Path
    ) -> None:
        notes = whats_new.notes_since("9.9.2", "junk", changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2",)

    def test_blank_intermediate_section_gets_no_heading(self, tmp_path: Path) -> None:
        text = (
            "# Changelog\n\n"
            "## [9.9.2] - 2027-02-01\n\n- New.\n\n"
            "## [9.9.1] - 2027-01-01\n\n"
            "## [9.9.0] - 2027-01-01\n\n- Old.\n"
        )
        path = tmp_path / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")

        notes = whats_new.notes_since("9.9.2", "9.8.0", path)

        assert notes is not None
        assert notes.versions == ("9.9.2", "9.9.0")

    def test_running_version_without_a_section_shows_nothing(
        self, changelog: Path
    ) -> None:
        assert whats_new.notes_since("9.9.9", "9.9.0", changelog) is None

    def test_pending_notes_passes_the_recorded_version_through(
        self, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)
        monkeypatch.setattr(
            whats_new.suite_config,
            "load_value",
            lambda key, default=None: "9.9.0",
        )

        notes = whats_new.pending_notes("9.9.2", argv=["prog"], changelog=changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2", "9.9.1")


class TestShippedChangelog:
    """The panel's usefulness depends on the running version having notes."""

    def test_running_version_has_release_notes(self) -> None:
        notes = whats_new.release_notes(declared_version())

        assert notes is not None, (
            "CHANGELOG.md has no section for the running version - the What's "
            "New panel would silently never open after an update"
        )
        assert notes.blocks, "the running version's section parsed to no blocks"


class TestPanel:
    """The Toplevel renders the section and records the version on close."""

    def _notes(self, changelog: Path, version: str = "9.9.1") -> whats_new.ReleaseNotes:
        notes = whats_new.release_notes(version, changelog)
        assert notes is not None
        return notes

    def test_renders_the_section_and_excludes_older_ones(
        self, tk_root: tk.Tk, changelog: Path
    ) -> None:
        panel = whats_new.show(tk_root, self._notes(changelog))

        try:
            assert "What's New in AudioSuite 9.9.1" in panel.title()
            body = _text_of(panel)
            assert "Added" in body
            assert "Fixed" in body
            assert "The newest thing." in body
            assert "It renders a spectrum and explains it." in body
            assert "The older thing." not in body
            assert whats_new.BULLET_GLYPH in body
        finally:
            panel.destroy()

    def test_close_records_the_version(
        self, tk_root: tk.Tk, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[str] = []
        monkeypatch.setattr(whats_new, "mark_seen", recorded.append)

        panel = whats_new.show(tk_root, self._notes(changelog))
        buttons = [w for w in _widgets(panel) if isinstance(w, ttk.Button)]
        assert buttons, "the panel has no close button"
        buttons[0].invoke()

        assert recorded == ["9.9.1"]
        assert not panel.winfo_exists()

    def test_custom_close_callback_replaces_the_record(
        self, tk_root: tk.Tk, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[str] = []
        monkeypatch.setattr(whats_new, "mark_seen", recorded.append)
        closed: list[bool] = []

        panel = whats_new.show(
            tk_root, self._notes(changelog), on_close=lambda: closed.append(True)
        )
        buttons = [w for w in _widgets(panel) if isinstance(w, ttk.Button)]
        buttons[0].invoke()

        assert closed == [True]
        assert recorded == []

    def test_renders_every_pending_release_under_its_own_heading(
        self, tk_root: tk.Tk, changelog: Path
    ) -> None:
        notes = whats_new.notes_since("9.9.2", "9.9.0", changelog)
        assert notes is not None

        panel = whats_new.show(tk_root, notes)

        try:
            assert "9.9.2" in panel.title()
            body = _text_of(panel)
            assert "Version 9.9.2" in body
            assert "Version 9.9.1" in body
            assert "Version 9.9.0" not in body, "an already-seen release leaked in"
            assert "The middle thing." in body
            assert "The newest thing." in body
            assert "The older thing." not in body
            subtitles = [
                w.cget("text")
                for w in _widgets(panel)
                if isinstance(w, tk.Label)
                and w.cget("text") == whats_new.MULTI_SUBTITLE
            ]
            assert subtitles, "the multi-release panel kept the single-release subtitle"
        finally:
            panel.destroy()

    def test_single_release_panel_has_no_version_heading(
        self, tk_root: tk.Tk, changelog: Path
    ) -> None:
        panel = whats_new.show(tk_root, self._notes(changelog, "9.9.2"))

        try:
            body = _text_of(panel)
            assert "Version 9.9.2" not in body
            assert whats_new.MULTI_SUBTITLE not in body
        finally:
            panel.destroy()

    def test_offer_pending_opens_the_panel(
        self, tk_root: tk.Tk, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)

        panel = whats_new.offer_pending(
            tk_root, version="9.9.1", argv=["prog"], changelog=changelog
        )

        assert panel is not None
        try:
            assert "9.9.1" in panel.title()
        finally:
            panel.destroy()

    def test_first_launch_offers_then_remembers(
        self, tk_root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real config loop: offer once, write the version on close."""
        import json

        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)
        config_path = tmp_path / "audio_suite_config.json"
        monkeypatch.setattr(whats_new.suite_config, "CONFIG_PATH", config_path)
        monkeypatch.setattr(
            whats_new.suite_config,
            "_LOCK_PATH",
            tmp_path / "audio_suite_config.json.lock",
        )
        monkeypatch.setattr(whats_new.suite_config, "load_value", _REAL_LOAD)
        monkeypatch.setattr(whats_new.suite_config, "save_value", _REAL_SAVE)
        whats_new.suite_config._invalidate_cache()

        panel = whats_new.offer_pending(tk_root, argv=["prog"])

        assert panel is not None, "the first launch after an update showed nothing"
        buttons = [w for w in _widgets(panel) if isinstance(w, ttk.Button)]
        buttons[0].invoke()

        saved = json.loads(config_path.read_text(encoding="utf-8"))
        assert saved[whats_new.SEEN_VERSION_KEY] == declared_version()

        whats_new.suite_config._invalidate_cache()
        assert whats_new.offer_pending(tk_root, argv=["prog"]) is None, (
            "the panel was offered twice for the same version"
        )

    def test_offer_pending_stays_closed_when_seen(
        self, tk_root: tk.Tk, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(whats_new.DISABLE_ENV, raising=False)
        monkeypatch.setattr(
            whats_new.suite_config,
            "load_value",
            lambda key, default=None: "9.9.1",
        )

        assert (
            whats_new.offer_pending(
                tk_root, version="9.9.1", argv=["prog"], changelog=changelog
            )
            is None
        )


class TestFullChangelog:
    """The archive covers every released section, newest first."""

    def test_covers_every_release_newest_first(self, changelog: Path) -> None:
        notes = whats_new.full_changelog(changelog)

        assert notes is not None
        assert notes.versions == ("9.9.2", "9.9.1", "9.9.0")
        assert [block.text for block in notes.blocks if block.style == "version"] == [
            "9.9.2",
            "9.9.1",
            "9.9.0",
        ]
        leads = [block.lead for block in notes.blocks]
        assert "The older thing." in leads, "the oldest release is missing"
        assert "The newest thing." in leads

    def test_unreleased_section_is_not_a_release(self, changelog: Path) -> None:
        notes = whats_new.full_changelog(changelog)

        assert notes is not None
        assert "Unreleased" not in notes.versions
        assert all(block.text != "Nothing yet." for block in notes.blocks)

    def test_order_comes_from_the_version_numbers(self, tmp_path: Path) -> None:
        """A heading in the wrong place cannot render the history out of order."""
        text = (
            "# Changelog\n\n"
            "## [9.9.9] - 2027-01-01\n\n- Nine.\n\n"
            "## [9.9.10] - 2027-02-01\n\n- Ten.\n"
        )
        path = tmp_path / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")

        notes = whats_new.full_changelog(path)

        assert notes is not None
        assert notes.versions == ("9.9.10", "9.9.9")
        assert notes.version == "9.9.10", "the window names the wrong newest release"

    def test_blank_sections_are_skipped(self, tmp_path: Path) -> None:
        text = (
            "# Changelog\n\n"
            "## [9.9.1] - 2027-01-01\n\n- New.\n\n"
            "## [9.9.0] - 2026-12-01\n\n"
        )
        path = tmp_path / "CHANGELOG.md"
        path.write_text(text, encoding="utf-8")

        notes = whats_new.full_changelog(path)

        assert notes is not None
        assert notes.versions == ("9.9.1",)
        assert "9.9.0" not in [block.text for block in notes.blocks]

    def test_no_changelog_means_no_history(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(whats_new, "find_changelog", lambda start=None: None)

        assert whats_new.full_changelog() is None

    def test_changelog_without_a_release_has_no_history(self, tmp_path: Path) -> None:
        path = tmp_path / "CHANGELOG.md"
        path.write_text("# Changelog\n\n## [Unreleased]\n\n- Soon.\n", encoding="utf-8")

        assert whats_new.full_changelog(path) is None


class TestFullChangelogPanel:
    """The panel's button opens the whole file and records nothing on close."""

    @staticmethod
    def _button(window: tk.Misc, text: str) -> ttk.Button:
        """Return the button labelled *text*."""
        for widget in _widgets(window):
            if isinstance(widget, ttk.Button) and widget.cget("text") == text:
                return widget
        raise AssertionError(f"no {text!r} button in the window")

    def test_panel_offers_the_button(self, tk_root: tk.Tk, changelog: Path) -> None:
        notes = whats_new.release_notes("9.9.1", changelog)
        assert notes is not None

        panel = whats_new.show(tk_root, notes, changelog=changelog)

        try:
            assert self._button(panel, "Full Changelog").winfo_exists()
        finally:
            panel.destroy()

    def test_button_opens_the_releases_outside_the_panel(
        self, tk_root: tk.Tk, changelog: Path
    ) -> None:
        notes = whats_new.release_notes("9.9.1", changelog)
        assert notes is not None

        panel = whats_new.show(tk_root, notes, changelog=changelog)

        try:
            self._button(panel, "Full Changelog").invoke()
            history = [
                widget
                for widget in panel.winfo_children()
                if isinstance(widget, tk.Toplevel)
            ]
            assert len(history) == 1, "the button opened no history window"
            assert history[0].title() == whats_new.FULL_WINDOW_TITLE
            body = _text_of(history[0])
            assert "Version 9.9.2" in body
            assert "Version 9.9.0" in body, "the older release is not in the archive"
            assert "The older thing." in body
        finally:
            panel.destroy()

    def test_history_renders_every_release(
        self, tk_root: tk.Tk, changelog: Path
    ) -> None:
        history = whats_new.show_full_changelog(tk_root, changelog=changelog)

        assert history is not None
        try:
            body = _text_of(history)
            assert "Version 9.9.2" in body
            assert "Version 9.9.1" in body
            assert "Version 9.9.0" in body
            assert "Nothing yet." not in body, "the unreleased section leaked in"
            labels = [
                widget.cget("text")
                for widget in _widgets(history)
                if isinstance(widget, tk.Label)
            ]
            assert whats_new.FULL_SUBTITLE in labels
        finally:
            history.destroy()

    def test_closing_the_history_records_nothing(
        self, tk_root: tk.Tk, changelog: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recorded: list[str] = []
        monkeypatch.setattr(whats_new, "mark_seen", recorded.append)

        history = whats_new.show_full_changelog(tk_root, changelog=changelog)

        assert history is not None
        buttons = [w for w in _widgets(history) if isinstance(w, ttk.Button)]
        assert buttons, "the history window has no close button"
        buttons[0].invoke()

        assert recorded == [], "browsing the archive marked the release as seen"
        assert not history.winfo_exists()

    def test_history_is_unavailable_without_a_changelog(
        self, tk_root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(whats_new, "find_changelog", lambda start=None: None)

        assert whats_new.show_full_changelog(tk_root) is None
