"""tag_processor.py — the example plugin's tag-processor contribution.

``audiosuite tag-update`` runs every enabled tag processor once per file, after
its own slash-rule rewrite and before it records the file's result.  A
processor receives the file path, the run's dry-run flag, and — because this
one declares the parameter — a
:class:`~audio_suite_shared.plugin_system.PluginContext` that reads and writes
tags through the suite's own tag layer.

The processor here collapses repeated whitespace in the ``comment`` field.  It
is deliberately boring: it changes one field, it can say what it changed, and it
writes nothing in a dry run, which is the whole contract.

Changed in 2.1.0: new module — the example tag processor (Item 7.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from audio_suite_shared.plugin_system import PluginContext, TagProcessorOutcome


def apply(
    path: Path, dry_run: bool, *, context: "PluginContext"
) -> "TagProcessorOutcome":
    """Collapse runs of whitespace in the file's comment tag.

    Args:
        path: The audio file being processed.
        dry_run: True when the run must not persist the rewrite.
        context: Suite services: tag reading, tag writing and a logger.

    Returns:
        Whether a rewrite is due (or was made) and a line for the run log.
    """
    from audio_suite_shared.plugin_system import TagProcessorOutcome

    tags = context.read_tags(path)
    comment = tags.get("comment")
    if not comment:
        return TagProcessorOutcome(changed=False)
    collapsed = " ".join(comment.split())
    if collapsed == comment:
        return TagProcessorOutcome(changed=False)
    if not dry_run:
        context.write_tag(path, "comment", collapsed)
    return TagProcessorOutcome(
        changed=True,
        message=(
            f"comment whitespace collapsed ({len(comment)} -> {len(collapsed)} chars)"
        ),
    )
