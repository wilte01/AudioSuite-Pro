"""A downstream consumer of :mod:`audio_suite_shared`, type-checked by mypy.

This module is not part of the product and nothing imports it at runtime: it
exists so the shared package's annotations are proven usable from *outside* the
tree. ``assert_type`` fails under mypy when an annotation is missing or has
drifted to ``Any``, which is exactly what a downstream caller would see, and
the assertions run as no-ops if anything ever does import the module.

It lives outside ``tests/`` on purpose: ``[tool.mypy] exclude`` drops that
tree, so a fixture there would be invisible to the bare ``mypy .`` gate and
the "checked by mypy" claim would rest on one test's subprocess alone.

Changed in 2.4.3: added as the WP-10 C-I6 consumer fixture, checked by the
bare gate and by ``tests/test_py_typed.py``.
"""

from __future__ import annotations

from typing import assert_type

from audio_suite_shared.audio_formats import (
    SUPPORTED_EXTENSIONS,
    get_export_args,
    is_lossless_extension,
)
from audio_suite_shared.suite_config import load_last_directory, load_value


def consume() -> None:
    """Touch the public signatures a downstream caller relies on."""
    assert_type(load_last_directory(), str)
    assert_type(load_value("typing_consumer", 0), object)
    assert_type(SUPPORTED_EXTENSIONS, tuple[str, ...])
    assert_type(get_export_args(".flac"), tuple[str, list[str]])
    assert_type(is_lossless_extension("song.flac"), bool)
