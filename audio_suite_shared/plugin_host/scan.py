"""scan.py — discovery, metadata and cache for installed VST3/AU plugins.

The suite hosts third-party audio plugins through ``pedalboard``, which knows
nothing about where a plugin lives: it takes a bundle path and loads it.  This
module supplies the missing half — the folders to look in, what each bundle is
called, and a cache so a chain can be validated without loading anything.

Three rules shape the code, and each is a test in
``tests/test_plugin_host_scan.py``:

* **Discovery reads the filesystem, never audio.**  A scan walks bundle
  directories and stats their files.  ``pedalboard`` is not imported and no
  plugin is instantiated unless the caller passes a metadata ``loader``, so
  scanning a folder of plugins cannot start an audio callback or write a file.
* **Metadata is opt-in and recorded.**  ``metadata_source`` says whether a
  record's name, vendor and parameters came from the loader or from the bundle's
  file name.  A scan that instantiates every bundle can crash the process on a
  broken plugin (the reason rendering moves to a worker, F-M1 D-1), so the safe
  route is the default and the richer one is named per record.
* **Paths stay in the cache.**  Every message and log line here names a plugin
  by its file name, because a plugin path can carry a user's folder layout into
  a report the suite publishes.  The cache file itself holds absolute paths,
  which is what the cache is for.

The cache is keyed by the scanned folders *and* every bundle's
``(path, mtime, size)``: adding a folder, adding a plugin, removing one or
editing a bundle all change the key, so a stale cache can never describe a tree
that no longer exists.  A cache that cannot be read is rebuilt rather than
reported — it is a convenience, not user data.

Changed in 3.0.0: new module — VST3/AU discovery, metadata and the scan cache
(F-M1 order-of-work #1).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_suite_shared.suite_paths import suite_path

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Environment override listing extra plugin folders, separated by
#: :data:`os.pathsep`.  It mirrors ``AUDIOSUITE_PLUGIN_DIR``: a test, a portable
#: install or a producer with plugins on another drive points the scan where it
#: wants without editing the platform table.
PLUGIN_DIRS_ENV = "AUDIOSUITE_AUDIO_PLUGIN_DIRS"

#: Schema version of the cache document.  A file written by another version is
#: ignored, so an older cache cannot be read with the wrong field meanings.
CACHE_VERSION = 1

#: Cache file name, resolved against
#: :func:`audio_suite_shared.suite_paths.suite_path`.
DEFAULT_CACHE_FILENAME = "audio_plugin_scan.json"

#: Steinberg's bundle suffix.  The bundle is a directory holding a platform
#: binary, not the binary itself.
VST3_SUFFIX = ".vst3"

#: Apple's Audio Unit bundle suffix (macOS only).
AU_SUFFIX = ".component"


@dataclass(frozen=True)
class PluginFolder:
    """One row of the standard plugin-folder table.

    Attributes
    ----------
    platform : str
        The :data:`sys.platform` value this row applies to (``"win32"``,
        ``"darwin"``); other platforms have no standard folder.
    base : str
        Where the relative path starts: ``"program_files"``,
        ``"local_app_data"``, ``"home"`` or ``"root"``.
    relative : str
        The path below the base, written with ``/`` separators on every
        platform.
    kind : str
        ``"vst3"`` or ``"au"`` — the bundle format this folder holds.
    """

    platform: str
    base: str
    relative: str
    kind: str


#: The standard locations, in the order a scan visits them.  The audit names
#: these three explicitly (F-M1 risk 3); a fourth location is a new row with a
#: test, never a string in a function.
STANDARD_FOLDERS: tuple[PluginFolder, ...] = (
    PluginFolder("win32", "program_files", "Common Files/VST3", "vst3"),
    PluginFolder("win32", "local_app_data", "Programs/Common/VST3", "vst3"),
    PluginFolder("darwin", "root", "Library/Audio/Plug-Ins/VST3", "vst3"),
    PluginFolder("darwin", "home", "Library/Audio/Plug-Ins/VST3", "vst3"),
    PluginFolder("darwin", "root", "Library/Audio/Plug-Ins/Components", "au"),
    PluginFolder("darwin", "home", "Library/Audio/Plug-Ins/Components", "au"),
)


@dataclass(frozen=True)
class ScanRoot:
    """One folder a scan visits.

    Attributes
    ----------
    path : str
        Folder path.  A path that is itself a ``.vst3``/``.component`` bundle is
        scanned as that bundle, which is how a user adds a single plugin.
    kind : str
        ``"vst3"`` or ``"au"`` — informational; discovery recognises both
        suffixes in any root, because a user path may hold either.
    """

    path: str
    kind: str = "vst3"


@dataclass(frozen=True)
class PluginParameter:
    """One automatable parameter a plugin reports.

    Attributes
    ----------
    name : str
        The plugin's own parameter name.
    value : float
        The value the plugin reported when the scan read its metadata.
    """

    name: str
    value: float


@dataclass(frozen=True)
class PluginMetadata:
    """What a metadata loader reports about one bundle.

    Attributes
    ----------
    name : str
        Display name.  A loader that cannot read it may leave the bundle name.
    vendor : str
        Manufacturer, or ``""`` when the plugin does not say.
    category : str
        The plugin's own category string, or ``""``.
    version : str
        The plugin's version string, or ``""``.  A state blob compares this so
        an update is refused rather than mis-loaded.
    parameters : tuple[PluginParameter, ...]
        Parameters in the plugin's order, or ``()``.
    """

    name: str
    vendor: str = ""
    category: str = ""
    version: str = ""
    parameters: tuple[PluginParameter, ...] = ()


#: A callable that reads one bundle's metadata.  The default scan route takes
#: ``None``, which records the bundle's file name and imports nothing; the tests
#: inject a fake and :func:`pedalboard_metadata` is the real one.
MetadataLoader = Callable[[Path], PluginMetadata]


@dataclass(frozen=True)
class PluginRecord:
    """One discovered bundle, as the scan cache stores it.

    Attributes
    ----------
    name : str
        Display name: the loader's, or the bundle's file name.
    vendor : str
        Manufacturer, or ``""``.
    category : str
        The plugin's category, or ``""``.
    version : str
        The plugin's version, or ``""``.
    path : str
        Absolute bundle path.  Chain validation compares it; no message built
        from this record includes it.
    metadata_source : str
        ``"loader"`` when the metadata came from an injected loader,
        ``"filename"`` when discovery used the bundle's name only.
    parameters : tuple[PluginParameter, ...]
        Parameters the loader reported, or ``()``.
    problem : str | None
        Why the metadata could not be read, when a loader failed.  Chain
        validation refuses a record carrying one.
    """

    name: str
    vendor: str
    category: str
    version: str
    path: str
    metadata_source: str
    parameters: tuple[PluginParameter, ...]
    problem: str | None = None

    @property
    def identifier(self) -> str:
        """Return the path-independent identity a saved state compares.

        Returns
        -------
        str
            ``"<vendor>/<name>"``, or the name alone when the plugin reports no
            vendor.  It survives the plugin being moved, which a path does not.
        """
        return f"{self.vendor}/{self.name}" if self.vendor else self.name


@dataclass(frozen=True)
class ScanResult:
    """The outcome of one scan pass.

    Attributes
    ----------
    records : tuple[PluginRecord, ...]
        Discovered plugins, sorted by display name and then vendor.
    cache_key : str
        SHA-256 of the folders and bundle fingerprints; two passes with the
        same key describe the same tree.
    from_cache : bool
        True when the records were read from a cache file whose key matched,
        False when they were built by walking the folders.
    """

    records: tuple[PluginRecord, ...]
    cache_key: str
    from_cache: bool

    @property
    def problems(self) -> tuple[PluginRecord, ...]:
        """Return the records whose metadata a loader could not read."""
        return tuple(record for record in self.records if record.problem is not None)

    def record_for(self, plugin_path: str | Path) -> PluginRecord | None:
        """Return the record for *plugin_path*, or None when it is not installed.

        Parameters
        ----------
        plugin_path : str | Path
            The bundle path a chain slot names.

        Returns
        -------
        PluginRecord | None
            The matching record.  Comparison is case-insensitive on Windows,
            because the filesystem is.
        """
        wanted = path_identity(plugin_path)
        for record in self.records:
            if path_identity(record.path) == wanted:
                return record
        return None


@dataclass(frozen=True)
class _Bundle:
    """A bundle found on disk, before its metadata is read."""

    path: Path
    mtime_ns: int
    size: int


def path_identity(plugin_path: str | Path) -> str:
    """Return a comparable identity for a bundle path.

    Parameters
    ----------
    plugin_path : str | Path
        Path to normalise.  It need not exist.

    Returns
    -------
    str
        The absolute path, case-folded on Windows so two spellings of one
        plugin are one plugin.
    """
    absolute = os.path.abspath(os.path.expanduser(str(plugin_path)))
    return os.path.normcase(absolute)


def standard_folders(
    platform: str | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[ScanRoot, ...]:
    """Return the standard plugin folders for one platform.

    Parameters
    ----------
    platform : str | None
        A :data:`sys.platform` value; ``None`` uses the running interpreter's.
    environ : Mapping[str, str] | None
        Environment to read the base variables from; ``None`` uses
        :data:`os.environ`.
    home : Path | None
        Home directory for per-user folders; ``None`` uses :func:`Path.home`.

    Returns
    -------
    tuple[ScanRoot, ...]
        The folders the table declares for *platform*, with a base whose
        environment variable is unset left out.  Duplicates are collapsed.
    """
    current = sys.platform if platform is None else platform
    environment = os.environ if environ is None else environ
    user_home = Path.home() if home is None else home
    roots: list[ScanRoot] = []
    seen: set[str] = set()
    for folder in STANDARD_FOLDERS:
        if folder.platform != current:
            continue
        base = _base_directory(folder.base, environment, user_home)
        if base is None:
            continue
        raw = base.joinpath(*folder.relative.split("/"))
        identity = path_identity(raw)
        if identity in seen:
            continue
        seen.add(identity)
        roots.append(ScanRoot(str(raw), folder.kind))
    return tuple(roots)


def default_scan_roots(
    *,
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> tuple[ScanRoot, ...]:
    """Return the folders a scan visits when the caller names none.

    The standard table comes first, then every folder listed in
    :data:`PLUGIN_DIRS_ENV`, so an explicit path cannot shadow a standard one.

    Parameters
    ----------
    platform : str | None
        A :data:`sys.platform` value; ``None`` uses the running interpreter's.
    environ : Mapping[str, str] | None
        Environment to read; ``None`` uses :data:`os.environ`.
    home : Path | None
        Home directory for per-user folders; ``None`` uses :func:`Path.home`.

    Returns
    -------
    tuple[ScanRoot, ...]
        Standard and user folders, without duplicates.
    """
    environment = os.environ if environ is None else environ
    roots = list(standard_folders(platform=platform, environ=environment, home=home))
    seen = {path_identity(root.path) for root in roots}
    for part in environment.get(PLUGIN_DIRS_ENV, "").split(os.pathsep):
        candidate = part.strip()
        if not candidate:
            continue
        expanded = Path(candidate).expanduser()
        identity = path_identity(expanded)
        if identity in seen:
            continue
        seen.add(identity)
        roots.append(ScanRoot(str(expanded), _bundle_kind(expanded) or "vst3"))
    return tuple(roots)


def default_cache_path() -> Path:
    """Return the cache file a scan writes when the caller names none.

    Returns
    -------
    Path
        ``<suite root>/audio_plugin_scan.json``.  The file is machine state, so
        it sits beside ``audio_suite_config.json`` and is gitignored, not
        shipped.
    """
    return suite_path(DEFAULT_CACHE_FILENAME)


def pedalboard_metadata(plugin_path: Path) -> PluginMetadata:
    """Read one bundle's metadata by loading it with ``pedalboard``.

    This is the real :data:`MetadataLoader`.  It instantiates the plugin, which
    is why the scan does not use it by default: a broken plugin can abort the
    process, and a scan that does so before the worker exists (F-M1 D-1) would
    take the suite with it.

    Parameters
    ----------
    plugin_path : Path
        The ``.vst3`` or ``.component`` bundle.

    Returns
    -------
    PluginMetadata
        The name, vendor, category, version and parameters the plugin reports.

    Raises
    ------
    RuntimeError
        The bundle is an Audio Unit and this is not macOS.
    Exception
        Whatever ``pedalboard`` raises for a bundle it cannot load; the scan's
        loader boundary turns that into a record with a ``problem``.
    """
    plugin = _plugin_class(_bundle_kind(plugin_path) or "vst3")(str(plugin_path))
    parameters = tuple(
        PluginParameter(name=str(name), value=float(value))
        for name, value in plugin.parameters.items()
    )
    return PluginMetadata(
        name=str(plugin.descriptive_name or plugin.name or plugin_path.stem),
        vendor=str(plugin.manufacturer_name or ""),
        category=str(plugin.category or ""),
        version=str(plugin.version or ""),
        parameters=parameters,
    )


def scan(
    roots: Sequence[ScanRoot] | None = None,
    *,
    loader: MetadataLoader | None = None,
    cache_path: Path | None = None,
    refresh: bool = False,
) -> ScanResult:
    """Discover the plugin bundles under *roots* and cache the result.

    Parameters
    ----------
    roots : Sequence[ScanRoot] | None
        Folders to visit; ``None`` uses :func:`default_scan_roots`.
    loader : MetadataLoader | None
        Reads a bundle's metadata.  ``None`` records the bundle's file name and
        imports no plugin library, which is the safe default.
    cache_path : Path | None
        Cache file to read and write; ``None`` uses :func:`default_cache_path`.
    refresh : bool
        Ignore a matching cache and rebuild the records, then rewrite the file.

    Returns
    -------
    ScanResult
        The records and the key describing the tree.  A failed metadata read is
        a record with ``problem`` set, never a missing record: the plugin still
        exists and validation must say so.
    """
    folders = tuple(roots) if roots is not None else default_scan_roots()
    bundles = _collect_bundles(folders)
    key = _cache_key(folders, bundles)
    destination = default_cache_path() if cache_path is None else cache_path

    if not refresh:
        cached = _read_cache(destination, key)
        if cached is not None:
            return ScanResult(records=cached, cache_key=key, from_cache=True)

    records = tuple(
        sorted(
            (_record_for(bundle, loader) for bundle in bundles),
            key=lambda record: (
                record.name.lower(),
                record.vendor.lower(),
                path_identity(record.path),
            ),
        )
    )
    _write_cache(destination, key, records)
    logger.info(
        "Scanned %d audio plugin(s) in %d folder(s)", len(records), len(folders)
    )
    return ScanResult(records=records, cache_key=key, from_cache=False)


def _base_directory(base: str, environ: Mapping[str, str], home: Path) -> Path | None:
    """Resolve one table row's base to a directory.

    Parameters
    ----------
    base : str
        ``"program_files"``, ``"local_app_data"``, ``"home"`` or ``"root"``.
    environ : Mapping[str, str]
        Environment holding the Windows variables.
    home : Path
        The home directory.

    Returns
    -------
    Path | None
        The base, or None when its environment variable is unset.
    """
    if base == "home":
        return home
    if base == "root":
        return Path("/")
    variable = {
        "program_files": "PROGRAMFILES",
        "local_app_data": "LOCALAPPDATA",
    }[base]
    value = environ.get(variable, "").strip()
    return Path(value) if value else None


def _bundle_kind(path: Path) -> str | None:
    """Return ``"vst3"``/``"au"`` for a bundle path, else None.

    Parameters
    ----------
    path : Path
        A file or directory name to classify.

    Returns
    -------
    str | None
        The format when the name carries the suffix, else None.
    """
    name = path.name.lower()
    if name.endswith(VST3_SUFFIX):
        return "vst3"
    if name.endswith(AU_SUFFIX):
        return "au"
    return None


def _plugin_class(bundle_format: str) -> Any:
    """Return the ``pedalboard`` class that loads *bundle_format*.

    Parameters
    ----------
    bundle_format : str
        ``"vst3"`` or ``"au"``.

    Returns
    -------
    Any
        ``pedalboard.VST3Plugin`` or ``pedalboard.AudioUnitPlugin``.

    Raises
    ------
    RuntimeError
        The format is an Audio Unit and this is not macOS.
    """
    if bundle_format == "au":
        if sys.platform != "darwin":
            raise RuntimeError("Audio Unit plugins are only available on macOS")
        from pedalboard import AudioUnitPlugin

        return AudioUnitPlugin
    from pedalboard import VST3Plugin

    return VST3Plugin


def _candidate_bundles(root: ScanRoot) -> list[Path]:
    """Return the bundles a root holds, sorted by name.

    Parameters
    ----------
    root : ScanRoot
        The folder to read.  When the root is itself a bundle it is the only
        candidate.

    Returns
    -------
    list[Path]
        Bundle directories, empty when the folder is missing or unreadable.
        A missing standard folder is normal, not an error.
    """
    directory = Path(root.path)
    if _bundle_kind(directory) is not None:
        return [directory] if directory.is_dir() else []
    try:
        entries = sorted(directory.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return []
    return [
        entry for entry in entries if entry.is_dir() and _bundle_kind(entry) is not None
    ]


def _fingerprint(bundle: Path) -> tuple[int, int]:
    """Return a bundle's ``(mtime_ns, total size)`` fingerprint.

    Parameters
    ----------
    bundle : Path
        The bundle directory.

    Returns
    -------
    tuple[int, int]
        The directory's modification time and the summed size of its files.
    """
    mtime_ns = bundle.stat().st_mtime_ns
    size = 0
    for directory, _subdirectories, files in os.walk(bundle):
        for name in files:
            try:
                size += (Path(directory) / name).stat().st_size
            except OSError:
                continue
    return mtime_ns, size


def _collect_bundles(roots: Sequence[ScanRoot]) -> tuple[_Bundle, ...]:
    """Return every bundle the roots hold, de-duplicated by path.

    Parameters
    ----------
    roots : Sequence[ScanRoot]
        Folders to visit, in order.

    Returns
    -------
    tuple[_Bundle, ...]
        The bundles, each fingerprinted.  A bundle that cannot be stat'ed is
        skipped and logged by name only.
    """
    bundles: list[_Bundle] = []
    seen: set[str] = set()
    for root in roots:
        for candidate in _candidate_bundles(root):
            identity = path_identity(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                mtime_ns, size = _fingerprint(candidate)
            except OSError as exc:
                logger.warning(
                    "%r could not be read (%s); skipped",
                    candidate.stem,
                    type(exc).__name__,
                )
                continue
            bundles.append(_Bundle(candidate, mtime_ns, size))
    return tuple(bundles)


def _cache_key(roots: Sequence[ScanRoot], bundles: Sequence[_Bundle]) -> str:
    """Return the key describing the folders and bundles a scan saw.

    Parameters
    ----------
    roots : Sequence[ScanRoot]
        Folders visited.
    bundles : Sequence[_Bundle]
        Bundles found.

    Returns
    -------
    str
        A SHA-256 hex digest.  Any added, removed or edited folder or bundle
        changes it.
    """
    document = {
        "version": CACHE_VERSION,
        "folders": [[path_identity(root.path), root.kind] for root in roots],
        "bundles": [
            [path_identity(bundle.path), bundle.mtime_ns, bundle.size]
            for bundle in bundles
        ],
    }
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_for(bundle: _Bundle, loader: MetadataLoader | None) -> PluginRecord:
    """Build one record, reading metadata only when a loader is supplied.

    Parameters
    ----------
    bundle : _Bundle
        The discovered bundle.
    loader : MetadataLoader | None
        Metadata reader, or None for the file-name route.

    Returns
    -------
    PluginRecord
        The record.  A loader failure becomes a ``problem`` on a record that
        still names the plugin.
    """
    file_name = bundle.path.stem
    metadata: PluginMetadata | None = None
    problem: str | None = None
    if loader is not None:
        try:
            metadata = loader(bundle.path)
        except Exception as exc:  # noqa: BLE001 - a third-party loader can raise
            # anything (a missing library, a refusing plugin), and the scan must
            # keep the plugin visible rather than fail the run (F-M1 order #1).
            logger.warning(
                "plugin %r could not report its metadata (%s); using its file name",
                file_name,
                type(exc).__name__,
            )
            problem = f"metadata could not be read: {type(exc).__name__}"
    headers = metadata or PluginMetadata(name=file_name)
    return PluginRecord(
        name=headers.name.strip() or file_name,
        vendor=headers.vendor.strip(),
        category=headers.category.strip(),
        version=headers.version.strip(),
        path=str(bundle.path),
        metadata_source="loader" if metadata is not None else "filename",
        parameters=tuple(headers.parameters),
        problem=problem,
    )


def _text(raw: Mapping[str, object], key: str) -> str:
    """Return a required text field from a cached record.

    Parameters
    ----------
    raw : Mapping[str, object]
        The decoded record object.
    key : str
        Field name.

    Returns
    -------
    str
        The field's value.

    Raises
    ------
    ValueError
        The field is missing or not text.
    """
    value = raw.get(key)
    if not isinstance(value, str):
        raise ValueError(f"cached plugin record field {key!r} is not text")
    return value


def _record_to_payload(record: PluginRecord) -> dict[str, object]:
    """Return a record as a JSON-friendly mapping.

    Parameters
    ----------
    record : PluginRecord
        The record to serialise.

    Returns
    -------
    dict[str, object]
        A flat mapping whose ``parameters`` holds plain objects.
    """
    return {
        "name": record.name,
        "vendor": record.vendor,
        "category": record.category,
        "version": record.version,
        "path": record.path,
        "source": record.metadata_source,
        "parameters": [
            {"name": parameter.name, "value": parameter.value}
            for parameter in record.parameters
        ],
        "problem": record.problem,
    }


def _record_from_payload(raw: object) -> PluginRecord:
    """Rebuild a record from a cached mapping.

    Parameters
    ----------
    raw : object
        One entry of the cache document's ``records`` list.

    Returns
    -------
    PluginRecord
        The rebuilt record.

    Raises
    ------
    ValueError
        The entry does not have the cached shape.
    """
    if not isinstance(raw, dict):
        raise ValueError("a cached plugin record is not an object")
    raw_parameters = raw.get("parameters", [])
    if not isinstance(raw_parameters, list):
        raise ValueError("a cached plugin record's parameters are not a list")
    parameters: list[PluginParameter] = []
    for item in raw_parameters:
        if not isinstance(item, dict):
            raise ValueError("a cached plugin parameter is not an object")
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str) or isinstance(value, bool):
            raise ValueError("a cached plugin parameter is malformed")
        if not isinstance(value, (int, float)):
            raise ValueError("a cached plugin parameter is malformed")
        parameters.append(PluginParameter(name=name, value=float(value)))
    problem = raw.get("problem")
    if problem is not None and not isinstance(problem, str):
        raise ValueError("a cached plugin record's problem is not text")
    return PluginRecord(
        name=_text(raw, "name"),
        vendor=_text(raw, "vendor"),
        category=_text(raw, "category"),
        version=_text(raw, "version"),
        path=_text(raw, "path"),
        metadata_source=_text(raw, "source"),
        parameters=tuple(parameters),
        problem=problem,
    )


def _read_cache(path: Path, key: str) -> tuple[PluginRecord, ...] | None:
    """Read a cache file when it describes *key*.

    Parameters
    ----------
    path : Path
        The cache file.
    key : str
        The key this scan computed.

    Returns
    -------
    tuple[PluginRecord, ...] | None
        The cached records, or None when the file is missing, unreadable,
        written by another schema version, or describes a different tree.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("version") != CACHE_VERSION or raw.get("key") != key:
        return None
    entries = raw.get("records")
    if not isinstance(entries, list):
        return None
    try:
        return tuple(_record_from_payload(entry) for entry in entries)
    except ValueError:
        return None


def _write_cache(path: Path, key: str, records: Sequence[PluginRecord]) -> None:
    """Write the cache atomically, reporting a failure without a path.

    Parameters
    ----------
    path : Path
        Destination file.
    key : str
        The key this scan computed.
    records : Sequence[PluginRecord]
        Records to store.
    """
    document = {
        "version": CACHE_VERSION,
        "key": key,
        "records": [_record_to_payload(record) for record in records],
    }
    temporary = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError as exc:
        logger.warning(
            "could not write the plugin scan cache (%s); the next scan will rescan",
            exc.strerror or type(exc).__name__,
        )
