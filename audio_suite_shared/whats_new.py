"""whats_new.py - the in-app "What's New" panel for the running suite version.

After an update the suite should say what changed, in the application the user
just opened, instead of leaving them to find ``CHANGELOG.md`` on disk.  This
module reads the release sections the user has not seen and renders them in a
scrollable Toplevel.

Why the changelog is the source of truth
----------------------------------------

``CHANGELOG.md`` is already the released record: the 1.3.0 cut promotes the
``[Unreleased]`` section into it, and the release command refuses to cut a
version with no entries.  Keeping a second, hand-maintained "what's new" list
would drift from it immediately, so the panel only ever renders a section the
changelog actually contains.  A section that cannot be found produces no panel
at all rather than an empty one - an install without a changelog (or a version
that was built without its notes) simply has nothing to say.

A skipped update must not lose its notes
----------------------------------------

Showing only the running version's section loses every release a user skipped:
someone who jumps 1.2.0 -> 1.4.0 would never see what 1.3.0 changed.  The panel
therefore renders *every* released section newer than the recorded
``last_seen_version`` up to and including the running version, newest first,
each under its own version heading.  Two cases deliberately fall back to the
running version alone: a first-ever launch (no previous version recorded, so
showing the whole history would be noise) and a recorded version at or above
the running one (nothing is pending - the Help menu still needs something to
show).  Versions are compared numerically from the changelog headings; a
heading that is not a number (``[Unreleased]``) never counts as pending.

When it is offered
------------------

``offer_pending()`` shows the panel once per version, suite-wide, tracked in
the shared ``audio_suite_config.json`` under ``last_seen_version`` (the shared
config pattern, not a tool-local file).  Closing the panel records the
*running* version, which is what makes the whole pending range seen at once.
It deliberately stays out of the way of unattended work:

* a launch with command-line arguments is a Master Driver launch - the batch
  runs tools itself, and a modal-ish panel no one clicks would block it;
* ``AUDIOSUITE_WHATS_NEW=0`` disables the automatic panel (the Help menu entry
  still opens it on request);
* the seen version is written when the panel is closed, so a run that is
  killed with the panel open simply offers it again.

Changed in 1.3.0: new module - the in-app release-notes panel and its
pending-version rule.  The panel covers every release since the last seen
version, not just the running one, so a skipped update still reports itself.

Changed in 1.4.1: a section underline one character short and a ``##``
literal carrying a trailing space are corrected, so Sphinx's parser accepts
the module and the API reference renders it (backlog P2).
"""

from __future__ import annotations

import logging
import os
import re
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from . import styles, suite_config
from .cli_helpers import was_launched_from_driver
from .project_version import declared_version

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Shared-config key recording the release version already shown to the user.
SEEN_VERSION_KEY = "last_seen_version"

#: Setting this to 0/off disables the automatic panel for unattended launches.
DISABLE_ENV = "AUDIOSUITE_WHATS_NEW"

#: Subtitle above the rendered release body.
PANEL_SUBTITLE = "What's new in this release"

#: Subtitle used when the panel covers more than one release.
MULTI_SUBTITLE = "What's new since your last update"

#: ASCII-safe bullet glyph (written as an escape so the source stays ASCII).
BULLET_GLYPH = "\u2022"

_HEADING_PREFIX = "### "
_BULLET_PREFIXES: tuple[str, str] = ("- ", "* ")
_SECTION_HEADING = re.compile(r"^## \[([^\]]+)\][^\n]*$", re.MULTILINE)
_NUMERIC_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)")
_LEAD_BOLD = re.compile(r"\*\*(.+?)\*\*\s*(.*)")
_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@dataclass(frozen=True)
class Block:
    """One rendered paragraph of a release section.

    Attributes:
        style: ``"version"`` (a release label when several are shown),
            ``"heading"``, ``"bullet"`` or ``"paragraph"``.
        text: The block's text, with Markdown markers removed.
        lead: A bold lead-in run (``**Title.**``), rendered separately so a
            scanning reader gets a heading-like anchor per entry.
    """

    style: str
    text: str
    lead: str = ""


@dataclass(frozen=True)
class ReleaseNotes:
    """The notes for one released version.

    Attributes:
        version: The running version the panel is titled with, e.g.
            ``"1.3.0"``.
        blocks: The parsed blocks of every covered release, newest first,
            each preceded by a ``"version"`` block when more than one
            release is shown.
        versions: Every release the blocks cover, newest first.  Empty only
            for a hand-built instance; :func:`release_notes` and
            :func:`notes_since` always populate it.
    """

    version: str
    blocks: list[Block]
    versions: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Changelog parsing (Tk-free, so it is testable without a display)
# ---------------------------------------------------------------------------


def find_changelog(start: Path | None = None) -> Path | None:
    """Return the nearest ``CHANGELOG.md`` at or above *start*.

    Args:
        start: Directory to search upwards from.  Defaults to the directory
            containing this module, which walks ``audio_suite_shared/`` →
            the repository root.

    Returns:
        The changelog path, or ``None`` for an install that does not ship one.
    """
    base = (start or Path(__file__).resolve().parent).resolve()
    for directory in (base, *base.parents):
        candidate = directory / "CHANGELOG.md"
        if candidate.is_file():
            return candidate
    return None


def section_body(changelog_text: str, version: str) -> str | None:
    """Return the body of the ``## [<version>]`` section.

    The section ends at the next ``##`` heading, so the body can never run on
    into a later release.

    Args:
        changelog_text: The full ``CHANGELOG.md`` source.
        version: The version whose notes are wanted.

    Returns:
        The section body with the heading removed, or ``None`` when the
        version has no section or its body is blank.
    """
    heading = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*$", changelog_text, re.MULTILINE
    )
    if heading is None:
        return None
    rest = changelog_text[heading.end() :]
    following = re.search(r"^## ", rest, re.MULTILINE)
    body = rest[: following.start()] if following is not None else rest
    body = body.strip()
    return body or None


def version_key(text: str) -> tuple[int, ...] | None:
    """Return a sortable key for a version string, or ``None`` if it has none.

    Changelog headings are ``1.3.0``-style, but a heading may carry a suffix
    (``1.3.0-rc1``) and ``[Unreleased]`` carries no number at all.  The key is
    the leading dotted number run, so a suffixed release sorts with its base
    version and an unreleased section never counts as a release.

    Args:
        text: A version string from a changelog heading.

    Returns:
        The numeric components, e.g. ``(1, 3, 0)``; ``None`` when the text
        does not start with a number.
    """
    match = _NUMERIC_VERSION.match(text.strip())
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def released_versions(changelog_text: str) -> list[str]:
    """Return every ``## [<version>]`` heading's version in document order.

    Args:
        changelog_text: The full ``CHANGELOG.md`` source.

    Returns:
        The heading texts in the order they appear, which for a Keep a
        Changelog file is newest first.  ``Unreleased`` is included here;
        callers that need actual releases filter on :func:`version_key`.
    """
    return [match.group(1) for match in _SECTION_HEADING.finditer(changelog_text)]


def _pending_versions(changelog_text: str, running: str, seen: str) -> list[str]:
    """Return the versions to show, newest first.

    Args:
        changelog_text: The full ``CHANGELOG.md`` source.
        running: The running version.
        seen: The version whose notes were shown last, or an empty string.

    Returns:
        Every released version *newer* than *seen* and no newer than
        *running*, newest first.  Falls back to ``[running]`` when there is no
        comparable ``seen`` (first launch, unparseable version) or nothing is
        pending (already seen, or a downgrade).
    """
    running_key = version_key(running)
    seen_key = version_key(seen) if seen else None
    if running_key is None or seen_key is None or seen_key >= running_key:
        return [running]

    versions = [
        version
        for version in released_versions(changelog_text)
        if (key := version_key(version)) is not None and seen_key < key <= running_key
    ]
    if not versions:
        return [running]
    versions.sort(key=lambda version: version_key(version) or (), reverse=True)
    return versions


def _clean_inline(text: str) -> str:
    """Strip inline Markdown that a plain text widget cannot render."""
    text = _LINK.sub(lambda match: match.group(1), text)
    text = _INLINE_BOLD.sub(lambda match: match.group(1), text)
    return text.replace("`", "").strip()


def parse_blocks(body: str) -> list[Block]:
    """Parse a release body into heading, bullet and paragraph blocks.

    Changelog entries are wrapped across indented continuation lines; those
    lines are joined back into the block they continue, so a rendered entry
    reads as one sentence rather than one fragment per source line.

    Args:
        body: A section body as returned by :func:`section_body`.

    Returns:
        The blocks in document order.
    """
    raw_blocks: list[list[str]] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            continue
        if raw_line[:1].isspace() and raw_blocks:
            raw_blocks[-1][2] = f"{raw_blocks[-1][2]} {stripped}".strip()
            continue
        if stripped.startswith(_HEADING_PREFIX):
            raw_blocks.append(["heading", "", stripped[len(_HEADING_PREFIX) :]])
        elif stripped.startswith(_BULLET_PREFIXES):
            content = stripped[len("- ") :]
            lead_match = _LEAD_BOLD.match(content)
            if lead_match is not None:
                raw_blocks.append(["bullet", lead_match.group(1), lead_match.group(2)])
            else:
                raw_blocks.append(["bullet", "", content])
        elif raw_blocks and raw_blocks[-1][0] == "paragraph":
            # Wrapped prose continues the paragraph above, indented or not.
            raw_blocks[-1][2] = f"{raw_blocks[-1][2]} {stripped}".strip()
        else:
            raw_blocks.append(["paragraph", "", stripped])

    return [
        Block(style, _clean_inline(text), _clean_inline(lead))
        for style, lead, text in raw_blocks
    ]


def release_notes(version: str, changelog: Path | None = None) -> ReleaseNotes | None:
    """Return *version*'s notes, or ``None`` when they are not available.

    Args:
        version: The version whose section is wanted.
        changelog: Changelog path; discovered when omitted.

    Returns:
        The parsed notes, or ``None`` when there is no changelog, no section
        for *version*, or the section is blank.
    """
    path = changelog or find_changelog()
    if path is None:
        logger.debug("no CHANGELOG.md found; release notes unavailable")
        return None
    body = section_body(path.read_text(encoding="utf-8"), version)
    if body is None:
        logger.debug("CHANGELOG.md has no release section for %s", version)
        return None
    return ReleaseNotes(version, parse_blocks(body), (version,))


def notes_since(
    running: str, seen: str = "", changelog: Path | None = None
) -> ReleaseNotes | None:
    """Return every release's notes since *seen*, newest first.

    Args:
        running: The running version; its section must exist, otherwise the
            panel has nothing to say and ``None`` is returned.
        seen: The version whose notes were shown last.  Empty (a first
            launch) or unparseable values fall back to *running* alone.
        changelog: Changelog path; discovered when omitted.

    Returns:
        The combined notes, or ``None`` when there is no changelog, no section
        for *running*, or every pending section is blank.  A blank
        intermediate section is skipped rather than rendered as a bare
        version heading.
    """
    path = changelog or find_changelog()
    if path is None:
        logger.debug("no CHANGELOG.md found; release notes unavailable")
        return None
    text = path.read_text(encoding="utf-8")
    if section_body(text, running) is None:
        logger.debug("CHANGELOG.md has no release section for %s", running)
        return None

    sections: list[tuple[str, list[Block]]] = []
    for version in _pending_versions(text, running, seen):
        body = section_body(text, version)
        if body is None:
            continue
        blocks = parse_blocks(body)
        if blocks:
            sections.append((version, blocks))
    if not sections:
        return None

    combined: list[Block] = []
    for version, blocks in sections:
        if len(sections) > 1:
            combined.append(Block("version", version))
        combined.extend(blocks)
    return ReleaseNotes(running, combined, tuple(v for v, _ in sections))


# ---------------------------------------------------------------------------
# Deciding whether to offer the panel
# ---------------------------------------------------------------------------


def _disabled_by_environment() -> bool:
    """Whether the automatic panel is switched off for this launch."""
    value = os.environ.get(DISABLE_ENV, "").strip().lower()
    return value in {"0", "false", "no", "off"}


def pending_notes(
    version: str | None = None,
    *,
    argv: list[str] | None = None,
    changelog: Path | None = None,
    force: bool = False,
) -> ReleaseNotes | None:
    """Return the notes that still need showing, if any.

    The returned notes cover every release newer than the recorded
    ``last_seen_version`` (see :func:`notes_since`), so a skipped update still
    reports what it changed.

    Args:
        version: The running version; read from ``pyproject.toml`` when
            omitted.
        argv: Program arguments used to detect a Master Driver launch.
            Defaults to ``sys.argv`` so production needs no argument.
        changelog: Changelog path; discovered when omitted.
        force: Show even when this version was already seen and even for a
            driver launch (the Help menu asks for it explicitly).  The
            recorded version is still read, so a forced open while notes are
            pending shows the whole pending range, and a forced open after
            they were seen shows the running version again.

    Returns:
        The notes to show, or ``None`` when the panel should stay closed.
    """
    running = version or declared_version()
    seen = str(suite_config.load_value(SEEN_VERSION_KEY, ""))
    if not force:
        if _disabled_by_environment():
            return None
        if was_launched_from_driver(argv):
            logger.debug("driver launch; not offering the release notes panel")
            return None
        if seen == running:
            return None
    return notes_since(running, seen, changelog)


def mark_seen(version: str) -> None:
    """Record that *version*'s notes have been shown."""
    suite_config.save_value(SEEN_VERSION_KEY, version)


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------


def show(
    parent: tk.Tk | tk.Toplevel,
    notes: ReleaseNotes,
    *,
    on_close: object = None,
) -> tk.Toplevel:
    """Render *notes* in a scrollable Toplevel.

    When *notes* covers several releases, each is introduced by its version
    heading so the user can tell which change came from which update.

    The panel is intentionally not modal: it is informational, and a grab
    that outlives the user's attention would block the tool behind it.

    Args:
        parent: The window the panel belongs to.
        notes: The parsed notes to render.
        on_close: Optional callable invoked instead of recording the version
            as seen when the panel closes.

    Returns:
        The created Toplevel.
    """
    top = tk.Toplevel(parent)
    top.title(f"What's New in AudioSuite {notes.version}")
    top.configure(bg=styles.BG_APP)
    top.minsize(520, 360)
    top.transient(parent)

    frame = ttk.Frame(top, padding=(16, 12, 16, 12))
    frame.pack(fill="both", expand=True)

    tk.Label(
        frame,
        text=f"AudioSuite {notes.version}",
        font=styles.FONT_TITLE,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        frame,
        text=PANEL_SUBTITLE if len(notes.versions) <= 1 else MULTI_SUBTITLE,
        font=styles.FONT_LABEL,
        bg=styles.BG_APP,
        fg=styles.FG_SUB,
        anchor="w",
    ).pack(fill="x", pady=(0, 8))

    text_frame = ttk.Frame(frame)
    text_frame.pack(fill="both", expand=True)
    body = tk.Text(
        text_frame,
        wrap="word",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        relief="flat",
        borderwidth=0,
        padx=6,
        pady=6,
        height=18,
        width=76,
    )
    scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=body.yview)
    body.configure(yscrollcommand=scrollbar.set)
    body.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    body.tag_configure("version", font=styles.FONT_TITLE, spacing1=14, spacing3=6)
    body.tag_configure("heading", font=styles.FONT_LABEL_B, spacing1=10, spacing3=4)
    body.tag_configure("bullet", lmargin1=18, lmargin2=32, spacing1=4)
    body.tag_configure("lead", font=styles.FONT_BODY_B)
    body.tag_configure("paragraph", spacing1=4)

    for block in notes.blocks:
        if block.style == "version":
            body.insert("end", f"Version {block.text}\n", "version")
        elif block.style == "heading":
            body.insert("end", f"{block.text}\n", "heading")
        elif block.style == "bullet":
            body.insert("end", f"{BULLET_GLYPH}  ")
            if block.lead:
                body.insert("end", f"{block.lead} ", "lead")
            body.insert("end", f"{block.text}\n", "bullet")
        else:
            body.insert("end", f"{block.text}\n\n", "paragraph")
    body.configure(state="disabled")

    def close() -> None:
        """Dismiss the panel and remember that it was shown."""
        if callable(on_close):
            on_close()
        else:
            mark_seen(notes.version)
        top.destroy()

    ttk.Button(frame, text="Close", command=close).pack(anchor="e", pady=(10, 0))
    top.protocol("WM_DELETE_WINDOW", close)
    top.lift()
    return top


def offer_pending(
    parent: tk.Tk | tk.Toplevel,
    *,
    version: str | None = None,
    argv: list[str] | None = None,
    changelog: Path | None = None,
    force: bool = False,
    on_close: object = None,
) -> tk.Toplevel | None:
    """Show the panel when this version has notes the user has not seen.

    Args:
        parent: The window the panel belongs to.
        version: The running version (defaults to the declared one).
        argv: Program arguments for the driver-launch check.
        changelog: Changelog path; discovered when omitted.
        force: Show even when already seen or driver-launched.
        on_close: Optional close callback instead of recording the version.

    Returns:
        The panel, or ``None`` when there was nothing to show.
    """
    notes = pending_notes(version, argv=argv, changelog=changelog, force=force)
    if notes is None:
        return None
    return show(parent, notes, on_close=on_close)
