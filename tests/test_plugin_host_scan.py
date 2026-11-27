"""Locks for VST3/AU discovery, metadata and the scan cache (F-M1 order #1).

The scan is the first thing the plugin subsystem does, and the only part of it
that runs before a user has chosen a plugin.  That position makes three
mistakes expensive, so each is locked here against a temporary ``.vst3`` tree:

* a scan that loads a plugin can crash the suite before the worker exists, so
  discovery must import nothing and the default route must record the bundle's
  file name;
* a scan that writes near the plugins it is reading can corrupt them, so the
  tree is byte-for-byte identical before and after;
* a cache that survives a changed tree would validate a chain against plugins
  that are no longer installed, so the key covers the folders and every
  bundle's path, mtime and size.

Metadata is read through an injected loader.  ``pedalboard`` cannot be given a
fixture it will legally load — a real plugin binary is the user's licence, and
the plan forbids both borrowing one and committing a download — so the seam is
the fake loader and the real one (``pedalboard_metadata``) is left to the
worker item, which is where a real plugin first becomes loadable under
supervision.

Changed in 3.0.0: new file — the scan, metadata and cache locks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from audio_suite_shared.plugin_host.scan import (
    CACHE_VERSION,
    PLUGIN_DIRS_ENV,
    PluginMetadata,
    PluginParameter,
    ScanRoot,
    default_scan_roots,
    path_identity,
    scan,
    standard_folders,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundle(root: Path, name: str) -> Path:
    """Create a VST3 bundle tree holding one dummy binary.

    Parameters
    ----------
    root : Path
        Folder the bundle lives in.
    name : str
        Bundle name, without the suffix.

    Returns
    -------
    Path
        The bundle directory.
    """
    bundle = root / f"{name}.vst3"
    binary = bundle / "Contents" / "x86_64-win" / f"{name}.vst3"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x00VST3" + name.encode("ascii"))
    return bundle


def _snapshot(root: Path) -> dict[str, tuple[int, str]]:
    """Return every file under *root* with its mtime and content hash.

    Parameters
    ----------
    root : Path
        Directory to snapshot.

    Returns
    -------
    dict[str, tuple[int, str]]
        Path relative to *root*, its mtime in nanoseconds and its SHA-256.
    """
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """Return a plugin folder holding two bundles and one stray folder.

    Returns
    -------
    Path
        The folder a scan is pointed at.
    """
    root = tmp_path / "plugins"
    _bundle(root, "Alpha")
    _bundle(root, "Beta")
    (root / "not_a_plugin").mkdir()
    (root / "not_a_plugin" / "readme.txt").write_text("hi", encoding="utf-8")
    return root


def _fake_loader(
    version: str = "1.0.0",
) -> tuple[list[Path], Callable[[Path], PluginMetadata]]:
    """Return a metadata loader and the list of bundles it was called for.

    Parameters
    ----------
    version : str
        Version string every record reports.

    Returns
    -------
    tuple[list[Path], Callable[[Path], PluginMetadata]]
        The call log and the loader itself.
    """
    calls: list[Path] = []

    def loader(bundle: Path) -> PluginMetadata:
        calls.append(bundle)
        return PluginMetadata(
            name=f"{bundle.stem} Pro",
            vendor="Fixture Audio",
            category="Fx",
            version=version,
            parameters=(
                PluginParameter(name="Mix", value=0.5),
                PluginParameter(name="Drive", value=2.0),
            ),
        )

    return calls, loader


class TestDiscovery:
    """A scan finds bundle directories and nothing else."""

    def test_two_bundles_are_found_and_sorted(self, tree: Path, tmp_path: Path) -> None:
        result = scan([ScanRoot(str(tree))], cache_path=tmp_path / "cache.json")

        assert [record.name for record in result.records] == ["Alpha", "Beta"]
        assert result.from_cache is False
        assert len(result.cache_key) == 64

    def test_a_stray_folder_is_not_a_plugin(self, tree: Path, tmp_path: Path) -> None:
        result = scan([ScanRoot(str(tree))], cache_path=tmp_path / "cache.json")

        assert "not_a_plugin" not in [record.name for record in result.records]
        assert result.problems == ()

    def test_a_bundle_path_is_itself_a_root(self, tmp_path: Path) -> None:
        bundle = _bundle(tmp_path / "plugins", "Solo")

        result = scan([ScanRoot(str(bundle))], cache_path=tmp_path / "cache.json")

        assert [record.name for record in result.records] == ["Solo"]
        assert result.records[0].path == str(bundle)

    def test_a_missing_folder_is_empty_not_an_error(self, tmp_path: Path) -> None:
        result = scan(
            [ScanRoot(str(tmp_path / "absent"))], cache_path=tmp_path / "cache.json"
        )

        assert result.records == ()
        assert result.from_cache is False

    def test_duplicate_roots_find_one_record(self, tree: Path, tmp_path: Path) -> None:
        result = scan(
            [ScanRoot(str(tree)), ScanRoot(str(tree))],
            cache_path=tmp_path / "cache.json",
        )

        assert len(result.records) == 2

    def test_records_are_sorted_case_insensitively(self, tmp_path: Path) -> None:
        root = tmp_path / "plugins"
        _bundle(root, "beta")
        _bundle(root, "Alpha")

        result = scan([ScanRoot(str(root))], cache_path=tmp_path / "cache.json")

        assert [record.name for record in result.records] == ["Alpha", "beta"]


class TestMetadata:
    """Metadata comes from the loader when given, the file name otherwise."""

    def test_default_route_names_the_file_and_imports_nothing(
        self, tree: Path, tmp_path: Path
    ) -> None:
        result = scan([ScanRoot(str(tree))], cache_path=tmp_path / "cache.json")

        assert {record.metadata_source for record in result.records} == {"filename"}
        assert {record.vendor for record in result.records} == {""}
        assert {record.parameters for record in result.records} == {()}

    def test_the_loader_fills_name_vendor_version_and_parameters(
        self, tree: Path, tmp_path: Path
    ) -> None:
        calls, loader = _fake_loader()

        result = scan(
            [ScanRoot(str(tree))],
            loader=loader,
            cache_path=tmp_path / "cache.json",
        )

        assert len(calls) == 2
        record = result.record_for(tree / "Alpha.vst3")
        assert record is not None
        assert record.name == "Alpha Pro"
        assert record.vendor == "Fixture Audio"
        assert record.category == "Fx"
        assert record.version == "1.0.0"
        assert record.metadata_source == "loader"
        assert [parameter.name for parameter in record.parameters] == ["Mix", "Drive"]
        assert record.identifier == "Fixture Audio/Alpha Pro"

    def test_a_failing_loader_keeps_the_plugin_visible_and_leaks_no_path(
        self, tree: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        def refusing(bundle: Path) -> PluginMetadata:
            raise RuntimeError(f"cannot load {bundle}")

        with caplog.at_level(logging.WARNING):
            result = scan(
                [ScanRoot(str(tree))],
                loader=refusing,
                cache_path=tmp_path / "cache.json",
            )

        assert len(result.records) == 2
        assert {record.problem for record in result.records} == {
            "metadata could not be read: RuntimeError"
        }
        assert str(tree) not in caplog.text
        assert "Alpha" in caplog.text

    def test_a_loader_that_reports_nothing_falls_back_to_the_file_name(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "plugins"
        _bundle(root, "Anonymous")

        def blank(_bundle_path: Path) -> PluginMetadata:
            return PluginMetadata(name="   ")

        result = scan(
            [ScanRoot(str(root))],
            loader=blank,
            cache_path=tmp_path / "cache.json",
        )

        assert result.records[0].name == "Anonymous"
        assert result.records[0].metadata_source == "loader"


class TestNothingIsWrittenToThePluginTree:
    """A scan reads plugins; it never writes beside them."""

    def test_the_tree_is_identical_after_a_scan(
        self, tree: Path, tmp_path: Path
    ) -> None:
        before = _snapshot(tree)

        scan([ScanRoot(str(tree))], cache_path=tmp_path / "cache.json")

        assert _snapshot(tree) == before

    def test_a_scan_with_metadata_writes_only_the_cache(
        self, tree: Path, tmp_path: Path
    ) -> None:
        before = _snapshot(tree)
        _calls, loader = _fake_loader()

        scan(
            [ScanRoot(str(tree))],
            loader=loader,
            cache_path=tmp_path / "cache.json",
        )

        assert _snapshot(tree) == before
        assert sorted(path.name for path in tmp_path.iterdir()) == [
            "cache.json",
            "plugins",
        ]


class TestCache:
    """The cache describes the tree it was written for, or it is ignored."""

    def test_a_matching_cache_is_reused_without_calling_the_loader(
        self, tree: Path, tmp_path: Path
    ) -> None:
        calls, loader = _fake_loader()
        cache = tmp_path / "cache.json"

        first = scan([ScanRoot(str(tree))], loader=loader, cache_path=cache)
        calls.clear()
        second = scan([ScanRoot(str(tree))], loader=loader, cache_path=cache)

        assert first.from_cache is False
        assert second.from_cache is True
        assert calls == []
        assert second.records == first.records

    def test_refresh_rebuilds_and_rewrites(self, tree: Path, tmp_path: Path) -> None:
        calls, loader = _fake_loader()
        cache = tmp_path / "cache.json"
        scan([ScanRoot(str(tree))], loader=loader, cache_path=cache)
        calls.clear()

        result = scan(
            [ScanRoot(str(tree))],
            loader=loader,
            cache_path=cache,
            refresh=True,
        )

        assert result.from_cache is False
        assert len(calls) == 2

    def test_the_cache_document_carries_the_key_and_schema(
        self, tree: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache.json"
        result = scan([ScanRoot(str(tree))], cache_path=cache)

        document = json.loads(cache.read_text(encoding="utf-8"))

        assert document["version"] == CACHE_VERSION
        assert document["key"] == result.cache_key
        assert len(document["records"]) == 2

    def test_a_corrupt_cache_is_rebuilt(self, tree: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        cache.write_text("{not json", encoding="utf-8")

        result = scan([ScanRoot(str(tree))], cache_path=cache)

        assert result.from_cache is False
        assert [record.name for record in result.records] == ["Alpha", "Beta"]

    def test_an_unreadable_cache_is_ignored(self, tree: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        cache.write_text(
            json.dumps({"version": CACHE_VERSION, "key": "other", "records": []}),
            encoding="utf-8",
        )

        result = scan([ScanRoot(str(tree))], cache_path=cache)

        assert result.from_cache is False
        assert len(result.records) == 2


class TestCacheKeyTracksTheTree:
    """Adding a folder, or a plugin, or removing one changes the key."""

    def test_adding_a_folder_changes_the_key(self, tree: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        first = scan([ScanRoot(str(tree))], cache_path=cache)
        second = scan(
            [ScanRoot(str(tree)), ScanRoot(str(tmp_path / "other"))],
            cache_path=cache,
        )

        assert second.cache_key != first.cache_key
        assert second.from_cache is False
        assert second.records == first.records

    def test_adding_a_plugin_changes_the_key(self, tree: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        first = scan([ScanRoot(str(tree))], cache_path=cache)
        _bundle(tree, "Gamma")

        second = scan([ScanRoot(str(tree))], cache_path=cache)

        assert second.cache_key != first.cache_key
        assert [record.name for record in second.records] == [
            "Alpha",
            "Beta",
            "Gamma",
        ]

    def test_removing_a_plugin_changes_the_key_and_drops_the_record(
        self, tree: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache.json"
        first = scan([ScanRoot(str(tree))], cache_path=cache)
        (tree / "Beta.vst3" / "Contents" / "x86_64-win" / "Beta.vst3").unlink()
        (tree / "Beta.vst3" / "Contents" / "x86_64-win").rmdir()
        (tree / "Beta.vst3" / "Contents").rmdir()
        (tree / "Beta.vst3").rmdir()

        second = scan([ScanRoot(str(tree))], cache_path=cache)

        assert second.cache_key != first.cache_key
        assert [record.name for record in second.records] == ["Alpha"]
        assert second.record_for(tree / "Beta.vst3") is None

    def test_editing_a_bundle_changes_the_key(self, tree: Path, tmp_path: Path) -> None:
        cache = tmp_path / "cache.json"
        first = scan([ScanRoot(str(tree))], cache_path=cache)
        binary = tree / "Alpha.vst3" / "Contents" / "x86_64-win" / "Alpha.vst3"
        binary.write_bytes(b"\x00VST3 changed")

        second = scan([ScanRoot(str(tree))], cache_path=cache)

        assert second.cache_key != first.cache_key
        assert second.from_cache is False


class TestNoPluginIsLoaded:
    """A default scan in a fresh interpreter never imports ``pedalboard``."""

    def test_discovery_imports_no_plugin_library(
        self, tree: Path, tmp_path: Path
    ) -> None:
        cache = tmp_path / "cache.json"
        source = (
            "import sys\n"
            "from audio_suite_shared.plugin_host.scan import ScanRoot, scan\n"
            f"result = scan([ScanRoot({str(tree)!r})], cache_path=__import__(\n"
            f"    'pathlib').Path({str(cache)!r}))\n"
            "assert len(result.records) == 2, len(result.records)\n"
            "assert 'pedalboard' not in sys.modules, sorted(sys.modules)\n"
            "print('ok')\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)

        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-B", "-c", source],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "ok"


class TestStandardFolders:
    """The three standard locations are a table, and every row is checked."""

    def test_windows_uses_program_files_and_local_app_data(self) -> None:
        home = Path("C:/Users/me")
        roots = standard_folders(
            "win32",
            environ={
                "PROGRAMFILES": "C:/Program Files",
                "LOCALAPPDATA": "C:/Users/me/AppData/Local",
            },
            home=home,
        )

        assert [root.path for root in roots] == [
            str(Path("C:/Program Files") / "Common Files" / "VST3"),
            str(Path("C:/Users/me/AppData/Local") / "Programs" / "Common" / "VST3"),
        ]
        assert {root.kind for root in roots} == {"vst3"}

    def test_macos_lists_vst3_and_audio_units_for_both_users(self) -> None:
        home = Path("/Users/me")
        roots = standard_folders("darwin", environ={}, home=home)

        assert [root.path for root in roots] == [
            str(Path("/Library/Audio/Plug-Ins/VST3")),
            str(home / "Library/Audio/Plug-Ins/VST3"),
            str(Path("/Library/Audio/Plug-Ins/Components")),
            str(home / "Library/Audio/Plug-Ins/Components"),
        ]
        assert [root.kind for root in roots] == ["vst3", "vst3", "au", "au"]

    def test_an_unset_base_is_left_out_not_built_from_nothing(self) -> None:
        assert standard_folders("win32", environ={}, home=Path("C:/Users/me")) == ()

    def test_an_unsupported_platform_has_no_standard_folder(self) -> None:
        assert standard_folders("linux", environ={}, home=Path("/home/me")) == ()


class TestUserFolders:
    """The environment override adds folders without duplicating one."""

    def test_the_override_adds_a_folder(self, tmp_path: Path) -> None:
        extra = tmp_path / "Extra Plugins"
        extra.mkdir()

        roots = default_scan_roots(
            platform="linux",
            environ={PLUGIN_DIRS_ENV: str(extra)},
            home=tmp_path,
        )

        assert [root.path for root in roots] == [str(extra)]
        assert roots[0].kind == "vst3"

    def test_the_override_accepts_a_bundle_path(self, tmp_path: Path) -> None:
        bundle = _bundle(tmp_path / "plugins", "Solo")

        roots = default_scan_roots(
            platform="linux",
            environ={PLUGIN_DIRS_ENV: str(bundle)},
            home=tmp_path,
        )

        assert [root.kind for root in roots] == ["vst3"]

    def test_a_repeated_override_is_listed_once(self, tmp_path: Path) -> None:
        extra = tmp_path / "Extra"

        roots = default_scan_roots(
            platform="linux",
            environ={PLUGIN_DIRS_ENV: os.pathsep.join([str(extra), str(extra)])},
            home=tmp_path,
        )

        assert len(roots) == 1

    def test_an_empty_override_adds_nothing(self, tmp_path: Path) -> None:
        roots = default_scan_roots(
            platform="linux", environ={PLUGIN_DIRS_ENV: ""}, home=tmp_path
        )

        assert roots == ()


class TestPathIdentity:
    """A slot and a scan record compare the same path either way."""

    def test_a_relative_and_absolute_path_are_one_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        assert path_identity("plugins/Alpha.vst3") == path_identity(
            tmp_path / "plugins" / "Alpha.vst3"
        )
