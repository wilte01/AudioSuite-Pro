"""Shared ASX stub schema for the Duplicate Finder and ASX Playlist Extractor.

A *stub* is a normal ASX 3.0 playlist whose ``<REF>`` points at the copy that
was kept, plus a versioned, machine-readable block of ``<PARAM>`` elements that
describes the file the stub replaced.  Any ASX-aware player can still play the
stub; the extractor uses the params to recreate the original file's name and
tags from the kept audio.

The schema lives here, not in either tool, because the writer (Duplicate
Finder) and the reader (ASX Playlist Extractor) must not drift: the suite may
not ship a stub that the installed extractor cannot restore.  This module has
no Tk and imports neither tool.

Schema version 1
----------------
- ``AudioSuite:stub-version`` is the discriminator.  A playlist without it is a
  plain ASX and is left to the existing extraction path.
- ``AudioSuite:original-name`` / ``AudioSuite:keeper-name`` are the two file
  names, for the report and for a human reading the stub.
- The nine :data:`~audio_suite_shared.tag_helper_base.EDITABLE_FIELDS` always
  appear as ``AudioSuite:field:<name>``.  An empty value means "the source had
  no value", so restoration clears the field instead of inheriting the kept
  file's.
- A value containing a line break, a tab or any other control character is
  written as ``AudioSuite:field:<name>:base64`` because XML attribute-value
  normalisation rewrites literal whitespace.  The reader accepts both forms.
- Lyrics and artwork are always base64.  Artwork is carried only when it is
  JPEG, the only form the shared artwork writer supports; a PNG cover is
  recorded as ``AudioSuite:artwork:omitted`` with a reason, never dropped
  silently.

Changed in 2.4.0: new module (PLAN_duplicate_disposition_2026-11-02.md DD-1).
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import os
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .tag_helper_art import embed_artwork
from .tag_helper_base import EDITABLE_FIELDS, TagHandlerFactory
from .tag_helper_reader import MUSICBRAINZ_ID_FIELDS
from .tag_helper_writer import (
    write_isrc,
    write_musicbrainz_ids,
    write_plain_lyrics,
    write_synced_lyrics,
)

#: Schema version written by this module and the only one the reader accepts.
STUB_VERSION = 1

#: Prefix every suite-owned parameter carries.
STUB_PREFIX = "AudioSuite:"

#: The parameter that distinguishes a suite stub from a plain ASX playlist.
STUB_VERSION_PARAM = f"{STUB_PREFIX}stub-version"

#: Fixed display text, so a stub written by two tools reads the same.
STUB_ABSTRACT = "Suite-generated stub; metadata for the file this replaced."

#: Caps applied before parsing, so a hostile or corrupt stub cannot exhaust
#: memory.  A real stub is a few KiB; the artwork allowance is the large part.
MAX_STUB_BYTES = 8 * 1024 * 1024
MAX_ARTWORK_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 2 * 1024 * 1024

#: JPEG's magic number.  ``embed_artwork`` accepts JPEG only, so a PNG cover is
#: recorded as omitted rather than written and silently ignored.
_JPEG_MAGIC = b"\xff\xd8\xff"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

#: Order the nine field params are written in; it is the reader's field order
#: and the literal fixture's order, so it is part of the schema.
FIELD_ORDER: tuple[str, ...] = EDITABLE_FIELDS

#: Order MusicBrainz ids are written in.
MBID_ORDER: tuple[str, ...] = MUSICBRAINZ_ID_FIELDS

#: Marker written on a stub whose artwork was not carried.
ARTWORK_OMITTED_PARAM = f"{STUB_PREFIX}artwork:omitted"
ARTWORK_MIME_PARAM = f"{STUB_PREFIX}artwork:mime"
ARTWORK_BASE64_PARAM = f"{STUB_PREFIX}artwork:base64"
LYRICS_PLAIN_PARAM = f"{STUB_PREFIX}lyrics:plain-base64"
LYRICS_SYNCED_PARAM = f"{STUB_PREFIX}lyrics:synced-base64"
ORIGINAL_NAME_PARAM = f"{STUB_PREFIX}original-name"
KEEPER_NAME_PARAM = f"{STUB_PREFIX}keeper-name"


class StubError(ValueError):
    """A stub could not be read or understood.

    The message is user-facing: the extractor reports it as the per-file
    failure reason, so it says what is wrong rather than naming a class.
    """


class NotAStubError(StubError):
    """The playlist is a plain ASX file, not a suite stub."""


@dataclass(frozen=True)
class StubMetadata:
    """Everything a stub records about the file it replaced.

    Attributes:
        original_name: File name of the duplicate the stub replaced.
        keeper_name: File name of the copy the stub points at.
        fields: The nine canonical editor fields; an empty string means the
            source had no value and restoration must clear the field.
        mbids: MusicBrainz identifiers that were present, by canonical name.
        isrcs: Every ISRC that was present, in stored order.
        lyrics_plain: Unsynced lyrics, or ``None`` when absent.
        lyrics_synced: LRC-formatted synced lyrics, or ``None`` when absent.
        artwork: Raw JPEG cover bytes, or ``None``.
        artwork_omitted: Why artwork was not carried, or an empty string.
        reference: The ``<REF HREF>`` value; ``write_stub`` fills it from the
            keeper's path when it is empty.
        keeper_path: Absolute keeper path used to build a relative reference.
        stub_version: Schema version this metadata was read from or written at.
    """

    original_name: str
    keeper_name: str
    fields: dict[str, str] = field(
        default_factory=lambda: {name: "" for name in FIELD_ORDER}
    )
    mbids: dict[str, str] = field(default_factory=dict)
    isrcs: tuple[str, ...] = ()
    lyrics_plain: str | None = None
    lyrics_synced: str | None = None
    artwork: bytes | None = None
    artwork_omitted: str = ""
    reference: str = ""
    keeper_path: str = ""
    stub_version: int = STUB_VERSION


def _clean_fields(fields: Mapping[str, str | None]) -> dict[str, str]:
    """Return every canonical field, defaulting an absent one to empty.

    Args:
        fields: Whatever the reader or snapshot produced.

    Returns:
        A dict with exactly :data:`FIELD_ORDER`, values coerced to ``str``.
    """
    return {name: str(fields.get(name, "") or "") for name in FIELD_ORDER}


def _needs_base64(value: str) -> bool:
    """Return whether a field value must use the ``:base64`` form.

    Args:
        value: The tag value.

    Returns:
        True for a line break, a tab or any other control character, all of
        which XML attribute-value normalisation would alter or reject.
    """
    return any(char in "\r\n\t" or ord(char) < 32 for char in value)


def _encode(value: str) -> str:
    """Return *value* as base64 UTF-8 text.

    Args:
        value: Text to encode.

    Returns:
        The base64 ASCII text.
    """
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _decode(value: str, *, what: str) -> str:
    """Decode a base64 UTF-8 value, refusing anything malformed or oversized.

    Args:
        value: The base64 text from the stub.
        what: Field name used in the failure message.

    Returns:
        The decoded text.

    Raises:
        StubError: If the value is not valid base64, is too large, or does not
            decode as UTF-8.
    """
    if len(value) > MAX_TEXT_BYTES * 2:
        raise StubError(f"{what} is too large for a stub")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise StubError(f"{what} is not valid base64") from exc
    if len(raw) > MAX_TEXT_BYTES:
        raise StubError(f"{what} is too large for a stub")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StubError(f"{what} is not valid UTF-8") from exc


def _add_param(parent: ET.Element, name: str, value: str) -> None:
    """Append one ``<PARAM NAME=... VALUE=...>`` element.

    Args:
        parent: The ``<ENTRY>`` element to append to.
        name: Parameter name, including the ``AudioSuite:`` prefix.
        value: Parameter value; never ``None``.
    """
    ET.SubElement(parent, "PARAM", {"NAME": name, "VALUE": value})


def build_stub(metadata: StubMetadata, reference: str | None = None) -> bytes:
    """Serialise *metadata* as a versioned ASX 3.0 stub.

    The element and attribute order is fixed and asserted by a test; the nine
    fields are always present, including when empty.

    Args:
        metadata: The snapshot to write.
        reference: The ``<REF HREF>`` value to use.  Defaults to
            ``metadata.reference`` and, when that is empty too, to the keeper
            name.

    Returns:
        UTF-8 XML bytes with an XML declaration and a trailing newline.
    """
    href = reference if reference is not None else metadata.reference
    if not href:
        href = metadata.keeper_name

    root = ET.Element("ASX", {"Version": "3.0"})
    entry = ET.SubElement(root, "ENTRY")
    fields = _clean_fields(metadata.fields)

    artist = fields["artist"].strip()
    title = fields["title"].strip()
    if artist and title:
        display_title = f"{artist} - {title}"
    else:
        display_title = title or artist

    ET.SubElement(entry, "TITLE").text = display_title
    ET.SubElement(entry, "AUTHOR").text = artist
    ET.SubElement(entry, "COPYRIGHT").text = fields["year"]
    ET.SubElement(entry, "ABSTRACT").text = STUB_ABSTRACT
    ET.SubElement(entry, "REF", {"HREF": href})

    _add_param(entry, STUB_VERSION_PARAM, str(STUB_VERSION))
    _add_param(entry, ORIGINAL_NAME_PARAM, metadata.original_name)
    _add_param(entry, KEEPER_NAME_PARAM, metadata.keeper_name)

    for name in FIELD_ORDER:
        value = fields[name]
        if _needs_base64(value):
            _add_param(entry, f"{STUB_PREFIX}field:{name}:base64", _encode(value))
        else:
            _add_param(entry, f"{STUB_PREFIX}field:{name}", value)

    for name in MBID_ORDER:
        value = metadata.mbids.get(name, "")
        if value:
            _add_param(entry, f"{STUB_PREFIX}mbid:{name}", value)

    for isrc in metadata.isrcs:
        if isrc:
            _add_param(entry, f"{STUB_PREFIX}isrc", isrc)

    if metadata.lyrics_plain:
        _add_param(entry, LYRICS_PLAIN_PARAM, _encode(metadata.lyrics_plain))
    if metadata.lyrics_synced:
        _add_param(entry, LYRICS_SYNCED_PARAM, _encode(metadata.lyrics_synced))
    if metadata.artwork:
        _add_param(entry, ARTWORK_MIME_PARAM, "image/jpeg")
        _add_param(
            entry,
            ARTWORK_BASE64_PARAM,
            base64.b64encode(metadata.artwork).decode("ascii"),
        )
    elif metadata.artwork_omitted:
        _add_param(entry, ARTWORK_OMITTED_PARAM, metadata.artwork_omitted)

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return ('<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n").encode("utf-8")


def _stub_bytes(data: bytes) -> None:
    """Refuse a payload that is too large or declares a DTD/entity.

    Args:
        data: The raw playlist bytes.

    Raises:
        StubError: If the payload is oversized or carries a DTD/entity, the
            billion-laughs/XXE shape no legitimate ASX uses.
    """
    if len(data) > MAX_STUB_BYTES:
        raise StubError("Stub is too large")
    upper = data.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise StubError("DTD-bearing stub rejected")


def _tag_name(element: ET.Element) -> str:
    """Return an element's local name, lower-cased and namespace-free.

    Args:
        element: The element.

    Returns:
        The local name in lower case.
    """
    return element.tag.rsplit("}", 1)[-1].lower()


def _attribute(element: ET.Element, name: str) -> str:
    """Return an attribute case-insensitively, or an empty string.

    XML attribute names are case-sensitive, and the format's own writers use
    ``HREF``/``NAME``/``VALUE``, so the reader accepts any casing.

    Args:
        element: The element.
        name: Attribute name to look for.

    Returns:
        The attribute value, or ``""`` when absent.
    """
    wanted = name.lower()
    for key, value in element.attrib.items():
        if key.lower() == wanted:
            return value
    return ""


def parse_stub_bytes(data: bytes) -> StubMetadata:
    """Parse a stub payload into :class:`StubMetadata`.

    Args:
        data: Raw XML bytes.

    Returns:
        The parsed metadata, with ``reference`` set from ``<REF HREF>``.

    Raises:
        StubError: If the payload is not a suite stub, is malformed, carries an
            unsupported schema version, or has an invalid base64 value.
    """
    _stub_bytes(data)
    try:
        root = ET.fromstring(data)  # nosec B314 - DTD/entity guard above
    except ET.ParseError as exc:
        raise StubError("Stub is not valid XML") from exc

    href = ""
    params: list[tuple[str, str]] = []
    for element in root.iter():
        name = _tag_name(element)
        if name == "ref" and not href:
            href = _attribute(element, "href")
        elif name == "param":
            params.append((_attribute(element, "name"), _attribute(element, "value")))

    version_text: str | None = None
    values: dict[str, list[str]] = {}
    fields: dict[str, str] = {name: "" for name in FIELD_ORDER}
    mbids: dict[str, str] = {}
    isrcs: list[str] = []
    lyrics_plain: str | None = None
    lyrics_synced: str | None = None
    artwork: bytes | None = None
    artwork_mime = ""
    artwork_omitted = ""

    for raw_name, value in params:
        if not raw_name.lower().startswith(STUB_PREFIX.lower()):
            continue
        name = raw_name[len(STUB_PREFIX) :]

        if name == "stub-version":
            version_text = value
        elif name == "original-name":
            values.setdefault("original-name", []).append(value)
        elif name == "keeper-name":
            values.setdefault("keeper-name", []).append(value)
        elif name.startswith("field:") and name.endswith(":base64"):
            field_name = name[len("field:") : -len(":base64")]
            if field_name in fields:
                fields[field_name] = _decode(value, what=f"field {field_name}")
        elif name.startswith("field:"):
            field_name = name[len("field:") :]
            if field_name in fields:
                fields[field_name] = value
        elif name.startswith("mbid:"):
            mbid_name = name[len("mbid:") :]
            if mbid_name in MBID_ORDER and value:
                mbids[mbid_name] = value
        elif name == "isrc":
            if value:
                isrcs.append(value)
        elif name == "lyrics:plain-base64":
            lyrics_plain = _decode(value, what="lyrics")
        elif name == "lyrics:synced-base64":
            lyrics_synced = _decode(value, what="synced lyrics")
        elif name == "artwork:mime":
            artwork_mime = value
        elif name == "artwork:base64":
            if len(value) > MAX_ARTWORK_BYTES * 2:
                raise StubError("Artwork is too large for a stub")
            try:
                raw = base64.b64decode(value, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise StubError("Artwork is not valid base64") from exc
            if len(raw) > MAX_ARTWORK_BYTES:
                raise StubError("Artwork is too large for a stub")
            artwork = raw
        elif name == "artwork:omitted":
            artwork_omitted = value

    if version_text is None:
        raise NotAStubError("Not an AudioSuite stub")
    try:
        version = int(version_text)
    except ValueError as exc:
        raise StubError(f"Invalid stub version: {version_text}") from exc
    if version != STUB_VERSION:
        raise StubError(
            f"Unsupported stub version {version}; this extractor reads version "
            f"{STUB_VERSION}"
        )
    if artwork is not None and artwork_mime and artwork_mime != "image/jpeg":
        raise StubError(f"Unsupported artwork type: {artwork_mime}")

    return StubMetadata(
        original_name=(values.get("original-name") or [""])[-1],
        keeper_name=(values.get("keeper-name") or [""])[-1],
        fields=fields,
        mbids=mbids,
        isrcs=tuple(isrcs),
        lyrics_plain=lyrics_plain,
        lyrics_synced=lyrics_synced,
        artwork=artwork,
        artwork_omitted=artwork_omitted,
        reference=href,
        stub_version=version,
    )


def read_stub(path: str | os.PathLike[str]) -> StubMetadata:
    """Read one stub file.

    Args:
        path: The ``.asx`` file to read.

    Returns:
        The parsed metadata.

    Raises:
        StubError: If the file is too large, unreadable, not a suite stub, or
            malformed.  A plain ASX raises ``StubError("Not an AudioSuite
            stub")``; callers that need "is this a stub?" use
            :func:`is_stub_file` first.
    """
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        raise StubError(f"Could not read the stub: {exc}") from exc
    return parse_stub_bytes(data)


def is_stub_file(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* is a readable suite stub.

    A malformed stub is reported as not-a-stub here; :func:`read_stub` is what
    surfaces the reason to the user.

    Args:
        path: The playlist to probe.

    Returns:
        True only when the file parses as a supported suite stub.
    """
    try:
        read_stub(path)
    except StubError:
        return False
    return True


def _jpeg_or_none(data: bytes | None) -> tuple[bytes | None, str]:
    """Return JPEG bytes that can be carried, or the reason they cannot.

    Args:
        data: Raw artwork read from the source file.

    Returns:
        ``(jpeg_bytes, "")`` for JPEG, or ``(None, reason)`` otherwise.
    """
    if not data:
        return None, ""
    if data.startswith(_JPEG_MAGIC):
        if len(data) > MAX_ARTWORK_BYTES:
            return None, "Cover art is larger than the stub's 4 MiB limit"
        return data, ""
    if data.startswith(_PNG_MAGIC):
        return None, "PNG cover art is not carried in stub version 1"
    return None, "Cover art is not JPEG and is not carried in stub version 1"


def snapshot_tags(path: str | os.PathLike[str]) -> StubMetadata:
    """Read the file's canonical tags into a stub snapshot.

    Args:
        path: The audio file to snapshot.

    Returns:
        Metadata named after *path* with the nine fields, MBIDs, ISRCs, lyrics
        and JPEG artwork that are present.

    Raises:
        AudioTagError: If the file's format has no registered handler or its
            tags cannot be read.
    """
    source = os.fspath(path)
    handler = TagHandlerFactory.get_handler(source)
    fields = _clean_fields(handler.read_editable_tags())
    mbids = {
        name: value for name in MBID_ORDER if (value := handler.read_custom_field(name))
    }
    isrcs = tuple(dict.fromkeys(handler.read_isrcs()))
    lyrics = handler.read_lyrics_tags()
    artwork, omitted = _jpeg_or_none(handler.extract_artwork())
    return StubMetadata(
        original_name=os.path.basename(source),
        keeper_name="",
        fields=fields,
        mbids=mbids,
        isrcs=isrcs,
        lyrics_plain=lyrics.plain,
        lyrics_synced=lyrics.synced,
        artwork=artwork,
        artwork_omitted=omitted,
    )


def apply_tags(path: str | os.PathLike[str], metadata: StubMetadata) -> None:
    """Replace a file's tags with the snapshot's.

    The copy's inherited tags are deleted first, then all nine fields are
    written (an empty value clears the field), then MBIDs, ISRCs, lyrics and
    JPEG artwork are restored.  ReplayGain is deliberately untouched: it was
    never snapshotted, and the copy's own values must not survive either.

    Args:
        path: The audio file to tag.
        metadata: The snapshot to apply.

    Raises:
        AudioTagError: If a tag operation fails.  The caller removes the
            temporary file, so a partial write never becomes the final file.
    """
    handler = TagHandlerFactory.get_handler(os.fspath(path))
    handler.delete_tags()
    for name in FIELD_ORDER:
        value = metadata.fields.get(name, "") or ""
        handler.write_editable_tag(name, value or None)
    if metadata.mbids:
        write_musicbrainz_ids(os.fspath(path), dict(metadata.mbids))
    if metadata.isrcs:
        write_isrc(os.fspath(path), metadata.isrcs)
    if metadata.lyrics_synced:
        write_synced_lyrics(os.fspath(path), metadata.lyrics_synced)
    if metadata.lyrics_plain:
        write_plain_lyrics(os.fspath(path), metadata.lyrics_plain)
    if metadata.artwork:
        embed_artwork(os.fspath(path), metadata.artwork)


def stub_path_for(audio_path: str | os.PathLike[str]) -> Path:
    """Return a free ``<stem>.asx`` path beside *audio_path*.

    A name already present gains a ``" (2)"``, ``" (3)"``… suffix before the
    extension rather than being overwritten.

    Args:
        audio_path: The duplicate being replaced.

    Returns:
        A path in the duplicate's folder that does not exist yet.
    """
    audio = Path(audio_path)
    candidate = audio.with_suffix(".asx")
    counter = 2
    while candidate.exists():
        candidate = audio.with_name(f"{audio.stem} ({counter}).asx")
        counter += 1
    return candidate


def derive_restore_name(
    stub_path: str | os.PathLike[str], keeper_path: str | os.PathLike[str]
) -> Path:
    """Return the recreated file's path: stub stem, keeper extension.

    A FLAC payload must never carry an ``.mp3`` name, so the duplicate's stem
    is combined with the keeper's extension.  An existing file gains a numeric
    suffix instead of being overwritten.

    Args:
        stub_path: The stub being restored.
        keeper_path: The audio file the stub points at.

    Returns:
        A path in the stub's folder that does not exist yet.
    """
    stub = Path(stub_path)
    suffix = Path(keeper_path).suffix
    candidate = stub.with_name(f"{stub.stem}{suffix}")
    counter = 2
    while candidate.exists():
        candidate = stub.with_name(f"{stub.stem} ({counter}){suffix}")
        counter += 1
    return candidate


def write_stub(path: str | os.PathLike[str], metadata: StubMetadata) -> None:
    """Write *metadata* to *path* atomically, with a relative reference.

    The stub is serialised to a temporary file in the destination folder and
    ``os.replace``d into place, so a reader never sees a half-written playlist.

    Args:
        path: Destination ``.asx`` path.
        metadata: The snapshot to write.  Its ``keeper_path`` is used to build
            a relative ``<REF HREF>``; a cross-volume keeper falls back to an
            absolute path because ``os.path.relpath`` cannot cross drives.

    Raises:
        OSError: If the temporary file cannot be written or replaced.
    """
    destination = Path(path)
    reference = metadata.reference
    if not reference and metadata.keeper_path:
        try:
            relative = os.path.relpath(
                metadata.keeper_path, start=os.fspath(destination.parent)
            )
        except ValueError:
            relative = metadata.keeper_path
        reference = relative.replace("\\", "/")
    data = build_stub(metadata, reference=reference)

    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def with_keeper(
    metadata: StubMetadata, keeper_path: str | os.PathLike[str]
) -> StubMetadata:
    """Return *metadata* with the keeper's name and path filled in.

    Args:
        metadata: A snapshot from :func:`snapshot_tags`.
        keeper_path: The copy the stub will point at.

    Returns:
        A copy of *metadata* naming the keeper.
    """
    keeper = os.fspath(keeper_path)
    return dataclasses.replace(
        metadata,
        keeper_name=os.path.basename(keeper),
        keeper_path=keeper,
    )
