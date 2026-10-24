"""extension_points.py — the four contracts a plugin can extend.

A plugin contributes through one or more of these surfaces, and each has a
first-party host that actually calls it:

=================  ===========================================================
Extension point    Host
=================  ===========================================================
``tool``            ``tool_plugin`` (registry), ``cli_app`` (command) and the
                    Master Driver (toggle, card, arguments, launcher)
``ui``              ``master_driver.ui.utilities_window`` / ``enrich_tab``
                    (the plugin's own card builder)
``tag_processor``   ``tag_field_updater.core.processor.TagProcessor``
``analysis``        ``library_stats.core.file_processor.scan_directory``
=================  ===========================================================

The contracts are deliberately narrow and duck-typed: a contribution is a
plain callable, so a plugin author needs no import from this package to be
loaded.  The helpers here are what the *hosts* use, and they are also what
turns a contribution's arbitrary return value into a typed outcome the host
can count, log and test.

Changed in 2.1.0: new module — the four extension-point contracts, the plugin
context and the invocation helpers (Sprint 7, Item 7.1).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeAlias, runtime_checkable

from audio_suite_shared.plugin_system.models import (
    ContributionSpec,
    PluginError,
)

#: The value types an analysis contribution may publish.  ``bool`` is refused
#: explicitly (it is an ``int`` subclass) because a flag is a category, not a
#: measured number, and silently aggregating it as 0/1 would invent a metric.
Scalar: TypeAlias = int | float | str

#: Logger namespace shared with the rest of the suite.
logger = logging.getLogger(f"audio_suite.{__name__}")


@dataclass(frozen=True)
class TagProcessorOutcome:
    """What one tag processor did to one file.

    Attributes
    ----------
    changed : bool
        Whether the processor changed a tag that was written to disk.
    message : str
        A short human-readable reason, shown in the host's per-file log.
    """

    changed: bool
    message: str = ""


@runtime_checkable
class TagProcessorHook(Protocol):
    """A tag processor contribution.

    The host calls :meth:`apply` once per file, after its own rules, with the
    dry-run flag the run was started with.  A processor that writes tags must
    honour ``dry_run`` by not writing.
    """

    def apply(self, path: Path, dry_run: bool) -> object:
        """Process one file.

        Args:
            path: The audio file to inspect or rewrite.
            dry_run: True when the run must not persist anything.

        Returns:
            ``True``/``False``, ``None``, or a :class:`TagProcessorOutcome`.
        """
        ...


@runtime_checkable
class AnalysisHook(Protocol):
    """A custom analysis contribution.

    The host calls :meth:`analyse` once per file with the tags it already read,
    so a contribution never pays for a second decode.  Returning a value that
    is not a mapping of scalars is refused by :func:`run_analysis`.
    """

    def analyse(self, path: Path, tags: Mapping[str, Any]) -> object:
        """Analyse one file.

        Args:
            path: The audio file being scanned.
            tags: The tags the host read for this file.

        Returns:
            A mapping of metric name to ``int``, ``float`` or ``str``.
        """
        ...


class PluginContext:
    """The suite services a plugin contribution receives.

    The context is passed *positionally* as the last argument when a
    contribution's callable declares a ``context`` parameter, so a contribution
    may ignore it entirely.  It exists so a plugin does not have to re-implement
    tag reading and writing (and get the FLAC in-place rule wrong, the way the
    suite's own scrubber once did).

    Args:
        plugin_id: The plugin that owns the contribution.
        logger: The logger the contribution should use; its records carry the
            suite namespace and reach ``logs/<program>.log``.
    """

    def __init__(self, plugin_id: str, logger: logging.Logger) -> None:
        self.plugin_id = plugin_id
        self.logger = logger

    def read_tags(self, path: Path) -> dict[str, str | None]:
        """Read every editable tag field of *path*.

        Args:
            path: The audio file.

        Returns:
            The editable fields mapped to their values, or None per field.
        """
        from audio_suite_shared.tag_helper import read_editable_tags

        return dict(read_editable_tags(str(path)))

    def write_tag(self, path: Path, field: str, value: str | None) -> None:
        """Write one editable tag field through the suite's tag layer.

        Args:
            path: The audio file.
            field: One of the suite's editable field names.
            value: The value to write, or None to clear the field.

        Raises:
            PluginError: The field is not one the tag layer edits.
        """
        from audio_suite_shared.tag_helper import EDITABLE_FIELDS, write_editable_tag

        if field not in EDITABLE_FIELDS:
            raise PluginError(
                f"{field!r} is not an editable tag field; "
                f"expected one of {sorted(EDITABLE_FIELDS)}"
            )
        write_editable_tag(str(path), field, value)

    @property
    def editable_fields(self) -> frozenset[str]:
        """Return the field names :meth:`write_tag` accepts."""
        from audio_suite_shared.tag_helper import EDITABLE_FIELDS

        return frozenset(EDITABLE_FIELDS)


def context_for(plugin_id: str) -> PluginContext:
    """Return a plugin context whose logger is named after the plugin.

    Args:
        plugin_id: The plugin that owns the contribution.

    Returns:
        A context bound to that plugin.
    """
    return PluginContext(
        plugin_id, logging.getLogger(f"audio_suite.plugins.{plugin_id}")
    )


def normalise_outcome(value: object) -> TagProcessorOutcome:
    """Turn a tag processor's return value into a typed outcome.

    Accepted forms, so a contribution stays a one-liner when it wants to:

    * ``None`` — nothing changed;
    * a ``bool`` — whether something changed;
    * a :class:`TagProcessorOutcome`;
    * any object with ``changed`` and optional ``message`` attributes.

    Args:
        value: The contribution's return value.

    Returns:
        The normalised outcome.
    """
    if value is None:
        return TagProcessorOutcome(changed=False)
    if isinstance(value, bool):
        return TagProcessorOutcome(changed=value)
    if isinstance(value, TagProcessorOutcome):
        return value
    changed = getattr(value, "changed", None)
    if isinstance(changed, bool):
        message = getattr(value, "message", "")
        return TagProcessorOutcome(
            changed=changed, message=message if isinstance(message, str) else ""
        )
    raise PluginError(
        "a tag processor must return None, a bool, or an object with a boolean "
        f"'changed' attribute; got {type(value).__name__}"
    )


def run_tag_processor(
    hook: Callable[..., object],
    path: Path,
    *,
    dry_run: bool,
    context: PluginContext | None = None,
) -> TagProcessorOutcome:
    """Invoke one tag processor and normalise its outcome.

    Args:
        hook: The resolved contribution callable.
        path: The audio file to process.
        dry_run: True when the run must not persist anything.
        context: The plugin context to pass when the hook accepts one.

    Returns:
        The normalised outcome.

    Raises:
        PluginError: The return value is not a recognised outcome.
    """
    value = _invoke(hook, (path, dry_run), context)
    return normalise_outcome(value)


def run_analysis(
    hook: Callable[..., object],
    path: Path,
    tags: Mapping[str, Any],
    *,
    context: PluginContext | None = None,
) -> dict[str, Scalar]:
    """Invoke one analysis contribution and validate its metrics.

    Args:
        hook: The resolved contribution callable.
        path: The audio file being scanned.
        tags: The tags the host read for this file.
        context: The plugin context to pass when the hook accepts one.

    Returns:
        The contribution's metrics, with non-scalar values removed.

    Raises:
        PluginError: The contribution returned something that is not a mapping
            of scalars.
    """
    value = _invoke(hook, (path, dict(tags)), context)
    if not isinstance(value, Mapping):
        raise PluginError(
            "an analysis contribution must return a mapping of metric name to "
            f"int, float or str; got {type(value).__name__}"
        )
    metrics: dict[str, Scalar] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise PluginError(
                f"analysis metric names must be non-empty strings; got {key!r}"
            )
        if isinstance(item, bool) or not isinstance(item, (int, float, str)):
            raise PluginError(
                f"analysis metric {key!r} is {type(item).__name__}; "
                "only int, float and str are published"
            )
        metrics[key] = item
    return metrics


def accepts_context(hook: Callable[..., object]) -> bool:
    """Return whether *hook* declares a parameter named ``context``.

    Args:
        hook: The contribution callable.

    Returns:
        True when the hook wants a :class:`PluginContext` passed.
    """
    return _declares(hook, "context")


def run_tool_entry(
    hook: Callable[..., object], directory: str, *, dry_run: bool
) -> None:
    """Call a plugin tool's CLI entry point.

    The entry point is the plugin's own ``main``.  The suite passes the folder
    every tool command takes, and the run mode only when the callable declares
    a ``dry_run`` parameter (or takes ``**kwargs``) — a plugin that has nothing
    to write is not forced to accept a flag it would ignore.

    Args:
        hook: The resolved entry point.
        directory: The folder the command was given.
        dry_run: Whether ``--dry`` was in effect.
    """
    if _declares(hook, "dry_run"):
        hook(directory, dry_run=dry_run)
        return
    hook(directory)


def _declares(hook: Callable[..., object], name: str) -> bool:
    """Return whether *hook* can accept a keyword argument called *name*.

    Args:
        hook: The callable to inspect.
        name: The keyword argument name.

    Returns:
        True when the parameter exists or the hook takes ``**kwargs``.
    """
    import inspect

    try:
        signature = inspect.signature(hook)
    except (TypeError, ValueError):  # pragma: no cover - builtins only
        return False
    if name in signature.parameters:
        return True
    return any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )


def _invoke(
    hook: Callable[..., object],
    args: tuple[object, ...],
    context: PluginContext | None,
) -> object:
    """Call *hook* with *args*, adding the context when it is wanted.

    Args:
        hook: The contribution callable.
        args: Positional arguments for the hook.
        context: The context to add, or None.

    Returns:
        The hook's return value.
    """
    if context is not None and accepts_context(hook):
        return hook(*args, context=context)
    return hook(*args)


def resolved_contributions(
    specs: tuple[ContributionSpec, ...],
    resolve: Callable[[ContributionSpec], Callable[..., object]],
) -> tuple[tuple[ContributionSpec, Callable[..., object]], ...]:
    """Resolve *specs*, keeping the ones that import and logging the rest.

    A plugin that cannot import must not stop the host's run, so a resolution
    failure is logged against the plugin and the other contributions still
    run.  ``doctor`` reports the same failure as a rejection reason.

    Args:
        specs: The contribution specs to resolve.
        resolve: The resolver, normally ``PluginRegistry.resolve_spec``.

    Returns:
        ``(spec, callable)`` pairs for every spec that resolved.
    """
    resolved: list[tuple[ContributionSpec, Callable[..., object]]] = []
    for spec in specs:
        try:
            hook = resolve(spec)
        except PluginError as exc:
            logger.warning("Skipping plugin contribution: %s", exc)
            continue
        resolved.append((spec, hook))
    return tuple(resolved)
