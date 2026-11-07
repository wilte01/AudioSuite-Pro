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

Changed in 2.5.0: the sweep reads ``*.pyw`` as well. The launchers are the one
kind of shipped code no other gate parses - ruff, mypy and bandit all take
``*.py`` - so a capability re-implemented there was invisible to every rule,
including a Tk error dialog hand-built three times (plan D-42).

Changed in 2.5.0: the hand-built-path rule covers every binary the suite
ships, not only FFmpeg: ``fpcalc``/``fpcalc.exe`` and ``discid.dll`` joined
``BINARY_FILE_NAMES``, and the two files that legitimately locate a shipped
copy carry their reason in the allowlist (plan D-43).

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
#: The resolver needed no entry - it assembles its name from an f-string - so
#: each entry below is a file the suite ships beside itself rather than a PATH
#: lookup: both lines exist to name that one copy, and there is no shared
#: source to converge them onto. An entry here is the deliberate escape hatch.
BINARY_PATH_ALLOWLIST: dict[str, str] = {
    "audio_fingerprinter/core/fingerprinter.py": (
        "the committed fpcalc.exe at the checkout root is the last resort "
        "after the shared search; a frozen build finds the bundle copy first"
    ),
    "CD_Ripper.pyw": (
        "ctypes needs the path of the shipped discid.dll, and search_binary "
        "answers executables by name - it cannot find a DLL"
    ),
}

#: The file names a hand-built lookup spells before joining a directory to it.
BINARY_FILE_NAMES: frozenset[str] = frozenset(
    {
        "ffmpeg",
        "ffmpeg.exe",
        "ffprobe",
        "ffprobe.exe",
        "fpcalc",
        "fpcalc.exe",
        "discid.dll",
    }
)

#: Modules allowed to read ``sys._MEIPASS``, with the reason. A bundle lookup
#: decides where a packaged file lives, so it belongs beside the resolver that
#: already owns that source rather than in the tool that needs the file.
BUNDLE_LOOKUP_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/ffmpeg.py": "the suite's one bundle-aware binary resolver",
    "audio_suite_shared/suite_paths.py": (
        "the suite's one installation-root resolver: a bundle unpacked its data "
        "into _MEIPASS, and every suite-owned file is found from that root"
    ),
}

#: The directory name the retired ``open_help`` walk matched on.  Comparing a
#: directory's name to it is finding the installation root by name.
_PROJECT_DIR_NAME = "AudioSuite-Pro"

#: Modules allowed to find the suite root by matching a directory name, with
#: the reason.  Empty by design: the name match is the shape that breaks on a
#: renamed checkout and in every packaged build, so ``suite_paths`` replaced
#: it instead of being wrapped by it.  An entry needs a reason the resolver
#: cannot satisfy.
ROOT_NAME_LOOKUP_ALLOWLIST: dict[str, str] = {}

#: Modules allowed to build a Tk error dialog by hand, with the reason.
DIALOG_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/launch_failure.py": "the suite's one launcher dialog",
}

#: Modules allowed to write the suite's config file, with the reason.
CONFIG_WRITER_ALLOWLIST: dict[str, str] = {
    "audio_suite_shared/suite_config.py": "the one reader and writer of it",
}

#: Audio extensions a literal list has to name before it counts as a format list.
_MIN_EXTENSIONS = 4


def _runtime_sources() -> list[Path]:
    """Return every shipped module and launcher, developer scripts excluded.

    ``*.pyw`` is included: a launcher is shipped code that ruff, mypy and
    bandit all skip, so this walk is the only pass that reads it.
    """
    return sorted(
        path
        for pattern in ("*.py", "*.pyw")
        for path in REPO_ROOT.rglob(pattern)
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


def _hunts_the_suite_root_by_name(source: str) -> bool:
    """Report whether a module finds the suite root by matching a folder name.

    The shape is a comparison where one side reads ``.name`` of a directory and
    the other is the literal project folder name - ``d.name != "AudioSuite-Prow"``
    in the ``while`` loop ``open_help`` used to climb with.

    Args:
        source: The module's text.

    Returns:
        True when a directory name is compared to :data:`_PROJECT_DIR_NAME`.
    """
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Compare):
            continue
        operands = [node.left, *node.comparators]
        reads_a_directory_name = any(
            isinstance(operand, ast.Attribute) and operand.attr == "name"
            for operand in operands
        )
        spells_the_project = any(
            isinstance(operand, ast.Constant)
            and isinstance(operand.value, str)
            and operand.value == _PROJECT_DIR_NAME
            for operand in operands
        )
        if reads_a_directory_name and spells_the_project:
            return True
    return False


def _joins_a_binary_path(source: str) -> bool:
    """Report whether a module builds its own path to a binary it ships.

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
        or for a ``/`` path division by such a literal, for every name in
        :data:`BINARY_FILE_NAMES` - the file the path points at is the thing
        being decided, not the tool it happens to belong to.
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


def _hand_builds_a_failure_dialog(source: str) -> bool:
    """Report whether a module builds its own Tk error dialog.

    A launcher that fails before ``main()`` has no root to parent a message
    to, so the copies created one, hid it, showed the message and destroyed
    it. Different copies leaked the root or lost the original exception in
    different ways; :func:`audio_suite_shared.launch_failure.show_error_dialog`
    does it once (plan D-42).

    Args:
        source: The module's text.

    Returns:
        True for a module that constructs a ``Tk`` root and calls both
        ``withdraw`` and ``showerror``.
    """
    names = {
        getattr(node.func, "attr", "") or getattr(node.func, "id", "")
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
    }
    return {"Tk", "withdraw", "showerror"} <= names


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
    launchers = [path for path in sources if path.suffix == ".pyw"]
    assert len(launchers) >= 20, (
        "the sweep no longer reaches the .pyw launchers "
        f"(found {len(launchers)}); an extension filter dropped them"
    )
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
    # The suite ships two more binaries; a join to either is the same lookup.
    assert _joins_a_binary_path('Path(here) / "fpcalc.exe"\n')
    assert _joins_a_binary_path('os.path.join(here, "discid.dll")\n')
    assert not _joins_a_binary_path('os.path.join(here, "cover.jpg")\n')
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
    # The exact climb `open_help` used, and the guard form beside it.
    assert _hunts_the_suite_root_by_name(
        'while d.name != "AudioSuite-Pro":\n    d = d.parent\n'
    )
    assert _hunts_the_suite_root_by_name(
        'if Path.cwd().name == "AudioSuite-Pro":\n    pass\n'
    )
    # A working-directory read is fine on its own, and other folder names are
    # ordinary: only the project's own name in a comparison is the smell.
    assert not _hunts_the_suite_root_by_name("here = Path.cwd()\n")
    assert not _hunts_the_suite_root_by_name('"""Walk up to AudioSuite-Pro."""\n')
    assert not _hunts_the_suite_root_by_name('if d.name != "plugins":\n    pass\n')
    assert not _hunts_the_suite_root_by_name(
        "from audio_suite_shared.suite_paths import suite_root\n"
    )
    assert not _reads_the_frozen_bundle(
        "from audio_suite_shared.ffmpeg import search_binary\n"
    )
    # The launcher dialog the three copies built, and the call that replaced it.
    assert _hand_builds_a_failure_dialog(
        "_root = tk.Tk()\n_root.withdraw()\nmessagebox.showerror('t', 'm')\n"
        "_root.destroy()\n"
    )
    assert not _hand_builds_a_failure_dialog(
        "show_error_dialog('Startup Error', 'boom')\n"
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
    texts = {
        _relative(path): path.read_text(encoding="utf-8") for path in _runtime_sources()
    }
    offenders = [
        rel
        for rel, text in texts.items()
        if _joins_a_binary_path(text) and rel not in BINARY_PATH_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules build their own path to a binary the suite ships "
        f"instead of using the shared resolver: {offenders}"
    )
    # An entry that no longer trips the rule would silently pre-approve the
    # next module that does, so each one is held to being load-bearing.
    stale = [
        rel
        for rel in BINARY_PATH_ALLOWLIST
        if rel not in texts or not _joins_a_binary_path(texts[rel])
    ]
    assert stale == [], f"allowlisted files that no longer trip the rule: {stale}"


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


def test_no_module_builds_its_own_launcher_error_dialog() -> None:
    """One launcher dialog, and it destroys the root it created.

    The launchers are outside every other gate, so this rule is the only thing
    that can see a fourth inline copy (plan D-42).
    """
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _hand_builds_a_failure_dialog(path.read_text(encoding="utf-8"))
        and _relative(path) not in DIALOG_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules build a Tk error dialog instead of calling "
        f"launch_failure.show_error_dialog: {offenders}"
    )


def test_no_module_finds_the_suite_root_by_directory_name() -> None:
    """The installation root comes from one resolver, never from a name match.

    ``open_help`` walked up from ``Path.cwd()`` until it met a directory called
    ``AudioSuite-Pro``, which fails for a renamed checkout, a shortcut started
    in another folder, and every packaged build - while the guide sat exactly
    where it had been installed (plan D-44).  ``suite_paths`` is the one
    resolver; matching a folder's name is the shape that cannot work.
    """
    offenders = [
        _relative(path)
        for path in _runtime_sources()
        if _hunts_the_suite_root_by_name(path.read_text(encoding="utf-8"))
        and _relative(path) not in ROOT_NAME_LOOKUP_ALLOWLIST
    ]

    assert offenders == [], (
        "these modules find the suite root by matching a directory name "
        f"instead of calling suite_paths.suite_root: {offenders}"
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
        *ROOT_NAME_LOOKUP_ALLOWLIST,
        *DIALOG_ALLOWLIST,
        *CONFIG_WRITER_ALLOWLIST,
    }

    missing = sorted(entry for entry in declared if not (REPO_ROOT / entry).is_file())

    assert missing == [], f"allowlist entries whose file no longer exists: {missing}"
