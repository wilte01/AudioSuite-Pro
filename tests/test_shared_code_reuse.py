"""Lock: one implementation per capability, and the shared one is it.

Changed in 2.5.0: initial version, after the same capability was implemented
three times.  ``InputValidator`` declares the filename characters no filesystem
accepts; the Track Splitter, the CUE splitter and the Audio Joiner each carried
a private copy of that set (or none at all), so a legal name such as
``1-03 Johnny, Don't Do It.mp3`` was unusable in one tool and safe in another.
``tests/test_filename_safety.py`` closes that instance.

This module is the general guard.  It reads the shipped runtime, not the tests,
and fails when a module declares its own copy of a capability the suite already
owns: the audio-extension list, the suite's config file, or the FFmpeg binary
itself - both ways a module can choose that binary, the ``shutil.which`` lookup
and a spelled-out binary name handed to a path builder.  Known copies are
frozen in an allowlist with the reason they still exist, so the set cannot grow
while they are converged; a new copy fails here.

Changed in 2.5.0: the binary rule grew a second detector. The first version
only recognised ``shutil.which("ffmpeg")``, which is why the ReplayGain
analyzer's ``get_resource_path("ffmpeg.exe")``-plus-``exists`` lookup survived
the sweep that found every other copy (plan D-40); ``_joins_a_binary_path``
now catches a spelled-out binary name handed to a path builder.

Changed in 2.5.0: a third rule, wider than a binary. ``sys._MEIPASS`` is where
a one-file build unpacks a packaged file, so a module that reads it has built
its own PyInstaller lookup - which is how that ``get_resource_path`` helper
outlived its last caller (plan D-41).

The suite already locks two neighbouring boundaries, and this module does not
repeat them: ``tests/test_subprocess_boundary.py`` owns process spawning and
``tests/test_filename_safety.py`` owns the filename character set.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Directories that are not the shipped runtime: developer scripts and plugins.
SKIPPED_DIRS = frozenset(
    {"tests", "utilities", "plugins", ".git", ".venv", "__pycache__", "build"}
)

#: Modules allowed to declare a literal audio-extension list, with the reason.
EXTENSION_LIST_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/audio_formats.py": "the suite's one format matrix",
    "metadata_scrubber/core/scrubber.py": (
        "routes each file to the tag family that can hold it (APEv2, Vorbis, "
        "ID3); the sets are disjoint by family, not a copy of the format list"
    ),
    "audio_refinery/core/trim.py": (
        "the containers whose frames a stream copy can cut; a writable subset "
        "of the format matrix, which is why it is declared as such"
    ),
    "audio_enhancer/core/ffmpeg_io.py": (
        "the containers its own FFmpeg lane handles; predates the shared "
        "format matrix's capability flags"
    ),
    "audio_joiner/core/join.py": (
        "the containers whose tags the joiner copies; a tagging subset of the "
        "format matrix"
    ),
}

#: Modules allowed to resolve the FFmpeg binary themselves, with the reason.
FFMPEG_FINDER_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/ffmpeg.py": "the suite's one FFmpeg/FFprobe resolver",
}

#: Modules allowed to build a path to a binary by hand, with the reason.
#: Empty on purpose: the resolver assembles its own name from an f-string, so
#: it never spells a literal a caller could mistake for a hand-built lookup.
#: An entry here is the deliberate escape hatch, not the way to pass.
BINARY_PATH_ALLOWLIST: dict[str, str] = {}

#: The file names a hand-built lookup spells before joining a directory to it.
BINARY_FILE_NAMES: frozenset[str] = frozenset(
    {"ffmpeg", "ffmpeg.exe", "ffprobe", "ffprobe.exe"}
)

#: Modules allowed to read ``sys._MEIPASS``, with the reason. A bundle lookup
#: decides where a packaged file lives, so it belongs beside the resolver that
#: already owns that source rather than in the tool that needs the file.
BUNDLE_LOOKUP_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/ffmpeg.py": "the suite's one bundle-aware resolver",
}

#: Modules allowed to write the suite's config file, with the reason.
CONFIG_WRITER_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/suite_config.py": "the one reader and writer of it",
}

#: Audio extensions a literal list has to name before it counts as a format list.
_MIN_EXTENSIONS = 4


def _runtime_sources() -> list[Path]:
    """Return every shipped Python module, developer scripts excluded."""
    return sorted(
        path
        for path in REPO_ROOT.rglob("*.py")
        if not SKIPPED_DIRS & set(path.relative_to(REPO_ROOT).parts)
    )


def _relative(path: Path) -> str:
    """Return *path* relative to the repository, with forward slashes."""
    return path.relative_to(REPO_ROOT).as_posix()


def _extension_lists(source: str) -> list[str]:
    """Return the audio-extension literals a module declares.

    Args:
        source: The module's text.

    Returns:
        One rendered literal per assignment to an ``…EXTENSIONS`` name whose
        value is a set or tuple of at least :data:`_MIN_EXTENSIONS` dotted
        strings, e.g. ``{'.mp3', '.flac', '.m4a', '.ogg'}``.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and "EXTENSIONS" in target.id.upper()
            for target in node.targets
        ):
            continue
        calls = list(ast.walk(node.value))
        extensions = [
            element.value
            for element in calls
            if isinstance(element, ast.Constant)
            and isinstance(element.value, str)
            and element.value.startswith(".")
        ]
        if len(extensions) >= _MIN_EXTENSIONS:
            found.append(", ".join(sorted(extensions)))
    return found


def _resolves_ffmpeg(source: str) -> bool:
    """Report whether a module looks the FFmpeg binary up on PATH itself.

    Args:
        source: The module's text.

    Returns:
        True for a ``shutil.which("ffmpeg")`` or ``shutil.which("ffprobe")``.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if getattr(function, "attr", "") != "which" or not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and argument.value in {
            "ffmpeg",
            "ffprobe",
        }:
            return True
    return False


def _is_binary_literal(node: ast.AST) -> bool:
    """Report whether *node* is a string literal naming an FFmpeg binary.

    Args:
        node: The AST node to test.

    Returns:
        True for a constant such as ``"ffmpeg.exe"`` (case-insensitive).
    """
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lower() in BINARY_FILE_NAMES
    )


def _is_path_builder(function: ast.expr) -> bool:
    """Report whether *function* is a callee that builds or probes a path.

    A binary literal is only a lookup when something is going to treat it as
    a path. ``run_secure_subprocess("ffmpeg", args)`` names the binary the
    wrapper runs and is deliberately not one of these; ``_tool_failure(...)``
    and ``SystemRequirement(...)`` take the same literal as a label.

    Args:
        function: The call's ``.func`` expression.

    Returns:
        True for a callee whose name is a path builder or probe, e.g.
        ``os.path.join``, ``Path``, ``get_resource_path``, ``os.path.exists``.
    """
    name = getattr(function, "attr", "") or getattr(function, "id", "")
    lowered = name.lower()
    return lowered == "path" or any(
        word in lowered
        for word in ("join", "path", "resource", "abspath", "exists", "isfile")
    )


def _joins_a_binary_path(source: str) -> bool:
    """Report whether a module builds its own path to an FFmpeg binary.

    ``_resolves_ffmpeg`` sees the ``shutil.which`` shape. This sees the other
    one: a spelled-out binary name handed to something that builds or probes a
    path, which is how the ReplayGain analyzer kept a private lookup alive
    through the first sweep - ``get_resource_path("ffmpeg.exe")`` guarded by
    ``os.path.exists``, with no lookup call anywhere, because the ``join`` sat
    inside the helper and took a variable. Both shapes decide *which* binary
    runs, so neither may live outside the shared resolver.

    Args:
        source: The module's text.

    Returns:
        True for ``… .join(<dir>, "ffmpeg.exe")`` on any ``join`` attribute,
        or for a ``/`` path division by such a literal.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            if _is_path_builder(node.func) and any(
                _is_binary_literal(argument) for argument in node.args
            ):
                return True
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if _is_binary_literal(node.left) or _is_binary_literal(node.right):
                return True
    return False


def _reads_the_frozen_bundle(source: str) -> bool:
    """Report whether a module reads PyInstaller's ``sys._MEIPASS``.

    Both spellings count: the attribute itself, and the ``getattr`` form a
    module uses when the name is absent outside a build. Reading it is how a
    module finds a file a one-file build unpacked, which is a location
    decision - the resolver already owns every one of those.

    Args:
        source: The module's text.

    Returns:
        True for ``sys._MEIPASS`` or ``getattr(sys, "_MEIPASS", None)``.
    """
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Attribute):
            if node.attr == "_MEIPASS":
                return True
        elif isinstance(node, ast.Call):
            function = node.func
            name = getattr(function, "id", "") or getattr(function, "attr", "")
            if name != "getattr" or len(node.args) < 2:
                continue
            target, key = node.args[0], node.args[1]
            if (
                isinstance(target, ast.Name)
                and target.id == "sys"
                and isinstance(key, ast.Constant)
                and key.value == "_MEIPASS"
            ):
                return True
    return False


def _writes_suite_config(source: str) -> bool:
    """Report whether a module serialises the suite's own config file.

    Args:
        source: The module's text.

    Returns:
        True when the module both names ``audio_suite_config`` and calls
        ``json.dump``.
    """
    return "audio_suite_config" in source and "json.dump(" in source


def test_the_scan_finds_the_runtime_tree() -> None:
    """The scan is non-vacuous: an empty walk would pass every check below."""
    sources = _runtime_sources()

    assert len(sources) > 100
    snippet = "AUDIO_EXTENSIONS = {'.mp3', '.flac', '.ogg', '.m4a'}"
    assert len(_extension_lists(snippet)) == 1


def test_the_detectors_can_fail() -> None:
    """Each detector recognises a copy and ignores the shared call."""
    assert _resolves_ffmpeg('import shutil\nshutil.which("ffmpeg")\n')
    assert not _resolves_ffmpeg("from x import FFMPEG_PATH\nFFMPEG_PATH\n")
    assert _writes_suite_config('name = "audio_suite_config"\njson.dump({}, f)\n')
    assert not _writes_suite_config("suite_config.save_value('a', 1)\n")
    # The exact shape the ReplayGain analyzer used, which the `which` detector
    # could not see: a literal handed to a path helper, no lookup call at all.
    assert _joins_a_binary_path(
        'def f():\n    local = get_resource_path("ffmpeg.exe")\n'
        '    return local if os.path.exists(local) else "ffmpeg"\n'
    )
    assert _joins_a_binary_path('os.path.join(here, "ffmpeg.exe")\n')
    assert _joins_a_binary_path('Path(here) / "ffprobe"\n')
    assert not _joins_a_binary_path("os.path.join(here, name)\n")
    # Naming the binary the wrapper will run is not a lookup: no path builder
    # is involved, and the argv[0] still comes from FFMPEG_PATH at the call
    # site that matters.
    assert not _joins_a_binary_path('run_secure_subprocess("ffmpeg", args)\n')
    assert not _joins_a_binary_path(
        "from audio_suite_shared.ffmpeg import FFMPEG_PATH\n"
    )
    # A frozen-bundle lookup is a location decision too, in either spelling.
    assert _reads_the_frozen_bundle('bundle = getattr(sys, "_MEIPASS", None)\n')
    assert _reads_the_frozen_bundle(
        "def f():\n    return os.path.join(sys._MEIPASS, relative_path)\n"
    )
    assert not _reads_the_frozen_bundle('frozen = getattr(sys, "frozen", False)\n')
    assert not _reads_the_frozen_bundle('"""A build unpacks into sys._MEIPASS."""\n')
    assert not _reads_the_frozen_bundle(
        "from audio_suite_shared.ffmpeg import search_binary\n"
    )


def test_no_module_declares_its_own_audio_extension_list() -> None:
    """A second format list drifts from ``audio_formats`` the moment it grows."""
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _extension_lists(path.read_text(encoding="utf-8"))
        and _relative(path) not in EXTENSION_LIST_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules declare their own audio-extension list instead of using "
        f"audio_suite_shared.audio_formats: {offenders}"
    )


def test_the_ffmpeg_binary_is_resolved_in_one_place() -> None:
    """One resolver owns the binary path; a second lookup can disagree."""
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _resolves_ffmpeg(path.read_text(encoding="utf-8"))
        and _relative(path) not in FFMPEG_FINDER_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules look FFmpeg up themselves instead of importing "
        f"FFMPEG_PATH: {offenders}"
    )


def test_no_module_builds_its_own_path_to_a_binary() -> None:
    """A hand-joined binary name picks a binary just as a lookup would.

    ``test_the_ffmpeg_binary_is_resolved_in_one_place`` only sees
    ``shutil.which``; this is the second shape, and it is the one that let the
    ReplayGain analyzer's private lookup survive the first sweep (plan D-39).
    """
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _joins_a_binary_path(path.read_text(encoding="utf-8"))
        and _relative(path) not in BINARY_PATH_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules build their own path to an FFmpeg binary instead of "
        f"importing FFMPEG_PATH: {offenders}"
    )


def test_only_the_shared_resolver_reads_the_frozen_bundle() -> None:
    """A bundle lookup outside the resolver decides where a packaged file is.

    ``sys._MEIPASS`` is the directory a one-file build unpacks into, so it is
    the same source the FFmpeg resolver owns. ReplayGain's
    ``get_resource_path`` kept a private copy of it alive with no caller (plan
    D-41); this is what stops the next one from being written.
    """
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _reads_the_frozen_bundle(path.read_text(encoding="utf-8"))
        and _relative(path) not in BUNDLE_LOOKUP_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules read sys._MEIPASS instead of calling "
        f"audio_suite_shared.ffmpeg.search_binary: {offenders}"
    )


def test_the_suite_config_file_has_one_writer() -> None:
    """Every preference goes through ``suite_config``: one file, one writer."""
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _writes_suite_config(path.read_text(encoding="utf-8"))
        and _relative(path) not in CONFIG_WRITER_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules write audio_suite_config.json themselves instead of "
        f"using suite_config.save_value: {offenders}"
    )


def test_every_allowlist_entry_names_a_real_file() -> None:
    """A stale allowlist entry would silently widen the rule for a new file."""
    declared = {
        *EXTENSION_LIST_ALLOWLIST,
        *FFMPEG_FINDER_ALLOWLIST,
        *BINARY_PATH_ALLOWLIST,
        *BUNDLE_LOOKUP_ALLOWLIST,
        *CONFIG_WRITER_ALLOWLIST,
    }

    missing = sorted(entry for entry in declared if not (REPO_ROOT / entry).is_file())

    assert missing == [], f"allowlist entries whose file no longer exists: {missing}"
