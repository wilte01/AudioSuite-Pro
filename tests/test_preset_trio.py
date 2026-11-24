"""Lock every window's preset adoption and the keys its presets store.

``tests/test_suite_app_contract.py`` holds each ``SuiteApp`` adopter to the
shell's tabs, wire buttons and run report, but a preset is a config key rather
than a widget, so that contract cannot see one.  This lock can:

* every window that offers a preset row must resolve select / save / delete to
  the shell's trio - a fourth local copy fails here;
* every stored key list is frozen.  A renamed key would orphan the presets a
  user already saved, and a reordered one would change the order a preset file
  is written in, so both are pinned per window;
* a window with its own settings mapping (the Refinery's config dataclass,
  BPM's default-filling apply) must keep declaring that mapping, rather than
  silently inheriting the shell's five fields.

The scan reads the tree the way the shared-code lock does: no app module is
imported, so a heavy GUI dependency cannot make the lock vacuous by failing to
import.

Changed in 2.9.0: new file.  D56 gave the shell the preset trio; this pins the
fifteen windows that adopted it, their store and their stored keys (D58).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from audio_suite_shared.suite_app import SuiteApp

#: Module path -> ``(class name, store prefix, own mapping, stored keys)``.
#: Empty store prefix means the shared ``presets`` block; a prefix means the
#: older ``<prefix>_preset_<name>`` keys.  ``own mapping`` means the window
#: keeps its own ``_collect_settings``/``_apply_preset`` (so ``keys`` is None
#: and its package tests pin the values).
ADOPTERS: dict[str, tuple[str, str, bool, tuple[str, ...] | None]] = {
    "album_art_sync/app.py": (
        "AudioSuiteV6",
        "",
        False,
        ("execution_mode", "embedded_resolution", "purge_hidden"),
    ),
    "album_genre_tagger/app.py": (
        "GenreConsolidatorApp",
        "",
        False,
        ("run_mode", "min_coverage"),
    ),
    "asx_extractor/app.py": ("ASXExtractorTool", "", False, ("run_mode",)),
    "audio_refinery/app.py": ("AudioRefineryApp", "", True, None),
    "bpm_analyzer/app.py": ("BPMAnalyzerApp", "bpm", True, None),
    "duplicate_finder/ui/app.py": (
        "DuplicateFinderApp",
        "duplicate_finder",
        True,
        None,
    ),
    "file_reorganizer/app.py": ("FileReorganizerApp", "", True, None),
    "genre_sync/app.py": ("GenreSetterApp", "", False, ("run_mode",)),
    "key_detector/app.py": (
        "KeyDetectorApp",
        "",
        False,
        (
            "folder_path",
            "run_mode",
            "analysis_duration",
            "parallel_mode",
            "max_workers",
        ),
    ),
    "lyrics_manager/app.py": ("LyricsManagerApp", "lyrics", True, None),
    "metadata_scrubber/app.py": (
        "MetadataScrubberApp",
        "",
        False,
        (
            "run_mode",
            "preserve_lyrics",
            "preserve_album_artist",
            "preserve_embedded_art",
        ),
    ),
    "mood_analyzer/app.py": (
        "MoodAnalyzerApp",
        "",
        False,
        (
            "folder_path",
            "run_mode",
            "analysis_duration",
            "parallel_mode",
            "max_workers",
        ),
    ),
    "mood_analysis_batch_tagger/app.py": (
        "MoodAnalysisBatchTaggerApp",
        "",
        False,
        ("root_path", "run_mode", "analysis_duration", "parallel_mode", "max_workers"),
    ),
    "music_format_converter/app.py": (
        "MusicFormatConverterApp",
        "",
        False,
        (
            "output_format",
            "quality_preset",
            "sample_rate",
            "bit_depth",
            "delete_originals",
            "normalize_mp3",
            "target_lufs",
            "dither",
            "run_mode",
        ),
    ),
    "replaygain_analyzer/app.py": (
        "ReplayGainAnalyzerApp",
        "",
        False,
        ("target_lufs", "run_mode"),
    ),
    "restoration/ui/app.py": ("RestorationApp", "restoration", True, None),
    "tempo_analyzer/app.py": (
        "TempoAnalyzerApp",
        "",
        False,
        ("tempo_scheme", "run_mode"),
    ),
}

_TRIO = ("use_preset", "store_preset", "remove_preset")


def _module_paths() -> list[Path]:
    return [*sorted(Path(".").glob("*/app.py")), *sorted(Path(".").glob("*/ui/app.py"))]


def _shell_classes(path: Path) -> dict[str, ast.ClassDef]:
    """Return the ``SuiteApp`` subclasses *path* declares, by name."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and "SuiteApp" in [ast.unparse(base) for base in node.bases]
    }


def _offers_a_preset_row(node: ast.ClassDef) -> bool:
    """Whether the window wires a preset row or declares its settings."""
    source = ast.unparse(node)
    return any(name in source for name in _TRIO) or any(
        name in source
        for name in ("PRESET_FIELDS", "_collect_settings", "_save_current_as_preset")
    )


def _discovered() -> dict[str, tuple[str, ast.ClassDef]]:
    found: dict[str, tuple[str, ast.ClassDef]] = {}
    for path in _module_paths():
        for name, node in _shell_classes(path).items():
            if _offers_a_preset_row(node):
                found[path.as_posix()] = (name, node)
    return found


def _class_value(module: ast.Module, node: ast.ClassDef, name: str) -> object:
    """Return the literal assigned to *name* in *node*'s body, or None."""
    for stmt in node.body:
        target: str | None = None
        value: ast.expr | None = None
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            if isinstance(stmt.targets[0], ast.Name):
                target, value = stmt.targets[0].id, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            target, value = stmt.target.id, stmt.value
        if target != name or value is None:
            continue
        if isinstance(value, ast.Name):
            for module_stmt in module.body:
                if (
                    isinstance(module_stmt, ast.Assign)
                    and len(module_stmt.targets) == 1
                ):
                    assigned = module_stmt.targets[0]
                    if isinstance(assigned, ast.Name) and assigned.id == value.id:
                        return ast.literal_eval(module_stmt.value)
            raise AssertionError(f"{name} refers to an unresolved module constant")
        return ast.literal_eval(value)
    return None


def _stored_keys(module: ast.Module, node: ast.ClassDef) -> tuple[str, ...]:
    """Return the keys the window's declarative mapping stores, in order."""
    fields = _class_value(module, node, "PRESET_FIELDS")
    if fields is None:
        fields = SuiteApp.PRESET_FIELDS
    aliases = _class_value(module, node, "PRESET_ALIASES") or {}
    by_attribute = {attribute: key for key, attribute in dict(aliases).items()}
    return tuple(by_attribute.get(field, field) for field in fields)


def test_the_table_covers_every_window_that_offers_a_preset_row() -> None:
    found = _discovered()
    assert found, "the scan found no adopter at all"
    assert {path: name for path, (name, _) in found.items()} == {
        path: row[0] for path, row in ADOPTERS.items()
    }


@pytest.mark.parametrize("path", sorted(ADOPTERS))
def test_the_window_uses_the_shell_trio(path: str) -> None:
    node = _shell_classes(Path(path))[ADOPTERS[path][0]]
    local = {
        stmt.name for stmt in node.body if isinstance(stmt, ast.FunctionDef)
    } & set(_TRIO)
    assert not local, f"{path} still defines {sorted(local)}"


@pytest.mark.parametrize("path", sorted(ADOPTERS))
def test_the_window_keeps_its_frozen_stored_keys(path: str) -> None:
    class_name, prefix, own_mapping, keys = ADOPTERS[path]
    module = ast.parse(Path(path).read_text(encoding="utf-8"))
    node = _shell_classes(Path(path))[class_name]
    methods = {stmt.name for stmt in node.body if isinstance(stmt, ast.FunctionDef)}

    assert _class_value(module, node, "PRESET_KEY_PREFIX") or "" == prefix
    if own_mapping:
        assert {"_collect_settings", "_apply_preset"} <= methods, (
            f"{path} stopped declaring its own mapping"
        )
        return

    assert not ({"_collect_settings", "_apply_preset"} & methods), (
        f"{path} declares a mapping the shell already implements"
    )
    assert _stored_keys(module, node) == keys
