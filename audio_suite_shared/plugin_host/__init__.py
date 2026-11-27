"""plugin_host — host third-party VST3/AU plugins in an offline chain.

This package is the plumbing a plugin chain needs before any audio is touched:

.. code-block:: python

    from audio_suite_shared.plugin_host import PluginChain, scan

    result = scan()
    chain = PluginChain.from_preset(saved_chain)
    chain.validate(result).raise_if_invalid()

* :mod:`~audio_suite_shared.plugin_host.scan` finds installed bundles and caches
  their metadata, without loading a plugin unless asked to;
* :mod:`~audio_suite_shared.plugin_host.chain` holds the ordered slots and
  validates them against a scan;
* :mod:`~audio_suite_shared.plugin_host.state` saves a plugin's own state
  versioned, so a plugin update is reported rather than mis-loaded;
* :mod:`~audio_suite_shared.plugin_host.render` applies the active slots to a
  decoded buffer, in order, and returns the caller's own buffer when every slot
  is bypassed;
* :mod:`~audio_suite_shared.plugin_host.runner` runs the render in a worker
  process per file, so a plugin that crashes costs one file, not the batch;
* :mod:`~audio_suite_shared.plugin_host.worker` is that process's entry point.

Nothing in this package imports ``pedalboard`` at import time, so a tool can
describe a chain without paying for the plugin host; the worker pays it in its
own process.

Changed in 3.0.0: new package — the plugin host's public surface (F-M1
order-of-work #1).
Changed in 3.0.0: gains the render layer, the worker and its parent runner
(F-M1 order-of-work #2).
"""

from __future__ import annotations

from audio_suite_shared.plugin_host.chain import (
    CHAIN_PRESET_VERSION,
    ChainPresetError,
    ChainProblem,
    ChainValidation,
    ChainValidationError,
    PluginChain,
    PluginSlot,
)
from audio_suite_shared.plugin_host.render import (
    PluginLoadError,
    PluginRenderError,
    SlotEffect,
    render_buffer,
)
from audio_suite_shared.plugin_host.runner import (
    DEFAULT_TIMEOUT_SECONDS,
    RENDERED,
    WORKER_MODULE,
    RenderOutcome,
    render_file,
    render_files,
)
from audio_suite_shared.plugin_host.scan import (
    AU_SUFFIX,
    CACHE_VERSION,
    DEFAULT_CACHE_FILENAME,
    PLUGIN_DIRS_ENV,
    STANDARD_FOLDERS,
    VST3_SUFFIX,
    MetadataLoader,
    PluginFolder,
    PluginMetadata,
    PluginParameter,
    PluginRecord,
    ScanResult,
    ScanRoot,
    default_cache_path,
    default_scan_roots,
    path_identity,
    pedalboard_metadata,
    scan,
    standard_folders,
)
from audio_suite_shared.plugin_host.state import (
    STATE_FORMAT_VERSION,
    PluginStateBlob,
    PluginStateError,
    PluginStateMismatch,
    capture_state,
    require_compatible,
)

__all__ = [
    "AU_SUFFIX",
    "CACHE_VERSION",
    "CHAIN_PRESET_VERSION",
    "DEFAULT_CACHE_FILENAME",
    "DEFAULT_TIMEOUT_SECONDS",
    "PLUGIN_DIRS_ENV",
    "RENDERED",
    "STANDARD_FOLDERS",
    "STATE_FORMAT_VERSION",
    "VST3_SUFFIX",
    "WORKER_MODULE",
    "ChainPresetError",
    "ChainProblem",
    "ChainValidation",
    "ChainValidationError",
    "MetadataLoader",
    "PluginChain",
    "PluginFolder",
    "PluginLoadError",
    "PluginMetadata",
    "PluginParameter",
    "PluginRecord",
    "PluginRenderError",
    "PluginSlot",
    "PluginStateBlob",
    "PluginStateError",
    "PluginStateMismatch",
    "RenderOutcome",
    "ScanResult",
    "ScanRoot",
    "SlotEffect",
    "capture_state",
    "default_cache_path",
    "default_scan_roots",
    "path_identity",
    "pedalboard_metadata",
    "render_buffer",
    "render_file",
    "render_files",
    "require_compatible",
    "scan",
    "standard_folders",
]
