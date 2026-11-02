"""The three dispositions a duplicate scan can apply to a duplicate.

Quarantine stays the default.  Delete and the ASX-stub replacement are opt-in
per run because they remove the file from the library; both go to the operating
system's Recycle Bin, never to a permanent unlink.

The value is a plain string in :class:`~duplicate_finder.core.models.ScanSettings`
so the CLI, the GUI preset and the driver argv all carry one token.  It is
validated once, through :func:`normalize`, at every entry point.

Changed in 2.4.0: new module (PLAN_duplicate_disposition_2026-11-02.md DD-2).
"""

from __future__ import annotations

from enum import StrEnum


class Disposition(StrEnum):
    """What a live run does with every non-keeper.

    Attributes:
        QUARANTINE: Move the duplicate into the quarantine folder (default).
        DELETE: Move the duplicate to the operating system's Recycle Bin.
        ASX_STUB: Write a metadata-bearing ASX stub beside the duplicate, then
            move the duplicate to the Recycle Bin.
    """

    QUARANTINE = "quarantine"
    DELETE = "delete"
    ASX_STUB = "asx-stub"


#: The values in the order every surface lists them.
DISPOSITIONS: tuple[str, ...] = tuple(item.value for item in Disposition)

#: The value an existing run, preset or card gets when it names no disposition.
DEFAULT_DISPOSITION: str = Disposition.QUARANTINE.value

#: Human labels for the GUI and the report header.  The CLI uses the raw value.
LABELS: dict[str, str] = {
    Disposition.QUARANTINE.value: "Move to quarantine",
    Disposition.DELETE.value: "Delete (Recycle Bin)",
    Disposition.ASX_STUB.value: "Replace with an ASX stub",
}

#: Spellings a caller might hand us, mapped to the canonical value.  The CLI
#: restricts the option, so these mainly make a preset hand-edited by a user
#: forgiving rather than fatal.
_ALIASES: dict[str, str] = {
    "quarantine": Disposition.QUARANTINE.value,
    "move": Disposition.QUARANTINE.value,
    "move-to-quarantine": Disposition.QUARANTINE.value,
    "delete": Disposition.DELETE.value,
    "trash": Disposition.DELETE.value,
    "recycle": Disposition.DELETE.value,
    "asx": Disposition.ASX_STUB.value,
    "stub": Disposition.ASX_STUB.value,
    "asx-stub": Disposition.ASX_STUB.value,
    "asx_stub": Disposition.ASX_STUB.value,
}


def normalize(value: str) -> str:
    """Return the canonical disposition for *value*.

    Args:
        value: A canonical value, a label-ish alias, or an empty string.

    Returns:
        One of :data:`DISPOSITIONS`.

    Raises:
        ValueError: If *value* names no known disposition.
    """
    token = (value or "").strip().lower().replace("_", "-")
    if not token:
        return DEFAULT_DISPOSITION
    canonical = _ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(DISPOSITIONS)
        raise ValueError(f"Unknown duplicate disposition {value!r}; use {allowed}")
    return canonical


def label_for(value: str) -> str:
    """Return the human label for a disposition value.

    Args:
        value: A canonical disposition value.

    Returns:
        The label the GUI and report header show.
    """
    return LABELS[normalize(value)]


def uses_trash(value: str) -> bool:
    """Return whether *value* removes the duplicate to the Recycle Bin.

    Args:
        value: A canonical disposition value.

    Returns:
        True for ``delete`` and ``asx-stub``, False for ``quarantine``.
    """
    return normalize(value) in {Disposition.DELETE.value, Disposition.ASX_STUB.value}
