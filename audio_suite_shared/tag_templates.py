"""tag_templates.py — saved field templates and copy-from-a-reference.

The Tag Editor could edit one file and import a CSV, but it could not say "make
these files carry the fields this reference file carries", and it had nowhere to
keep a field set worth reusing.  This module owns both: a :class:`TagTemplate`
is a name, a canonical-field mapping and the file it came from, stored in the
shared suite config under ``tag_templates`` so no tool-local JSON file appears;
:func:`apply_template` writes it through
:class:`~audio_suite_shared.tag_field_engine.TagFieldEngine`, so the one field
table and the one save path stay the only implementations.

Field names are validated by :func:`~audio_suite_shared.tag_field_engine.rule_for`,
never by a second list here: a template cannot name a field the engine does not
know, and a container that cannot carry one is refused with the engine's own
message instead of being silently dropped.  Every write of one template to many
files runs inside a single undo batch, so Undo Tag Edits reverts the whole apply.

Changed in 2.6.0: new — plan F-E7 (tag copy/template).
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from . import suite_config
from .batch_undo import active_batch, get_active_batch_id
from .exceptions import AudioSuiteError, AudioTagError, user_message_for
from .tag_field_engine import TagFieldEngine, rule_for
from .tag_handler_factory import TagHandlerFactory

#: Shared-config key the templates live under (``audio_suite_config.json``).
CONFIG_KEY = "tag_templates"
#: Tool label the undo batch records, so the Undo window names the run.
TOOL_NAME = "tag_editor"
#: Operation label the undo snapshot records.
SNAPSHOT_OPERATION = "tag_template"


@dataclass(frozen=True)
class TagTemplate:
    """A reusable set of canonical tag fields.

    Attributes:
        name: The template's name; unique within the shared config.
        fields: Canonical field name -> value.  Absent fields are not touched.
        source: The file the values were copied from, for the report.
    """

    name: str
    fields: dict[str, str]
    source: str = ""

    def to_payload(self) -> dict[str, Any]:
        """Return the JSON-serialisable form stored in the shared config."""
        return {"fields": dict(self.fields), "source": self.source}

    @classmethod
    def from_payload(cls, name: str, payload: Mapping[str, Any]) -> TagTemplate:
        """Rebuild a template from its stored payload.

        Args:
            name: The key the payload was stored under.
            payload: A mapping with ``fields`` and optionally ``source``.

        Returns:
            The template.  Non-string values are stringified, because the
            config file can be hand-edited.
        """
        raw_fields = payload.get("fields", {})
        fields = (
            {str(key): str(value) for key, value in raw_fields.items()}
            if isinstance(raw_fields, Mapping)
            else {}
        )
        return cls(name=name, fields=fields, source=str(payload.get("source", "")))


@dataclass
class TemplateResult:
    """What one file's template apply did, or would do.

    Attributes:
        path: The file.
        changes: Canonical field -> ``(stored, template value)`` for the fields
            that differ.  Empty when the file already matches.
        error: One user-facing message when the file could not be read/written.
        written: Whether the change was persisted (always False for a dry run).
    """

    path: Path
    changes: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    error: str | None = None
    written: bool = False

    @property
    def changed(self) -> bool:
        """Whether this file has (or would have) at least one field changed."""
        return bool(self.changes)


def _raw_store() -> dict[str, Any]:
    """Return a copy of the stored template payloads."""
    stored = suite_config.load_value(CONFIG_KEY, {})
    return dict(stored) if isinstance(stored, Mapping) else {}


def load_templates() -> dict[str, TagTemplate]:
    """Return every saved template, keyed by name.

    Returns:
        The templates.  A malformed entry is skipped rather than raising, so one
        hand-edited key cannot take the whole window down.
    """
    templates: dict[str, TagTemplate] = {}
    for name, payload in _raw_store().items():
        if isinstance(payload, Mapping):
            templates[str(name)] = TagTemplate.from_payload(str(name), payload)
    return templates


def save_template(template: TagTemplate) -> None:
    """Persist *template*, replacing a saved template of the same name.

    Args:
        template: The template to store.
    """
    store = _raw_store()
    store[template.name] = template.to_payload()
    suite_config.save_value(CONFIG_KEY, store)


def delete_template(name: str) -> bool:
    """Remove a saved template.

    Args:
        name: The template's name.

    Returns:
        True when a template was removed, False when the name was not saved.
    """
    store = _raw_store()
    if name not in store:
        return False
    del store[name]
    suite_config.save_value(CONFIG_KEY, store)
    return True


def parse_fields(text: str | Iterable[str]) -> tuple[str, ...]:
    """Resolve field names, in input order, against the one field table.

    Args:
        text: A comma-separated string, or an iterable of names.

    Returns:
        Canonical field names, de-duplicated.

    Raises:
        AudioTagError: For an unknown field (naming the valid ones), or when no
            field was given.
    """
    names = (
        [part.strip() for part in text.split(",")]
        if isinstance(text, str)
        else [str(name).strip() for name in text]
    )
    resolved: list[str] = []
    for name in names:
        if not name:
            continue
        canonical = rule_for(name).name
        if canonical not in resolved:
            resolved.append(canonical)
    if not resolved:
        raise AudioTagError("A template needs at least one field.")
    return tuple(resolved)


def template_from_file(
    path: str | os.PathLike[str],
    fields: str | Iterable[str],
    *,
    name: str | None = None,
) -> TagTemplate:
    """Read *fields* from *path* and return them as a template.

    Args:
        path: The reference audio file.
        fields: Field names, comma-separated or as an iterable.
        name: Template name; defaults to the reference file's stem.

    Returns:
        The template, carrying the reference's non-empty values.

    Raises:
        AudioSuiteError: When the container has no tag writer, or when *path*
            carries none of the requested fields set.
        AudioTagError: For an unknown field name.
    """
    names = parse_fields(fields)
    engine = TagFieldEngine(path, snapshot_operation=SNAPSHOT_OPERATION)
    stored = engine.read_fields()
    for field_name in names:
        if field_name not in stored:
            raise AudioTagError(
                f"field {field_name!r} is not available for {engine.convention} files"
            )
    values: dict[str, str] = {}
    for field_name in names:
        value = stored[field_name]
        if value:
            values[field_name] = value
    if not values:
        raise AudioTagError(
            f"{Path(path).name} has none of the requested fields set: "
            f"{', '.join(names)}"
        )
    return TagTemplate(name=name or Path(path).stem, fields=values, source=str(path))


def supported_audio_files(target: str | os.PathLike[str]) -> list[Path]:
    """Expand a file or directory into the tag-writable files it names.

    Args:
        target: One audio file, or a directory to walk.

    Returns:
        The file itself when it has a handler, otherwise every handled file
        under *target* in sorted walk order.

    Raises:
        AudioSuiteError: When *target* does not exist.
    """
    path = Path(target)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise AudioTagError(f"Not a file or directory: {path}")
    found: list[Path] = []
    for current_root, dirnames, filenames in os.walk(path):
        dirnames.sort()
        for filename in sorted(filenames):
            candidate = Path(current_root) / filename
            if TagHandlerFactory.is_supported(candidate.suffix):
                found.append(candidate)
    return found


def apply_template(
    template: TagTemplate,
    targets: Iterable[str | os.PathLike[str]],
    *,
    dry_run: bool = False,
) -> list[TemplateResult]:
    """Write *template*'s fields to every target, under one undo batch.

    The diff is computed before anything is written, so a dry run reports the
    same changes a live run would make and records no undo snapshot.  One file's
    failure is that file's error, never the batch's.

    Args:
        template: The template to apply.
        targets: Files to apply it to.
        dry_run: When True, report the diff and persist nothing.

    Returns:
        One result per target, in input order.
    """
    results: list[TemplateResult] = []
    pending: list[tuple[TemplateResult, TagFieldEngine]] = []
    for target in targets:
        path = Path(target)
        try:
            engine = TagFieldEngine(path, snapshot_operation=SNAPSHOT_OPERATION)
            result = TemplateResult(path=path, changes=engine.diff(template.fields))
        except AudioSuiteError as exc:
            results.append(TemplateResult(path=path, error=user_message_for(exc)))
            continue
        results.append(result)
        if result.changes and not dry_run:
            pending.append((result, engine))

    if pending:
        if get_active_batch_id() is not None:
            # A caller (the Tag Editor, or a test) already opened the batch the
            # whole run belongs to; opening a second one would orphan its id.
            _write_pending(pending, template)
        else:
            with active_batch(TOOL_NAME, SNAPSHOT_OPERATION):
                _write_pending(pending, template)
    return results


def _write_pending(
    pending: list[tuple[TemplateResult, TagFieldEngine]], template: TagTemplate
) -> None:
    """Write every planned file, recording one file's failure on its result."""
    for result, engine in pending:
        try:
            engine.write_fields(template.fields)
        except AudioSuiteError as exc:
            result.error = user_message_for(exc)
            continue
        result.written = True


def copy_fields(
    reference: str | os.PathLike[str],
    targets: Iterable[str | os.PathLike[str]],
    fields: str | Iterable[str],
    *,
    dry_run: bool = False,
) -> tuple[TagTemplate, list[TemplateResult]]:
    """Copy *fields* from *reference* onto *targets*.

    Args:
        reference: The file whose values are copied.
        targets: Files to write.
        fields: Field names, comma-separated or as an iterable.
        dry_run: When True, report the diff and persist nothing.

    Returns:
        The template built from *reference*, and one result per target.

    Raises:
        AudioSuiteError: When the reference cannot supply the fields (see
            :func:`template_from_file`).
        AudioTagError: For an unknown field name.
    """
    template = template_from_file(reference, fields)
    return template, apply_template(template, targets, dry_run=dry_run)


def result_line(result: TemplateResult, *, is_dry_run: bool) -> str:
    """Return one run-report line for a template apply.

    Args:
        result: The file's outcome.
        is_dry_run: Whether the run may write.

    Returns:
        A ``[FAILED]``, ``[UNCHANGED]``, ``[WOULD WRITE]`` or ``[WRITTEN]``
        line naming every field and its before/after value.
    """
    if result.error is not None:
        return f"[FAILED]    {result.path.name}: {result.error}\n"
    if not result.changes:
        return f"[UNCHANGED] {result.path.name}: already matches the template\n"
    verb = "WOULD WRITE" if is_dry_run else "WRITTEN"
    detail = "; ".join(
        f"{name} {old!r} -> {new!r}" for name, (old, new) in result.changes.items()
    )
    return f"[{verb}] {result.path.name}: {detail}\n"


def with_name(template: TagTemplate, name: str) -> TagTemplate:
    """Return *template* under a new name.

    Args:
        template: The template to rename.
        name: The new name.

    Returns:
        A copy with the new name.
    """
    cleaned = name.strip()
    if not cleaned:
        raise AudioTagError("A template needs a name.")
    return replace(template, name=cleaned)
