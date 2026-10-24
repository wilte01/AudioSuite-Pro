"""plugins_cli.py — the ``audiosuite plugins`` command group.

The plugin system discovers manifests without importing plugin code, but a
plugin's code only runs once the user enables it.  That switch needs a surface a
user can reach, so this group is it:

=======================  ======================================================
``plugins list``         Every discovered plugin and its state
``plugins enable ID``    Let this plugin's code run in the tools that follow
``plugins disable ID``   Stop importing this plugin's code
=======================  ======================================================

Each command publishes the shared JSON payload (``--json``), so a script can
check what is installed before running a batch.  Every command re-discovers the
plugin directory rather than reading the process singleton: enabling a plugin
must be visible to the very next ``plugins list``, even when both run inside
one interpreter (the test suite does exactly that).

Changed in 2.1.0: new module — the plugin management commands (Sprint 7).
"""

from __future__ import annotations

import json as _json_mod
import time

import click

from audio_suite_shared.cli_base import _opt_json, cli
from audio_suite_shared.cli_schema import build_payload
from audio_suite_shared.plugin_system import (
    default_plugin_root,
    discover,
    load_enabled_map,
    manifest_as_dict,
    save_enabled_map,
)
from audio_suite_shared.plugin_system.models import PluginState


@cli.group("plugins")
def plugins_group() -> None:
    """Inspect and enable third-party plugins discovered under ``plugins/``."""


def _plugin_entry(state: PluginState) -> dict[str, object]:
    """Return the JSON view of one discovered plugin.

    Args:
        state: The discovery state to render.

    Returns:
        A JSON-friendly mapping; ``problem`` carries a refusal reason.
    """
    entry: dict[str, object] = {
        "id": state.plugin_id,
        "name": state.name,
        "version": state.version,
        "status": state.status,
        "directory": str(state.directory),
        "problem": state.problem,
        "tool": None,
        "contributions": [],
    }
    if state.manifest is not None:
        rendered = manifest_as_dict(state.manifest)
        entry["tool"] = rendered["tool"]
        entry["contributions"] = rendered["contributions"]
    return entry


@plugins_group.command("list")
@_opt_json
def plugins_list(json: bool) -> None:
    """List every discovered plugin, its state and what it contributes.

    \b
    Examples:
        audiosuite plugins list
        audiosuite plugins list --json
    """
    started = time.monotonic()
    discovery = discover()
    entries = [_plugin_entry(state) for state in discovery.states]
    loaded = sum(1 for entry in entries if entry["status"] == "loaded")
    disabled = sum(1 for entry in entries if entry["status"] == "disabled")
    rejected = sum(1 for entry in entries if entry["status"] == "rejected")

    payload = build_payload(
        "plugins list",
        dry_run=False,
        total=len(entries),
        processed=len(entries),
        skipped=disabled,
        errors=rejected,
        duration_secs=time.monotonic() - started,
        log_entries=[],
        plugins=entries,
    )

    if json:
        click.echo(_json_mod.dumps(payload, indent=2))
        return
    if not entries:
        click.echo(f"  No plugins found in {default_plugin_root()}.")
        return
    click.echo(f"  Plugins: {loaded} loaded, {disabled} disabled, {rejected} rejected")
    for entry in entries:
        line = f"  [{entry['status']!s:<8}] {entry['id']} {entry['version']}".rstrip()
        if entry["problem"]:
            line += f" — {entry['problem']}"
        click.echo(line)


def _set_enabled(plugin_id: str, enabled: bool) -> None:
    """Enable or disable one plugin, refusing an unknown or rejected manifest.

    Args:
        plugin_id: The plugin to change.
        enabled: True to let its code run, False to stop importing it.

    Raises:
        click.UsageError: The id names no discovered plugin — a bad argument,
            so it exits with Click's usage status like any other.
        click.ClickException: The manifest is rejected, so the suite cannot
            honour what enabling it would promise.
    """
    discovery = discover()
    state = discovery.state_for(plugin_id)
    if state is None:
        # The message names no directory: a usage error is quoted in the
        # published fatal document, and a host path there would make the
        # recorded corpus machine-dependent.
        raise click.UsageError(
            f"no plugin with id {plugin_id!r}; "
            "run 'audiosuite plugins list' to see what is installed"
        )
    if state.problem is not None:
        raise click.ClickException(
            f"plugin {plugin_id!r} is rejected and cannot be enabled: {state.problem}"
        )
    current = load_enabled_map()
    current[plugin_id] = enabled
    save_enabled_map(current)


@plugins_group.command("enable")
@click.argument("plugin_id")
@_opt_json
def plugins_enable(plugin_id: str, json: bool) -> None:
    """Enable a plugin so its tools and contributions run.

    \b
    Examples:
        audiosuite plugins enable example_plugin
        audiosuite plugins enable example_plugin --json
    """
    _run_toggle(plugin_id, enabled=True, as_json=json, command="plugins enable")


@plugins_group.command("disable")
@click.argument("plugin_id")
@_opt_json
def plugins_disable(plugin_id: str, json: bool) -> None:
    """Disable a plugin without uninstalling it.

    \b
    Examples:
        audiosuite plugins disable example_plugin
        audiosuite plugins disable example_plugin --json
    """
    _run_toggle(plugin_id, enabled=False, as_json=json, command="plugins disable")


def _run_toggle(plugin_id: str, *, enabled: bool, as_json: bool, command: str) -> None:
    """Apply an enable/disable decision and publish the shared payload.

    Args:
        plugin_id: The plugin to change.
        enabled: True to enable, False to disable.
        as_json: Whether to print the JSON document.
        command: The schema command path this invocation publishes.
    """
    started = time.monotonic()
    error: str | None = None
    status = 1
    try:
        _set_enabled(plugin_id, enabled)
    except click.UsageError:
        # A mistyped id is a usage error, not a run that did work: it is
        # re-raised so the CLI publishes the standard fatal document (zero
        # counters, ``error`` only) and Click's usage status, exactly as a
        # missing argument does.
        raise
    except click.ClickException as exc:
        error = exc.message

    payload = build_payload(
        command,
        dry_run=False,
        total=1,
        processed=1,
        skipped=0,
        errors=0 if error is None else 1,
        duration_secs=time.monotonic() - started,
        log_entries=[],
        plugin=plugin_id,
        enabled=error is None and enabled,
        **({} if error is None else {"error": error}),
    )

    if as_json:
        # The JSON mode publishes exactly one document, so the human line below
        # must not follow it.
        click.echo(_json_mod.dumps(payload, indent=2))
        if error is not None:
            raise SystemExit(status)
        return
    if error is not None:
        click.echo(f"  Error: {error}", err=True)
        raise SystemExit(status)
    verb = "enabled" if enabled else "disabled"
    click.echo(f"  Plugin {plugin_id!r} {verb}; tools started from now on use it.")
