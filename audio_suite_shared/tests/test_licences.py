"""Tests for audio_suite_shared.licences and its Help > Licences viewer.

The defect these lock: the licence texts travelled with the two bundled binaries
but were reachable only by knowing the install layout and a filename. A Help
entry that listed files it could not open, or opened one folder instead of
showing a text a user can actually read, would look fixed and still fail the
user it was added for.

Changed in 2.7.0: new module. The resolver is driven through a synthetic suite
root rather than the real one, so the test states the rule instead of depending
on whether this checkout happens to carry the staged folder.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from audio_suite_shared import licences, ui_helpers


def _write(path: Path, text: str = "text\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def fake_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the resolver at a synthetic installation root."""
    monkeypatch.setattr(licences.suite_paths, "suite_root", lambda: tmp_path)
    return tmp_path


def _walk(widget: tk.Misc) -> Iterator[tk.Misc]:
    """Every widget at or under *widget*."""
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


class TestLicenceDirectory:
    """One rule, two layouts: installed payload first, checkout second."""

    def test_the_installed_folder_wins_over_the_checkout(self, fake_root: Path) -> None:
        installed = fake_root / "licenses"
        installed.mkdir(parents=True)
        (fake_root / "packaging" / "licenses").mkdir(parents=True)
        assert licences.licence_directory() == installed

    def test_the_checkout_answers_before_an_installer_exists(
        self, fake_root: Path
    ) -> None:
        checkout = fake_root / "packaging" / "licenses"
        checkout.mkdir(parents=True)
        assert licences.licence_directory() == checkout

    def test_a_copy_with_neither_reports_none(self, fake_root: Path) -> None:
        assert licences.licence_directory() is None


class TestLicenceDocuments:
    """Only files this copy ships may be listed, in reader order."""

    def test_third_party_texts_come_first(self, fake_root: Path) -> None:
        directory = fake_root / "licenses"
        for name in ("PROVENANCE.md", "LGPL-2.1.md", "Chromaprint-LICENSE.md"):
            _write(directory / name)
        documents = licences.licence_documents()
        assert [document.path.name for document in documents] == [
            "LGPL-2.1.md",
            "Chromaprint-LICENSE.md",
            "PROVENANCE.md",
        ]

    def test_the_suite_licence_and_notices_follow(self, fake_root: Path) -> None:
        _write(fake_root / "licenses" / "LGPL-2.1.md")
        _write(fake_root / "LICENSE")
        _write(fake_root / "THIRD_PARTY_NOTICES.md")
        documents = licences.licence_documents()
        assert [document.title for document in documents] == [
            "GNU LGPL 2.1",
            "Suite licence (GPL-3.0)",
            "Third-party notices",
        ]

    def test_unshipped_files_are_not_listed(self, fake_root: Path) -> None:
        _write(fake_root / "licenses" / "LGPL-2.1.md")
        assert len(licences.licence_documents()) == 1

    def test_an_installation_with_no_texts_lists_nothing(self, fake_root: Path) -> None:
        assert licences.licence_documents() == ()
        assert "No licence texts" in licences.missing_message()


class TestReadLicence:
    """The text is shown as it is; a bad byte must not hide the licence."""

    def test_text_is_read_verbatim(self, fake_root: Path) -> None:
        path = _write(fake_root / "licenses" / "LGPL-2.1.md", "GNU LESSER\n")
        document = licences.LicenceDocument("GNU LGPL 2.1", path)
        assert licences.read_licence(document) == "GNU LESSER\n"

    def test_an_undecodable_byte_is_replaced_not_raised(self, fake_root: Path) -> None:
        path = fake_root / "licenses" / "LGPL-2.1.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"GNU \xff LESSER\n")
        document = licences.LicenceDocument("GNU LGPL 2.1", path)
        assert licences.read_licence(document).startswith("GNU ")

    def test_the_limit_bounds_what_a_viewer_must_render(self, fake_root: Path) -> None:
        path = _write(fake_root / "licenses" / "LGPL-2.1.md", "x" * 50)
        document = licences.LicenceDocument("GNU LGPL 2.1", path)
        assert len(licences.read_licence(document, limit=10)) == 10


class TestViewer:
    """The window a user actually gets, built on the shared hidden root."""

    def test_the_window_lists_and_renders_the_shipped_text(
        self, fake_root: Path, root: tk.Tk
    ) -> None:
        _write(fake_root / "licenses" / "LGPL-2.1.md", "GNU LESSER GENERAL PUBLIC\n")
        _write(fake_root / "LICENSE", "GPL-3.0\n")

        window = ui_helpers.open_licence_viewer(root)
        try:
            listboxes = [w for w in _walk(window) if isinstance(w, tk.Listbox)]
            texts = [w for w in _walk(window) if isinstance(w, tk.Text)]
            assert listboxes, "the viewer has no document list"
            assert listboxes[0].size() == 2, "the list does not match what ships"
            assert texts, "the viewer has no text pane"
            assert "GNU LESSER GENERAL PUBLIC" in texts[0].get("1.0", "end")
        finally:
            window.destroy()

    def test_an_installation_without_texts_says_so(
        self, fake_root: Path, root: tk.Tk
    ) -> None:
        window = ui_helpers.open_licence_viewer(root)
        try:
            texts = [w for w in _walk(window) if isinstance(w, tk.Text)]
            assert texts
            assert "No licence texts" in texts[0].get("1.0", "end")
            assert texts[0].cget("state") == "disabled"
        finally:
            window.destroy()

    def test_the_viewer_is_read_only(self, fake_root: Path, root: tk.Tk) -> None:
        _write(fake_root / "licenses" / "LGPL-2.1.md", "GNU LESSER\n")
        window = ui_helpers.open_licence_viewer(root)
        try:
            texts = [w for w in _walk(window) if isinstance(w, tk.Text)]
            assert texts and texts[0].cget("state") == "disabled"
        finally:
            window.destroy()


class TestTextModeHeader:
    """The header says where each text came from, not one folder for all five.

    Two of the documents (the suite licence and the third-party notices) live at
    the suite root, so a header reading "N licence text(s) in <folder>" named a
    folder that holds only some of them - a claim a reader can check and
    disbelieve.
    """

    @staticmethod
    def _ship_third_party(root: Path) -> Path:
        directory = root / "packaging" / "licenses"
        for name in ("LGPL-2.1.md", "Chromaprint-LICENSE.md", "PROVENANCE.md"):
            _write(directory / name)
        return directory

    @staticmethod
    def _header() -> str:
        from click.testing import CliRunner

        from audio_suite_shared.cli_app import cli

        result = CliRunner().invoke(cli, ["licences"])
        assert result.exit_code == 0, result.output
        lines = result.output.splitlines()
        assert lines, "text mode printed nothing"
        return lines[0]

    def test_a_mixed_copy_names_both_places(self, fake_root: Path) -> None:
        directory = self._ship_third_party(fake_root)
        _write(fake_root / "LICENSE")
        _write(fake_root / "THIRD_PARTY_NOTICES.md")

        header = self._header()

        assert "5 licence text(s)" in header, header
        assert f"3 third-party in {directory}" in header, header
        assert "2 with the suite" in header, header

    def test_third_party_texts_only_keep_the_folder(self, fake_root: Path) -> None:
        directory = self._ship_third_party(fake_root)

        assert self._header().strip() == f"3 licence text(s) in {directory}"

    def test_suite_texts_only_say_where_they_are(self, fake_root: Path) -> None:
        _write(fake_root / "LICENSE")
        _write(fake_root / "THIRD_PARTY_NOTICES.md")

        assert self._header().strip() == "2 licence text(s) shipped with the suite"
