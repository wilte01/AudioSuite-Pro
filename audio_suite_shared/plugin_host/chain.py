"""chain.py — the ordered list of plugin slots a render applies.

A chain is inert data: a tuple of :class:`PluginSlot` records, each naming one
scanned bundle, its saved state, its bypass switch and any parameter overrides.
Nothing here loads a plugin — rendering belongs to the worker (F-M1 order #2) —
and that separation is the point.  A chain can be built, saved, reloaded and
checked before any third-party binary is touched, so a missing plugin or a state
saved for another version is reported by validation rather than discovered
halfway through a batch.

Validation names every problem by slot index and plugin name.  A plugin path is
never part of a message: a chain summary travels into run reports, and a report
must describe the plugin a user chose, not the folder layout of the machine that
rendered it.

Changed in 3.0.0: new module — slots, the chain, validation and the preset
codec (F-M1 order-of-work #1).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from audio_suite_shared.plugin_host.scan import (
    AU_SUFFIX,
    VST3_SUFFIX,
    ScanResult,
)
from audio_suite_shared.plugin_host.state import (
    PluginStateBlob,
    PluginStateError,
    PluginStateMismatch,
    require_compatible,
)

#: Schema version of the chain's preset document.  A preset written by another
#: version is refused, not guessed at.
CHAIN_PRESET_VERSION = 1

#: Keys one slot may carry in a preset document.  An unknown key is a typo, and
#: ignoring it would silently drop what the writer meant to save.
_SLOT_KEYS = frozenset({"plugin", "state", "bypass", "parameters"})


class ChainPresetError(ValueError):
    """A saved plugin chain is not this suite's preset format."""


class ChainValidationError(ValueError):
    """A chain names plugins or state the scan cannot satisfy.

    Attributes
    ----------
    problems : tuple[ChainProblem, ...]
        Every problem found, so a caller can report all of them rather than the
        first.
    """

    def __init__(self, message: str, problems: "tuple[ChainProblem, ...]") -> None:
        """Build the error from its reportable problems.

        Parameters
        ----------
        message : str
            The one-line summary, as :meth:`ChainValidation.describe` builds it.
        problems : tuple[ChainProblem, ...]
            The problems the chain has.
        """
        super().__init__(message)
        self.problems = problems


@dataclass(frozen=True)
class PluginSlot:
    """One plugin in a chain.

    Attributes
    ----------
    plugin_path : str
        The bundle path the slot names, as the scan reports it.  It is compared
        case-insensitively on Windows and never printed in a message.
    state : PluginStateBlob | None
        The versioned state saved for this plugin, or None for the plugin's
        defaults.
    bypass : bool
        True to leave this slot out of the render.  Every slot bypassed is a
        chain that renders its input unchanged (proven with the worker,
        F-M1 order #2).
    parameter_overrides : Mapping[str, float]
        Parameters the preset pins, by the plugin's own parameter name.
    """

    plugin_path: str
    state: PluginStateBlob | None = None
    bypass: bool = False
    parameter_overrides: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalise and refuse a slot that could not identify its plugin.

        Raises
        ------
        ValueError
            The path is empty, an override has no name, or an override value is
            not a finite number.
        TypeError
            The state is not a blob, or the bypass flag is not a boolean.
        """
        if not self.plugin_path.strip():
            raise ValueError("a plugin slot needs the path of a scanned plugin")
        if self.state is not None and not isinstance(self.state, PluginStateBlob):
            raise TypeError("a plugin slot's state must be a PluginStateBlob or None")
        if not isinstance(self.bypass, bool):
            raise TypeError("a plugin slot's bypass must be True or False")
        overrides: dict[str, float] = {}
        for name, value in self.parameter_overrides.items():
            if not isinstance(name, str) or not name.strip():
                raise ValueError("a parameter override needs a parameter name")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"parameter override {name!r} must be a number, not {value!r}"
                )
            if not math.isfinite(float(value)):
                raise ValueError(f"parameter override {name!r} must be finite")
            overrides[name] = float(value)
        object.__setattr__(self, "plugin_path", self.plugin_path.strip())
        object.__setattr__(self, "parameter_overrides", MappingProxyType(overrides))

    @property
    def plugin_name(self) -> str:
        """Return the plugin's display name, never its path.

        Returns
        -------
        str
            The bundle's file name with its ``.vst3``/``.component`` suffix
            removed.
        """
        name = Path(self.plugin_path).name
        lowered = name.lower()
        for suffix in (VST3_SUFFIX, AU_SUFFIX):
            if lowered.endswith(suffix):
                return name[: -len(suffix)]
        return name


@dataclass(frozen=True)
class ChainProblem:
    """One reason a chain cannot be rendered as saved.

    Attributes
    ----------
    slot : int
        Zero-based position in the chain, so a user can point at the row.
    plugin : str
        The plugin's name — never its path.
    reason : str
        One sentence naming what is wrong, with no filesystem path in it.
    """

    slot: int
    plugin: str
    reason: str


@dataclass(frozen=True)
class ChainValidation:
    """The result of checking a chain against a scan.

    Attributes
    ----------
    problems : tuple[ChainProblem, ...]
        Every problem found, in slot order; empty when the chain is renderable.
    """

    problems: tuple[ChainProblem, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether the chain can be rendered as saved."""
        return not self.problems

    def describe(self) -> str:
        """Return a one-line report, naming plugins but no paths.

        Returns
        -------
        str
            ``"plugin chain: no problems"``, or one clause per problem.
        """
        if not self.problems:
            return "plugin chain: no problems"
        clauses = "; ".join(
            f"slot {problem.slot} ({problem.plugin}) {problem.reason}"
            for problem in self.problems
        )
        return f"plugin chain: {clauses}"

    def raise_if_invalid(self) -> None:
        """Raise the collected problems as one error.

        Raises
        ------
        ChainValidationError
            The chain has at least one problem.
        """
        if self.problems:
            raise ChainValidationError(self.describe(), self.problems)


@dataclass(frozen=True)
class PluginChain:
    """An ordered list of plugin slots.

    Attributes
    ----------
    slots : tuple[PluginSlot, ...]
        The chain, in render order.
    """

    slots: tuple[PluginSlot, ...] = ()

    def __post_init__(self) -> None:
        """Store the slots as a tuple, so the chain cannot be edited in place."""
        object.__setattr__(self, "slots", tuple(self.slots))

    def __len__(self) -> int:
        """Return how many slots the chain holds, bypassed ones included."""
        return len(self.slots)

    def active_slots(self) -> tuple[PluginSlot, ...]:
        """Return the slots a render applies, in order.

        Returns
        -------
        tuple[PluginSlot, ...]
            Every slot whose bypass switch is off.  An empty result means the
            renderer's output is the input, which is what makes a fully
            bypassed chain bit-transparent once the worker exists.
        """
        return tuple(slot for slot in self.slots if not slot.bypass)

    def all_bypassed(self) -> bool:
        """Return whether every slot is bypassed, ignoring its plugins.

        Returns
        -------
        bool
            True for a non-empty chain whose every slot is bypassed.  An empty
            chain returns False: it has no slot to bypass, and the caller that
            cares about an empty chain should ask :func:`len`.
        """
        return bool(self.slots) and all(slot.bypass for slot in self.slots)

    def validate(self, result: ScanResult) -> ChainValidation:
        """Check every slot against a scan.

        Parameters
        ----------
        result : ScanResult
            The scan to resolve slots against.

        Returns
        -------
        ChainValidation
            The problems found.  A missing plugin is reported here, before any
            render, and a state saved for another version is refused rather
            than applied.
        """
        problems: list[ChainProblem] = []
        for index, slot in enumerate(self.slots):
            record = result.record_for(slot.plugin_path)
            if record is None:
                problems.append(
                    ChainProblem(
                        index,
                        slot.plugin_name,
                        "is not installed in any scanned plugin folder",
                    )
                )
                continue
            if record.problem is not None:
                problems.append(ChainProblem(index, record.name, record.problem))
                continue
            if slot.state is not None:
                try:
                    require_compatible(slot.state, record)
                except PluginStateMismatch as exc:
                    problems.append(ChainProblem(index, record.name, str(exc)))
        return ChainValidation(tuple(problems))

    def describe(self) -> str:
        """Return the chain as a short summary for a run report.

        Returns
        -------
        str
            ``"Alpha (active), Beta (bypassed)"``, or ``"no plugins"``.
        """
        if not self.slots:
            return "no plugins"
        parts = [
            f"{slot.plugin_name} ({'bypassed' if slot.bypass else 'active'})"
            for slot in self.slots
        ]
        return ", ".join(parts)

    def to_preset(self) -> dict[str, object]:
        """Return the chain as a JSON-friendly preset document.

        Returns
        -------
        dict[str, object]
            ``{"version": 1, "slots": [...]}`` where each slot carries its
            path, bypass flag, parameter overrides and encoded state.  The
            result is a fresh object, safe to hand to :func:`json.dumps`.
        """
        return {
            "version": CHAIN_PRESET_VERSION,
            "slots": [
                {
                    "plugin": slot.plugin_path,
                    "bypass": slot.bypass,
                    "parameters": dict(slot.parameter_overrides),
                    "state": None if slot.state is None else slot.state.encode(),
                }
                for slot in self.slots
            ],
        }

    @classmethod
    def from_preset(cls, preset: Mapping[str, object]) -> PluginChain:
        """Build a chain from a document :meth:`to_preset` wrote.

        Parameters
        ----------
        preset : Mapping[str, object]
            The decoded preset document.

        Returns
        -------
        PluginChain
            The chain it describes.

        Raises
        ------
        ChainPresetError
            The document is another schema version, has an unknown key, or
            holds a slot whose fields are the wrong type.
        """
        if not isinstance(preset, Mapping):
            raise ChainPresetError("a plugin chain preset must be an object")
        version = preset.get("version")
        if version != CHAIN_PRESET_VERSION:
            raise ChainPresetError(
                f"plugin chain preset uses version {version!r}; "
                f"this suite writes version {CHAIN_PRESET_VERSION}"
            )
        entries = preset.get("slots")
        if not isinstance(entries, list):
            raise ChainPresetError("a plugin chain preset needs a list of slots")
        return cls(
            tuple(
                _slot_from_preset(index, entry) for index, entry in enumerate(entries)
            )
        )


def _slot_from_preset(index: int, entry: object) -> PluginSlot:
    """Rebuild one slot from a preset entry.

    Parameters
    ----------
    index : int
        Zero-based slot position, used in messages.
    entry : object
        One value of the preset's ``slots`` list.

    Returns
    -------
    PluginSlot
        The slot.

    Raises
    ------
    ChainPresetError
        The entry is not an object, carries an unknown key, or holds a field of
        the wrong type.
    """
    if not isinstance(entry, Mapping):
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset is not an object"
        )
    unknown = sorted(set(entry) - _SLOT_KEYS)
    if unknown:
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset declares unknown key(s) {unknown}"
        )
    plugin = entry.get("plugin")
    if not isinstance(plugin, str) or not plugin.strip():
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset names no plugin"
        )
    bypass = entry.get("bypass", False)
    if not isinstance(bypass, bool):
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset has a bypass that is not "
            "True or False"
        )
    raw_parameters = entry.get("parameters", {})
    if not isinstance(raw_parameters, Mapping):
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset has parameters that are "
            "not an object"
        )
    parameters: dict[str, float] = {}
    for name, value in raw_parameters.items():
        if not isinstance(name, str) or isinstance(value, bool):
            raise ChainPresetError(
                f"slot {index} in the plugin chain preset has a malformed "
                "parameter override"
            )
        if not isinstance(value, (int, float)):
            raise ChainPresetError(
                f"slot {index} in the plugin chain preset has a parameter "
                f"override {name!r} that is not a number"
            )
        parameters[name] = float(value)
    raw_state = entry.get("state")
    state: PluginStateBlob | None = None
    if raw_state is not None:
        if not isinstance(raw_state, str):
            raise ChainPresetError(
                f"slot {index} in the plugin chain preset has state that is not text"
            )
        try:
            state = PluginStateBlob.decode(raw_state)
        except PluginStateError as exc:
            raise ChainPresetError(
                f"slot {index} in the plugin chain preset has unreadable state: {exc}"
            ) from exc
    try:
        return PluginSlot(
            plugin_path=plugin,
            state=state,
            bypass=bypass,
            parameter_overrides=parameters,
        )
    except (TypeError, ValueError) as exc:
        raise ChainPresetError(
            f"slot {index} in the plugin chain preset is invalid: {exc}"
        ) from exc
