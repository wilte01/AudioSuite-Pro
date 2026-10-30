"""config.py — Action-group persistence for the filename source (F-01).

An *action group* is a named set of filename patterns plus the write mode they
were agreed with.  It is what makes a filename run repeatable: the library's
naming convention is recorded once and reloaded by name instead of retyped.

Storage follows the suite's shared-config rule (``AGENTS.md``, *Shared Config
Pattern*): the groups live in ``audio_suite_config.json`` under one key, via
``audio_suite_shared.suite_config``.  There is deliberately no tool-local JSON
file, and the feature needs none of the documented exceptions.

Reading is defensive — a hand-edited or older config must not break the GUI —
while writing is exact, so a malformed entry that was never saved by this
module cannot replace a good one.

Changed in 2.2.0: new — the action-group half of F-01.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from audio_suite_shared import suite_config

logger = logging.getLogger(__name__)

#: Single config key holding every saved group.
ACTION_GROUPS_KEY = "tag_field_updater_action_groups"


@dataclass(frozen=True)
class ActionGroup:
    """A named filename pattern set.

    Attributes:
        name: The name the group is saved under.
        patterns: Patterns in the order they are tried.
        only_fill_blanks: Whether a parsed field may overwrite an existing tag.
    """

    name: str
    patterns: tuple[str, ...]
    only_fill_blanks: bool = True

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-ready form stored in the shared config."""
        return {
            "patterns": list(self.patterns),
            "only_fill_blanks": self.only_fill_blanks,
        }


def _coerce_group(name: str, raw: Any) -> ActionGroup | None:
    """Build a group from one stored entry, or None if it is unusable.

    A stored group that cannot be read is ignored rather than guessed at: a
    half-parsed pattern list would tag files the user never described.
    """
    if not isinstance(raw, dict):
        return None
    patterns = raw.get("patterns")
    if not isinstance(patterns, list) or not patterns:
        return None
    if not all(isinstance(pattern, str) and pattern.strip() for pattern in patterns):
        return None
    fill = raw.get("only_fill_blanks", True)
    return ActionGroup(
        name=name,
        patterns=tuple(patterns),
        only_fill_blanks=bool(fill) if isinstance(fill, bool) else True,
    )


def load_action_groups() -> dict[str, ActionGroup]:
    """Read every saved group, skipping unusable entries.

    Returns:
        Group name → :class:`ActionGroup`, in stored order.  An absent or
        malformed config value yields an empty dict rather than raising, so a
        damaged config cannot stop the tool from starting.
    """
    raw = suite_config.load_value(ACTION_GROUPS_KEY, {})
    if not isinstance(raw, dict):
        logger.warning(
            "Ignoring %s: expected an object, found %s",
            ACTION_GROUPS_KEY,
            type(raw).__name__,
        )
        return {}
    groups: dict[str, ActionGroup] = {}
    for name, entry in raw.items():
        if not isinstance(name, str) or not name.strip():
            continue
        group = _coerce_group(name, entry)
        if group is None:
            logger.warning("Ignoring unusable action group %r", name)
            continue
        groups[name] = group
    return groups


def get_action_group(name: str) -> ActionGroup | None:
    """Return the saved group called *name*, or None if it is not saved.

    Args:
        name: Group name to look up.
    """
    return load_action_groups().get(name)


def save_action_group(
    name: str, patterns: tuple[str, ...] | list[str], *, only_fill_blanks: bool = True
) -> ActionGroup:
    """Store a group under *name*, replacing any group already saved there.

    Args:
        name: Group name; whitespace-trimmed.
        patterns: Patterns in the order they are tried.
        only_fill_blanks: Whether the run only fills empty fields.

    Returns:
        The group as saved.

    Raises:
        ValueError: If the name is blank or the pattern list is empty.
    """
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("an action group needs a name")
    clean_patterns = tuple(pattern.strip() for pattern in patterns if pattern.strip())
    if not clean_patterns:
        raise ValueError(
            f"action group {clean_name!r} needs at least one filename pattern"
        )

    group = ActionGroup(
        name=clean_name,
        patterns=clean_patterns,
        only_fill_blanks=only_fill_blanks,
    )
    stored = {
        existing_name: existing.to_dict()
        for existing_name, existing in load_action_groups().items()
    }
    stored[clean_name] = group.to_dict()
    suite_config.save_value(ACTION_GROUPS_KEY, stored)
    return group


def delete_action_group(name: str) -> bool:
    """Remove the group called *name*.

    Args:
        name: Group name to remove.

    Returns:
        True if a group was removed, False if it was not saved.  ``save_value``
        failures propagate — a delete that silently did nothing would leave the
        GUI listing a group the config no longer has.
    """
    groups = load_action_groups()
    if name not in groups:
        return False
    stored = {
        existing_name: existing.to_dict()
        for existing_name, existing in groups.items()
        if existing_name != name
    }
    suite_config.save_value(ACTION_GROUPS_KEY, stored)
    return True
