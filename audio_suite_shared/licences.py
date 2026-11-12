"""
licences.py — The licence texts this installation ships, and how to read them.

The installer stages ``packaging/licenses/`` into the payload as ``licenses/``
(``packaging/build_installer.ps1``), so an installed copy carries the GNU LGPL
2.1 text, Chromaprint's notice and the bundled-binary provenance record beside
the two binaries those texts cover. A source checkout keeps the same files under
``packaging/licenses/``. Help ▸ Licences reads whichever exists, so the entry
works both before and after an installer is built.

The resolution rule lives here rather than in a menu handler: the GUI, a future
CLI command and the tests ask the same question, and a second copy of "look in
``licenses/``, else ``packaging/licenses``" would be the sort of near-identical
private variant the shared-code rule exists to prevent.

Changed in 2.7.0: new module. The texts travelled with the binaries but there
was no way to reach them from the app — a user who wanted to read the licence of
something the product ships had to know the install layout and a filename.

Changed in 2.7.0: documents are resolved to real paths before they are offered.
A viewer must never list a name it cannot then open, so a file that this copy
does not ship is not listed at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import suite_paths

__all__ = [
    "CHECKOUT_LICENCE_DIR",
    "INSTALLED_LICENCE_DIR",
    "LicenceDocument",
    "licence_directory",
    "licence_documents",
    "missing_message",
    "read_licence",
]

#: Where the installer stages the third-party texts, relative to the root.
INSTALLED_LICENCE_DIR = "licenses"

#: Where a source checkout keeps the same files, relative to the root.
CHECKOUT_LICENCE_DIR = ("packaging", "licenses")

#: Third-party texts in the order a reader usually wants them: the licence
#: itself, then the notice explaining why it applies, then the provenance record
#: that says which upstream build the file is.
_THIRD_PARTY_TEXTS: tuple[tuple[str, str], ...] = (
    ("GNU LGPL 2.1", "LGPL-2.1.md"),
    ("Chromaprint licence", "Chromaprint-LICENSE.md"),
    ("Bundled binary provenance", "PROVENANCE.md"),
)

#: The suite's own licence documents, which sit at the root of the payload.
_ROOT_TEXTS: tuple[tuple[str, str], ...] = (
    ("Suite licence (GPL-3.0)", "LICENSE"),
    ("Third-party notices", "THIRD_PARTY_NOTICES.md"),
)


@dataclass(frozen=True)
class LicenceDocument:
    """One licence document a user can read from Help ▸ Licences.

    Attributes:
        title: The label shown in the viewer's list, written for a reader
            rather than for a lawyer.
        path: The file itself, already resolved — a document never needs the
            installation root again to be opened.
    """

    title: str
    path: Path


def licence_directory() -> Path | None:
    """Return the folder holding the shipped licence texts, if this copy has one.

    The installed payload is preferred over the source checkout: a staged build
    run from beside the repository should show what it actually shipped, not
    what the working tree currently holds.

    Returns:
        ``<root>/licenses`` when it exists, else ``<root>/packaging/licenses``,
        else ``None``. The caller decides what an absent folder means.
    """
    installed = suite_paths.suite_path(INSTALLED_LICENCE_DIR)
    if installed.is_dir():
        return installed
    checkout = suite_paths.suite_path(*CHECKOUT_LICENCE_DIR)
    if checkout.is_dir():
        return checkout
    return None


def licence_documents() -> tuple[LicenceDocument, ...]:
    """Return every licence document this installation actually ships.

    Only files that exist are returned: a copy built before the texts were
    staged must show what it has rather than list names it cannot open.

    Returns:
        The third-party texts in reader order, followed by the suite's own
        licence and notices. Empty when this copy ships none of them.
    """
    documents: list[LicenceDocument] = []

    directory = licence_directory()
    if directory is not None:
        for title, name in _THIRD_PARTY_TEXTS:
            path = directory / name
            if path.is_file():
                documents.append(LicenceDocument(title, path))

    for title, name in _ROOT_TEXTS:
        path = suite_paths.suite_path(name)
        if path.is_file():
            documents.append(LicenceDocument(title, path))

    return tuple(documents)


def read_licence(document: LicenceDocument, limit: int | None = None) -> str:
    """Read one licence document as text for display.

    Args:
        document: The document to read.
        limit: Optional maximum number of characters to return, so a viewer
            cannot be made slow by a file larger than it expected.

    Returns:
        The file's text. Undecodable bytes become replacement characters rather
        than raising: a licence with one bad byte is still a licence the user is
        entitled to read.

    Raises:
        OSError: If the file cannot be read — deleted after it was listed, or
            unreadable by this user.
    """
    text = document.path.read_text(encoding="utf-8", errors="replace")
    if limit is not None and len(text) > limit:
        return text[:limit]
    return text


def missing_message() -> str:
    """Return the sentence the viewer shows when this copy ships no texts.

    Returns:
        One plain sentence naming where the texts are expected, so a user of an
        older or partial installation knows what is absent rather than seeing an
        empty window.
    """
    return (
        "No licence texts were found in this installation. An installed copy "
        "keeps them in a 'licenses' folder beside the program files."
    )
