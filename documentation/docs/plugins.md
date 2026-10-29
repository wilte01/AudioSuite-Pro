# Plugin development guide

AudioSuite-Pro can load tools and analysis code that do not ship with it. A
plugin is a directory under `<suite root>/plugins/` holding a `MANIFEST.toml`
and the Python package that manifest points at.

Plugins run **in the suite's own process**, with the user's permissions and
import path. There is no sandbox: a plugin can read and write whatever the
signed-in user can. Installing one is a trust decision on the same footing as
installing a package, and enabling one is what makes its code run.

## Discovery, not import

Discovery parses every `plugins/*/MANIFEST.toml` at startup and validates it
without importing any plugin code. That is why `audiosuite doctor` and
`audiosuite plugins list` can report a plugin that will not import: the
manifest is data, and the module named by an entry point is loaded only when a
host actually calls it.

Every plugin is therefore in one of three states:

`loaded`
: The manifest parsed, the plugin is enabled, and its hosts will run it.

`disabled`
: The manifest parsed and the plugin is switched off; nothing of its code is
  imported.

`rejected`
: The manifest was refused, with a reason. A rejected plugin is listed, never
  run, and cannot be enabled.

## Switching a plugin on

Plugins are discovered always and enabled per plugin, where every other suite
preference lives — `audio_suite_config.json`, under `plugins_enabled`:

```console
audiosuite plugins list
audiosuite plugins enable my_plugin
audiosuite plugins disable my_plugin
```

A plugin absent from that map falls back to the suite's own default, which
enables only the bundled example plugin. The default lives in first-party code,
so a manifest cannot opt itself in.

## Extension points

Four surfaces exist, and each has a first-party host that really calls it:

| Surface | First-party host |
| --- | --- |
| `tool` | `audio_suite_shared.tool_plugin` (the tool registry), `audiosuite <cli_command>` and the Master Driver (toggle, arguments, card, launcher) |
| `tool.ui` | `master_driver.ui.utilities_window` / `enrich_tab`, which call the plugin's own card builder |
| `tag_processor` | `tag_field_updater.core.processor.TagProcessor`, once per file during `audiosuite tag-update` |
| `analysis` | `library_stats.core.file_processor.scan_directory`, once per file during `audiosuite stats` |

A manifest may declare any combination. A plugin that declares a surface it
does not implement is refused rather than silently degraded: the loader checks
that every entry point is `module:callable` and that the module lives inside
the plugin's own package, so a manifest cannot point at `os:system`.

## `MANIFEST.toml` reference

```toml
[plugin]
id = "my_plugin"            # required, [a-z][a-z0-9_]{0,63}
name = "My Plugin"          # required
version = "1.0.0"           # required, dotted
author = "Your Name"        # required
description = "What it does"  # required
api_version = 1             # required; the suite understands 1

[tool]
id = "my_tool"              # required within [tool], same id grammar
name = "My Tool"            # required
category = "utility"        # required: enrich, utility or refinery
description = "..."         # optional
entry_point = "my_plugin.app:main"  # optional: the CLI callable
cli_command = "my-tool"     # optional; derived as plugin-<id> if omitted
launcher = "My_Tool.pyw"    # optional: a launcher inside the plugin folder
standalone = true           # optional, default true
order = 100                 # optional, default 100 (Master Driver order)

[tool.ui]
entry = "my_plugin.ui:build"  # optional: the card builder

[[tag_processor]]
id = "my_processor"          # required
name = "My processor"        # required
entry_point = "my_plugin.tags:apply"  # required

[[analysis]]
id = "my_metric"             # required
name = "My metric"           # required
entry_point = "my_plugin.analysis:analyse"  # required
```

Rules the loader enforces, each with its own message:

* **Tables and keys are closed sets.** An unknown section or key is an error,
  not something to ignore — a typo must not silently disable a contribution.
* **The directory name is the package.** It has to be a valid Python
  identifier, because that is how the plugin's modules are imported, and it may
  not collide with a first-party package name.
* **Ids are unique.** Plugin ids and tool ids may not repeat each other or any
  first-party tool, and a contribution id may not repeat within its plugin.
* **CLI names are reserved.** `cli_command` may not take a first-party
  command name, `doctor`, `cue` or `plugins`.
* **`api_version` is exact.** A manifest written for a different API version
  is rejected with both versions named, rather than half-loaded.
* **A tool needs a surface.** `[tool]` with neither `entry_point` nor
  `launcher` is refused: the Master Driver could show a toggle that starts
  nothing.
* **The launcher stays inside the plugin.** A `launcher` path that resolves
  outside the plugin directory is refused.

## What the driver passes a launcher

A launcher opens its own window, so it receives the same four arguments the
Master Driver gives every tool:

```text
My_Tool.pyw <directory> --live|--dry --start|--no-start --end|--no-end
```

`<directory>` is the folder the driver is pointed at, `--live`/`--dry`
is its run mode, and `--start`/`--end` ask the tool to begin by itself and
to close when the run finishes. Reading them is what makes a window open on
the folder and mode the user selected; ignoring them silently opens an empty
window in the wrong mode. A plugin may ignore a flag it has no use for — it
must just do so deliberately. The example reads the grammar with
`parse_launch_args` in its `tool.py`, because the driver does not build a
plugin's arguments from a plugin's options: it sends this one grammar to every
plugin tool.

The example honours all four: it pre-fills the folder and mode, runs the report
as soon as it opens under `--start`, and closes when that run finishes under
`--end`, which is what makes it usable as a batch step. Two rules a copying
plugin should take from it:

* **Do the work off the Tk thread, but never touch Tk from it.** The example
  runs the folder walk on a `threading.Thread` and posts the result to a
  `queue.SimpleQueue` that the window polls with `root.after`. A worker
  calling `root.after` — or any widget method — itself raises
  `RuntimeError: main thread is not in main loop` and takes the window with
  it, so the poll must be started from the Tk thread and the worker's only
  shared state is the queue.
* **A failed run keeps its window open.** `--end` closes an unattended run,
  but hiding the one line that says what failed leaves the driver's process
  exiting with no output at all.

## What a contribution may return

A tag processor is called as `apply(path, dry_run)`. It may also declare a
`context` parameter to receive a
{class}`audio_suite_shared.plugin_system.PluginContext`, which reads and
writes tags through the suite's own tag layer — so a plugin does not have to
re-implement the per-format rules (and get the FLAC in-place rule wrong). It
returns `None`, a `bool`, or an object with a boolean `changed` attribute
and an optional `message`. A processor **must honour** `dry_run` by not
writing; a dry run that writes is the one defect the host cannot undo.

An analysis contribution is called as `analyse(path, tags)`, with the tags
the scan already read, and returns a mapping of metric name to `int`,
`float` or `str`. The host counts how many files produced each value and
publishes that distribution under `plugin_analysis`; a contribution that
returns anything else, or raises, is counted in `plugin_analysis_errors` and
logged, and the scan continues.

Both kinds are reported per plugin: `audiosuite tag-update --json` publishes
`plugin_updates` / `plugin_errors`, and `audiosuite stats --json`
publishes `plugin_analysis` / `plugin_analysis_errors`. The matching
`--no-plugin-tags` and `--no-plugin-analysis` flags run the tool without any
plugin contribution, which is what makes a difference between two runs
attributable.

## A first plugin

The bundled example under `plugins/example_plugin/` implements all four
extension points and is the template to copy:

```text
plugins/example_plugin/
├── MANIFEST.toml          the manifest above, filled in
├── __init__.py
├── tool.py                def main(directory, dry_run=False)
├── window.py              the launcher's window, argv pre-fill included
├── ui.py                  def build(parent, state)
├── tag_processor.py       def apply(path, dry_run, *, context)
├── analysis.py            def analyse(path, tags)
└── Example_Plugin.pyw     the standalone launcher
```

To try one, copy that directory, rename the directory and package to a new
identifier, change `[plugin].id` and every entry point, then run
`audiosuite plugins list`. A rejection names the manifest key to fix.

## Testing a plugin

Discovery can be pointed at another tree with `AUDIOSUITE_PLUGIN_DIR`, which
is what the suite's own tests use: set it to a scratch directory, call
`audio_suite_shared.plugin_system.reset_plugins_for_tests()` so the cached
registry is dropped, and the next host call discovers that tree instead. The
bundled suites for `tag_field_updater` and `library_stats` each install a
throwaway plugin this way, and read the outcome back from the file rather than
from the processor's own return value.
