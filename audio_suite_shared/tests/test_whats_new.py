"""Tests for ``audio_suite_shared.whats_new`` - the in-app release notes.

Three layers are pinned separately, because each has its own failure mode:

* the **parser** (Tk-free) must take only the requested version's section and
  rejoin wrapped entries, or the panel shows the wrong release;
* the **pending rule** must offer the panel once per version, stay silent for
  a Master Driver launch, and never claim to have shown notes it could not
  find;
* the **panel** must actually render the section (headings, entries, bold
  lead-ins) and record the version only when it is closed.

The end-to-end case uses a temporary changelog rather than the shipped one, so
it tests the widget rather than the current release; a separate test asserts
the shipped changelog really does carry the running version's notes, which is
what makes the panel useful after an update.

Changed in 1.3.0: new suite for the in-app release-notes panel.
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
