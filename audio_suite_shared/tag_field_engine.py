"""
tag_field_engine.py — one field table and one write path for audio tags.

Before this module the suite described the same tag field three times: the
per-container keys in ``tag_field_updater``'s ``TAG_MAPPINGS``, the editable-field
mappings inside each tag handler, and the transformation rules that walked a
mutagen object directly.  A field could be added in one place and stay absent in
another, which is how the Tag Field Updater and the Tag Editor drifted apart.
This module is the single table.  :data:`FIELD_RULES` names every canonical
field once, with the container key each convention uses; :class:`TagFieldEngine`
reads and writes those fields through a
:class:`~audio_suite_shared.tag_helper_base.BaseTagHandler`,
so the container work — including the FLAC in-place comment mutation that a
``.tags`` rebinding silently loses — stays in the handler that owns it.

The engine never imports mutagen.  It asks the handler for a *field key*, which
the handler interprets in its own convention:

===========  ==========================  ==============================
Convention   key form                    example
===========  ==========================  ==============================
``id3``      a frame id or ``TXXX:desc``  ``TIT1``, ``TXXX:ALBUMGENRE``
``vorbis``   a comment name               ``CONTENTGROUP``
``mp4``      an atom or freeform key      ``©grp``, ``----:TXXX:ALBUMGENRE``
``apev2``    an item name                 ``ContentGroup``
===========  ==========================  ==============================

Those keys are the ones the suite already wrote, character for character, so
migrating a consumer cannot change what lands in a file.

A container with no handler, or a container the format matrix marks
``tag_writable = False``, raises
:class:`~audio_suite_shared.exceptions.AudioFormatError`
with the ``Unsupported format:`` token every other refusal uses.  The engine
never falls back to a neighbouring container: writing APEv2 tags into a file it
guessed at is worse than refusing.

Changed in 2.4.2: new — plan WP-6 (C-M2), the one tag layer.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .audio_formats import FORMAT_MATRIX
from .batch_undo import record_tag_edit_snapshot
from .exceptions import AudioFormatError, AudioTagError
from .tag_handler_factory import TagHandlerFactory
from .tag_helper_base import EDITABLE_FIELDS

if TYPE_CHECKING:
    from .tag_helper_base import BaseTagHandler

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Tag conventions the handlers speak.  A handler declares its own through
#: :attr:`~audio_suite_shared.tag_helper_base.BaseTagHandler.convention`; the
#: engine reads that rather than mapping extensions a second time.
ID3 = "id3"
VORBIS = "vorbis"
MP4 = "mp4"
APEV2 = "apev2"
CONVENTIONS: tuple[str, ...] = (ID3, VORBIS, MP4, APEV2)

#: No value rewrite: the text is stored as given.
TRANSFORM_VERBATIM = "verbatim"
#: The genre rule: a bare ``/`` separates genres and becomes ``"; "``, while a
#: ``" / "`` separated list is left alone.
TRANSFORM_SLASH_GENRE = "slash_genre"

#: Rule kinds.  ``editable`` writes through the handler's editable-field API
#: (which owns the recording-year fallback, the MP4 ``trkn``/``disk`` pairs and
#: the comment frame); ``key`` writes one container key directly.
_EDITABLE = "editable"
_KEY = "key"


def needs_slash_genre_split(value: str | None) -> bool:
    """Report whether *value* contains a bare slash the genre rule rewrites.

    Args:
        value: A stored tag value, or ``None`` when the field is absent.

    Returns:
        True when the value carries at least one ``'/'``.
    """
    return value is not None and "/" in value


def split_slash_genre(value: str) -> str:
    """Rewrite bare slashes in a genre-style value as ``"; "``.

    Segments separated by ``" / "`` are kept intact — that form already says
    "these are separate genres" — and only bare ``'/'`` characters inside each
    segment are replaced.

    Args:
        value: The stored value.

    Returns:
        The rewritten value, or *value* unchanged when it carries no ``'/'``.
    """
    if " / " in value:
        parts = value.split(" / ")
        return " / ".join(
            part.replace("/", "; ") if "/" in part else part for part in parts
        )
    if "/" in value:
        return value.replace("/", "; ")
    return value


def apply_transform(transform: str, value: str) -> str:
    """Apply one rule's value transform.

    Args:
        transform: A :data:`TRANSFORM_VERBATIM` / :data:`TRANSFORM_SLASH_GENRE`
            token.
        value: The value to store.

    Returns:
        The value to write.

    Raises:
        AudioTagError: When *transform* is not one this module implements, so a
            typo in the table cannot silently store the raw text.
    """
    if transform == TRANSFORM_VERBATIM:
        return value
    if transform == TRANSFORM_SLASH_GENRE:
        return split_slash_genre(value)
    raise AudioTagError(f"Unknown field transform: {transform}")


@dataclass(frozen=True)
class FieldRule:
    """One canonical tag field and where each convention stores it.

    Attributes:
        name: Canonical field name.  For an editable rule this is a member of
            :data:`~audio_suite_shared.tag_helper_base.EDITABLE_FIELDS`; the
            extra names (``content_group``, ``album_genre`` …) are the suite's
            own genre bookkeeping fields.
        kind: ``"editable"`` (handler's editable-field API) or ``"key"`` (one
            container key, written verbatim).
        keys: ``(convention, container key)`` pairs.  A convention that is
            absent cannot write or read this field, and the engine says so
            rather than guessing a neighbouring key.
        transform: The value rewrite applied on write.  ``verbatim`` for the
            editable fields, whose own mappings already normalise their numbers
            and comment encodings, ``slash_genre`` for the slash rule.
        readable: Whether :meth:`TagFieldEngine.read_fields` reports it.
        writable: Whether :meth:`TagFieldEngine.write_fields` may store it.
    """

    name: str
    kind: str
    keys: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    transform: str = TRANSFORM_VERBATIM
    readable: bool = True
    writable: bool = True

    def key_for(self, convention: str) -> str:
        """Return this field's container key in *convention*.

        Args:
            convention: One of :data:`CONVENTIONS`.

        Returns:
            The container key.

        Raises:
            AudioTagError: When the field has no key for that convention.
        """
        for candidate, key in self.keys:
            if candidate == convention:
                return key
        raise AudioTagError(
            f"field {self.name!r} has no {convention} key; "
            f"known conventions: {', '.join(name for name, _ in self.keys) or 'none'}"
        )

    def supports(self, convention: str) -> bool:
        """Report whether this rule applies to *convention*.

        An editable rule applies to every convention that has an editable-field
        API, so it declares no keys; a key rule applies only where it has one.

        Args:
            convention: One of :data:`CONVENTIONS`.

        Returns:
            True when the field can be read or written in that convention.
        """
        if self.kind == _EDITABLE:
            return True
        return any(candidate == convention for candidate, _ in self.keys)


#: The nine freeform editor fields, minus ``genre``, which carries its own key
#: rule below: the slash rule rewrites the container key directly so one
#: version-aware ID3 write keeps the encoding a v2.3 file already used.
_EDITABLE_RULES: tuple[FieldRule, ...] = tuple(
    FieldRule(name=name, kind=_EDITABLE) for name in EDITABLE_FIELDS if name != "genre"
)

#: The five fields ``tag_field_updater`` rewrites, in the order its per-format
#: rules walked them: the three suite genre fields, then the content group, then
#: the standard genre.  The keys are byte-identical to the ones those rules
#: wrote, so a migrated run lands the same text in the same frames.
_KEY_RULES: tuple[FieldRule, ...] = (
    FieldRule(
        name="album_artist_genre",
        kind=_KEY,
        keys=(
            (ID3, "TXXX:ALBUMARTISTGENRE"),
            (VORBIS, "ALBUMARTISTGENRE"),
            (MP4, "----:TXXX:ALBUMARTISTGENRE"),
            (APEV2, "ALBUMARTISTGENRE"),
        ),
        transform=TRANSFORM_SLASH_GENRE,
    ),
    FieldRule(
        name="album_genre",
        kind=_KEY,
        keys=(
            (ID3, "TXXX:ALBUMGENRE"),
            (VORBIS, "ALBUMGENRE"),
            (MP4, "----:TXXX:ALBUMGENRE"),
            (APEV2, "ALBUMGENRE"),
        ),
        transform=TRANSFORM_SLASH_GENRE,
    ),
    FieldRule(
        name="artist_genre",
        kind=_KEY,
        keys=(
            (ID3, "TXXX:ARTISTGENRE"),
            (VORBIS, "ARTISTGENRE"),
            (MP4, "----:TXXX:ARTISTGENRE"),
            (APEV2, "ARTISTGENRE"),
        ),
        transform=TRANSFORM_SLASH_GENRE,
    ),
    FieldRule(
        name="content_group",
        kind=_KEY,
        keys=(
            (ID3, "TIT1"),
            (VORBIS, "CONTENTGROUP"),
            (MP4, "©grp"),
            (APEV2, "ContentGroup"),
        ),
        transform=TRANSFORM_SLASH_GENRE,
    ),
    FieldRule(
        name="genre",
        kind=_KEY,
        keys=((ID3, "TCON"), (VORBIS, "GENRE"), (MP4, "©gen"), (APEV2, "Genre")),
        transform=TRANSFORM_SLASH_GENRE,
    ),
)

#: Every canonical field, in one table.  The editable fields come first so
#: :func:`rule_for` finds them for the Tag Editor, and the key rules after them.
FIELD_RULES: tuple[FieldRule, ...] = _EDITABLE_RULES + _KEY_RULES

_RULES_BY_NAME: dict[str, FieldRule] = {rule.name: rule for rule in FIELD_RULES}


def rule_for(name: str) -> FieldRule:
    """Return the rule for one canonical field name.

    Args:
        name: Canonical field name.

    Returns:
        The :class:`FieldRule`.

    Raises:
        AudioTagError: When the field is not in :data:`FIELD_RULES`, so an
            unknown name fails here instead of being written somewhere odd.
    """
    try:
        return _RULES_BY_NAME[name]
    except KeyError:
        raise AudioTagError(
            f"Unknown tag field: {name}. Valid fields: {', '.join(_RULES_BY_NAME)}"
        ) from None


@dataclass(frozen=True)
class FieldWrite:
    """What one :meth:`TagFieldEngine.write_fields` call did.

    Attributes:
        changed: Canonical fields whose stored value differs from the requested
            one — for a dry run, the ones that *would* differ.
        keys: Container keys that were (or would be) written, for a report that
            names what the file actually carries.
        skipped: Requested fields whose transformed value already matched, so
            no write was needed.
        dry_run: Whether anything was persisted.
    """

    changed: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    dry_run: bool = False

    @property
    def updated(self) -> bool:
        """Whether this write changed (or would change) at least one field."""
        return bool(self.changed)


class TagFieldEngine:
    """Read and write canonical tag fields on one audio file.

    The engine owns no container knowledge: it resolves a field's key for the
    file's convention and hands the work to its handler, so the handler's save
    path — and the FLAC in-place mutation that keeps a restored comment block
    from being dropped — is the only one in the suite.

    Args:
        path: Path to the audio file.
        snapshot_operation: Operation label the undo snapshot records, so the
            Undo Tag Edits window names the run that made the change.

    Raises:
        AudioFormatError: When the container has no tag handler, or the format
            matrix marks it not tag-writable.
        AudioTagError: When a handler speaks a convention this module does not
            know, which would mean the table and the handler disagree.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        snapshot_operation: str = "tag_field_update",
    ) -> None:
        """Open *path* through the tag-handler factory.

        Args:
            path: Path to the audio file.
            snapshot_operation: Undo-snapshot label for writes from this engine.
        """
        self.path = os.fspath(path)
        self._snapshot_operation = snapshot_operation
        extension = os.path.splitext(self.path)[1].lower()
        capability = FORMAT_MATRIX.get(extension)
        if capability is not None and not capability.tag_writable:
            raise AudioFormatError(
                f"Unsupported format: {extension} "
                f"({capability.display_name} carries no tag writer)"
            )
        self._handler: BaseTagHandler = TagHandlerFactory.get_handler(self.path)
        self.convention: str = self._handler.convention
        if self.convention not in CONVENTIONS:
            raise AudioTagError(
                f"{type(self._handler).__name__} declares no known tag convention "
                f"({self.convention!r}); expected one of {', '.join(CONVENTIONS)}"
            )
        self._rules: tuple[FieldRule, ...] = tuple(
            rule for rule in FIELD_RULES if rule.supports(self.convention)
        )

    @property
    def rules(self) -> tuple[FieldRule, ...]:
        """Return the rules that apply to this file's convention."""
        return self._rules

    def has_tags(self) -> bool:
        """Report whether the file carries a tag container at all.

        Returns:
            True when the handler loaded a tag object.  Callers use it to
            distinguish "nothing to rewrite" from a container that is simply
            absent, which the ID3-backed formats report as a skip.
        """
        return self._handler.get_raw_tags() is not None

    def read_fields(self) -> dict[str, str | None]:
        """Read every canonical field for this file's convention.

        Returns:
            Field name → stored value, or ``None`` when absent.
        """
        editable = self._handler.read_editable_tags()
        values: dict[str, str | None] = {}
        for rule in self._rules:
            if not rule.readable:
                continue
            if rule.kind == _EDITABLE:
                values[rule.name] = editable.get(rule.name)
            else:
                values[rule.name] = self._handler.read_field_key(
                    rule.key_for(self.convention)
                )
        return values

    def diff(self, values: Mapping[str, str]) -> dict[str, tuple[str | None, str]]:
        """Return the requested fields whose stored value would change.

        Args:
            values: Field name → value to store.  Each value is transformed by
                its rule before comparison.

        Returns:
            Field name → ``(stored, transformed)`` for the fields that differ.

        Raises:
            AudioTagError: For an unknown field or a field this convention
                cannot write.
        """
        stored = self.read_fields()
        changes: dict[str, tuple[str | None, str]] = {}
        for name, raw in values.items():
            rule = self._rule(name)
            candidate = apply_transform(rule.transform, raw)
            current = stored.get(name)
            if current != candidate:
                changes[name] = (current, candidate)
        return changes

    def raw_updates(self, values: Mapping[str, str]) -> dict[str, str]:
        """Return the container keys and transformed values a write would use.

        This is the report's view: it names the frames/comments/atoms the file
        will carry, which is what a user sees in the run log, rather than the
        canonical names the engine works in.

        Args:
            values: Field name → value to store.

        Returns:
            Container key → value for every ``key`` rule in *values*; editable
            rules are omitted because their key is the handler's business.

        Raises:
            AudioTagError: For an unknown field.
        """
        updates: dict[str, str] = {}
        for name, raw in values.items():
            rule = self._rule(name)
            if rule.kind != _KEY:
                continue
            updates[rule.key_for(self.convention)] = apply_transform(
                rule.transform, raw
            )
        return updates

    def write_fields(
        self, values: Mapping[str, str], *, dry_run: bool = False
    ) -> FieldWrite:
        """Apply *values* to the file, one save, gated on *dry_run*.

        The gate lives here, at the write site: a dry run computes the same
        diff, records no undo snapshot and never calls ``save()``, so the file's
        bytes and mtime are untouched.

        Args:
            values: Field name → value to store.
            dry_run: When True, report the change and persist nothing.

        Returns:
            The outcome, in canonical names and container keys.

        Raises:
            AudioTagError: For an unknown field, a field this convention cannot
                write, or a field marked read-only.
        """
        stored = self.read_fields()
        changed: list[str] = []
        keys: list[str] = []
        skipped: list[str] = []
        pending: list[tuple[str, str]] = []

        for name, raw in values.items():
            rule = self._rule(name)
            if not rule.writable:
                raise AudioTagError(f"Tag field is read-only: {name}")
            candidate = apply_transform(rule.transform, raw)
            if stored.get(name) == candidate:
                skipped.append(name)
                continue
            changed.append(name)
            if rule.kind == _EDITABLE:
                if not dry_run:
                    self._handler.write_editable_tag(name, candidate)
            else:
                key = rule.key_for(self.convention)
                keys.append(key)
                pending.append((key, candidate))

        if pending:
            if dry_run:
                logger.info(
                    "Dry run: %s would set %s",
                    os.path.basename(self.path),
                    ", ".join(key for key, _ in pending),
                )
            else:
                record_tag_edit_snapshot(self.path, self._snapshot_operation)
                for key, candidate in pending:
                    self._handler.set_field_key(key, candidate)
                self._handler.save()
                logger.info(
                    "Set %s in %s",
                    ", ".join(key for key, _ in pending),
                    os.path.basename(self.path),
                )

        return FieldWrite(
            changed=tuple(changed),
            keys=tuple(keys),
            skipped=tuple(skipped),
            dry_run=dry_run,
        )

    def delete_fields(self, names: Sequence[str] | None = None) -> tuple[str, ...]:
        """Remove *names* (or every field this convention carries) from the file.

        Args:
            names: Canonical field names; ``None`` removes every rule's field.

        Returns:
            The canonical fields that were removed, in table order.

        Raises:
            AudioTagError: For an unknown field or a read-only field.
        """
        targets = (
            list(self._rules) if names is None else [self._rule(name) for name in names]
        )
        removed: list[str] = []
        key_targets: list[str] = []
        for rule in targets:
            if not rule.writable:
                raise AudioTagError(f"Tag field is read-only: {rule.name}")
            if rule.kind == _EDITABLE:
                self._handler.write_editable_tag(rule.name, None)
            else:
                key_targets.append(rule.key_for(self.convention))
            removed.append(rule.name)
        if key_targets:
            record_tag_edit_snapshot(self.path, self._snapshot_operation)
            for key in key_targets:
                self._handler.set_field_key(key, None)
            self._handler.save()
        return tuple(removed)

    def _rule(self, name: str) -> FieldRule:
        """Return *name*'s rule, rejecting a field this convention cannot carry.

        Args:
            name: Canonical field name.

        Returns:
            The rule.

        Raises:
            AudioTagError: When the field is unknown, or has no key for this
                convention (a field a container genuinely cannot hold).
        """
        rule = rule_for(name)
        if not rule.supports(self.convention):
            raise AudioTagError(
                f"field {name!r} is not available for {self.convention} files"
            )
        return rule
