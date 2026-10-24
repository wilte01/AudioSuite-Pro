"""example_plugin — the AudioSuite-Pro example plugin.

This package is both a working plugin and the template a third-party developer
copies.  Its ``MANIFEST.toml`` contributes one of each extension point:

* ``tool`` — ``Example Tool``, launched from the Master Driver's Utilities tab
  and available as ``audiosuite example <dir>``;
* ``ui`` — the tool's own card, so the plugin renders the Master Driver UI
  rather than relying on the generic fallback card;
* ``tag_processor`` — runs over every file ``audiosuite tag-update`` visits;
* ``analysis`` — runs over every file a Library Statistics full scan reads.

Nothing here is imported until the plugin is enabled and a host runs one of the
contributions.

Changed in 2.1.0: new package — the example plugin (Sprint 7, Item 7.2).
"""

from __future__ import annotations
