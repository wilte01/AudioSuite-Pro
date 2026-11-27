"""state.py — versioned, portable plugin state for a chain slot.

A plugin's own state is an opaque byte blob (``pedalboard`` exposes it as
``raw_state``).  Storing those bytes alone loses the one fact a preset needs:
*which plugin, at which version*, produced them.  A plugin update can change
the meaning of its blob without changing its length, so reloading bare bytes
after an update is the silent mis-load this module exists to prevent.

Every saved state is therefore a :class:`PluginStateBlob` — the plugin's
identity, its version, and the payload — serialised as one small ASCII JSON
document with the payload base64-encoded.  That shape round-trips through a
preset file, a JSON ``StageConfig`` and a fresh process without binary data in
a text field, and :meth:`PluginStateBlob.decode` refuses anything it did not
write rather than guessing.

Changed in 3.0.0: new module — the versioned state blob, its base64 codec and
the compatibility check (F-M1 order-of-work #1).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from audio_suite_shared.plugin_host.scan import PluginRecord

#: Schema version of the state document itself.  A blob carrying another
#: version is refused: this suite cannot know what its fields mean.
STATE_FORMAT_VERSION = 1


class PluginStateError(ValueError):
    """A saved plugin state is unreadable or is not this suite's format."""


class PluginStateMismatch(PluginStateError):
    """A saved state belongs to another plugin, or another version of it."""


@dataclass(frozen=True)
class PluginStateBlob:
    """One plugin's saved state, with the identity it was saved for.

    Attributes
    ----------
    plugin : str
        The path-independent identity from
        :attr:`audio_suite_shared.plugin_host.scan.PluginRecord.identifier`
        (``"<vendor>/<name>"``).  A moved plugin keeps its state; a different
        plugin does not inherit it.
    version : str
        The plugin's version when the state was captured.
    payload : bytes
        The plugin's own state bytes.
    format_version : int
        The schema version of the saved document.
    """

    plugin: str
    version: str
    payload: bytes
    format_version: int = STATE_FORMAT_VERSION

    def encode(self) -> str:
        """Return the blob as one ASCII JSON document.

        Returns
        -------
        str
            ``{"format": 1, "plugin": ..., "state": "<base64>", "version": ...}``
            with sorted keys, so two saves of one state are byte-identical.
        """
        document = {
            "format": self.format_version,
            "plugin": self.plugin,
            "state": base64.b64encode(self.payload).decode("ascii"),
            "version": self.version,
        }
        return json.dumps(document, sort_keys=True, separators=(",", ":"))

    @classmethod
    def decode(cls, text: str) -> PluginStateBlob:
        """Read a blob saved by :meth:`encode`.

        Parameters
        ----------
        text : str
            The saved document.

        Returns
        -------
        PluginStateBlob
            The decoded blob.

        Raises
        ------
        PluginStateError
            The document is not JSON, lacks a field, carries another schema
            version, or its payload is not base64.
        """
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PluginStateError(
                f"saved plugin state is not JSON ({exc.msg})"
            ) from exc
        if not isinstance(document, dict):
            raise PluginStateError("saved plugin state is not an object")
        version = document.get("format")
        if version != STATE_FORMAT_VERSION:
            raise PluginStateError(
                f"saved plugin state uses format {version!r}; "
                f"this suite writes format {STATE_FORMAT_VERSION}"
            )
        encoded = document.get("state")
        if not isinstance(encoded, str):
            raise PluginStateError("saved plugin state carries no state payload")
        try:
            payload = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PluginStateError(
                "saved plugin state's payload is not base64"
            ) from exc
        return cls(
            plugin=_required_text(document, "plugin"),
            version=_required_text(document, "version"),
            payload=payload,
            format_version=STATE_FORMAT_VERSION,
        )


def capture_state(
    plugin: PluginRecord,
    payload: bytes,
) -> PluginStateBlob:
    """Wrap *payload* with the identity and version of *plugin*.

    Parameters
    ----------
    plugin : PluginRecord
        The scanned plugin the payload came from.
    payload : bytes
        The plugin's own state bytes.

    Returns
    -------
    PluginStateBlob
        A blob that :func:`require_compatible` can check against the plugin
        installed later.
    """
    return PluginStateBlob(
        plugin=plugin.identifier,
        version=plugin.version,
        payload=bytes(payload),
    )


def require_compatible(blob: PluginStateBlob, plugin: PluginRecord) -> None:
    """Refuse a state blob saved for another plugin or another version.

    Parameters
    ----------
    blob : PluginStateBlob
        The saved state.
    plugin : PluginRecord
        The plugin installed now.

    Raises
    ------
    PluginStateMismatch
        The blob's identity or version differs from the installed plugin.  The
        message names both sides by name and version only — never a path.
    """
    if blob.plugin != plugin.identifier:
        raise PluginStateMismatch(
            f"state was saved for {blob.plugin!r}, but {plugin.name!r} is installed"
        )
    if blob.version != plugin.version:
        raise PluginStateMismatch(
            f"state for {plugin.name!r} was saved at version "
            f"{blob.version or 'unknown'}, but version "
            f"{plugin.version or 'unknown'} is installed"
        )


def _required_text(document: dict[str, Any], key: str) -> str:
    """Return a required text field from a decoded state document.

    Parameters
    ----------
    document : dict[str, Any]
        The decoded JSON object.
    key : str
        Field name.

    Returns
    -------
    str
        The field's value.

    Raises
    ------
    PluginStateError
        The field is missing or not text.
    """
    value = document.get(key)
    if not isinstance(value, str):
        raise PluginStateError(f"saved plugin state field {key!r} is not text")
    return value
