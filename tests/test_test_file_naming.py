"""Naming lock: one test file per source module (AGENTS `Test File Naming`).

Canonical rule (AGENTS.md): a test file under a package's ``tests/`` tree
must be named ``test_<module>.py`` where ``<module>`` is the stem of some
source module in that package — e.g. ``core/scrubber.py`` is tested by
``tests/test_scrubber.py``.  Root ``tests/`` is exempt by scope (its files
are cross-cutting by design), as are test trees whose package lacks
``__init__.py`` (``utilities/tests``).

Classifier (embedded here so it can be re-derived at any time):

1. For every ``test_*.py`` file in the repository, find its nearest
   ancestor directory named ``tests``.  The package is that directory's
   parent; skip the file unless the package carries ``__init__.py`` and is
   not the repository root (root ``tests/`` exemption).
2. ``src_stems`` = stems of every ``*.py`` under the package, excluding any
   ``tests/`` subtree (recursive, so ``state/app_state.py`` backs
   ``test_app_state.py``).
3. A scanned file whose stem minus the ``test_`` prefix is not in
   ``src_stems`` is a naming violation unless it appears in ``ALLOWLIST``.

The allowlist freezes the 30 deliberate composites/contract locks that
existed at the time the lock landed (iteration-9 G5.2); its length is
asserted so new violations cannot be smuggled in as "one more composite".
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_SKIP_DIRS = frozenset({".git", ".venv", "__pycache__", "node_modules"})

#: Deliberate non-mirroring test files, frozen at 30 entries.
#: Key format: ``<package>/<test file stem>`` (stem includes ``test_``).
ALLOWLIST: dict[str, str] = {
    "album_art_sync/test_album_art_sync": "whole-package smoke composite",
    "album_genre_tagger/test_tag_io": "AGENTS-sanctioned composite example",
    "asx_extractor/test_asx_core": "core-package composite",
    "audio_normalizer/test_normalizer_core": "core-package composite",
    "audio_refinery/test_convert_and_pipeline": "core-package composite",
    "audio_refinery/test_pipeline_stages": "core-package composite",
    "audio_refinery/test_target_lufs_restriction": (
        "named-by-concern LUFS contract lock"
    ),
    "audio_suite_shared/test_cli_cue": "CUE CLI concerns",
    "audio_suite_shared/test_cli_helpers_ast_lock": "AST contract lock",
    "audio_suite_shared/test_e4_dead_code_lock": "AST contract lock",
    "audio_suite_shared/test_i1_robustness": "cross-module robustness scenarios",
    "audio_suite_shared/test_infra": "infra composite",
    "audio_suite_shared/test_logging_namespacing": "logging contract lock",
    "audio_suite_shared/test_synced_lyrics": "cross-module lyrics fixtures",
    "audio_suite_shared/test_tag_helper_completeness": "tag-helper family",
    "cd_ripper/test_disc_core": "core composite",
    "cd_ripper/test_ripper_core": "core composite",
    "cd_ripper/test_ripper_platform_fail_fast": "platform scenario suite",
    "file_reorganizer/test_reorganizer": "engine composite",
    "genre_sync/test_genre_core": "core composite",
    "genre_sync/test_ui": "ui composite",
    "lyrics_manager/test_providers": "provider-chain composite",
    "lyrics_manager/test_sidecar_provider": "provider contract incl. registry",
    "master_driver/test_runner": "cross-cutting driver suite",
    "master_driver/test_ui_cards": "cross-cutting driver suite",
    "master_driver/test_utilities_format_detection": ("cross-cutting driver suite"),
    "replaygain_analyzer/test_replaygain_core": "core composite",
    "replaygain_analyzer/test_replaygain_pipeline": "core composite",
    "silence_trimmer/test_silence_trimmer": ("module-with-behaviour-suite composite"),
    "tempo_analyzer/test_ui": "ui composite",
}


def source_module_stems(pkg_dir: Path) -> set[str]:
    """Stems of every source module in ``pkg_dir``, excluding ``tests/``.

    Args:
        pkg_dir: A package directory (carries ``__init__.py``).

    Returns:
        The stem of every ``*.py`` file under ``pkg_dir`` that does not
        live in a ``tests`` subtree (recursive — subpackages count).
    """
    stems: set[str] = set()
    for path in pkg_dir.rglob("*.py"):
        rel = path.relative_to(pkg_dir)
        if "tests" in rel.parts:
            continue
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        stems.add(path.stem)
    return stems


def mirrors_source_module(pkg_dir: Path, test_path: Path) -> bool:
    """Whether ``test_path`` follows the ``test_<module>.py`` naming rule.

    Pure matcher: no filesystem state beyond the two paths is consulted
    other than reading ``pkg_dir``'s source tree.

    Args:
        pkg_dir: The package the test file belongs to.
        test_path: Path of the ``test_*.py`` file.

    Returns:
        ``True`` when the test stem (``test_path.stem[5:]`` — the
        ``test_`` prefix stripped) names a source module of ``pkg_dir``.
    """
    return test_path.stem[5:] in source_module_stems(pkg_dir)


def package_test_files(repo_root: Path) -> Iterator[tuple[Path, Path]]:
    """Yield ``(pkg_dir, test_file)`` for every in-scope test file.

    Scope is the canonical rule: the file sits under a directory named
    ``tests`` whose parent package carries ``__init__.py`` and is not the
    repository root (root ``tests/`` and ``utilities/tests`` therefore drop
    out).  Traversal prunes ``.venv``/``.git`` so the walk stays on
    first-party code.
    """
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            if not filename.startswith("test_") or not filename.endswith(".py"):
                continue
            test_file = Path(dirpath) / filename
            tests_dir = next((p for p in test_file.parents if p.name == "tests"), None)
            if tests_dir is None:
                continue
            pkg_dir = tests_dir.parent
            if pkg_dir == repo_root:
                continue
            if not (pkg_dir / "__init__.py").is_file():
                continue
            yield pkg_dir, test_file


def _scan() -> tuple[list[str], list[str]]:
    """Run the classifier over the working tree.

    Returns:
        ``(scanned_keys, violation_keys)`` where each key is
        ``<package relative path>/<test file stem>``.
    """
    scanned: list[str] = []
    violations: list[str] = []
    for pkg_dir, test_file in package_test_files(REPO_ROOT):
        key = f"{pkg_dir.relative_to(REPO_ROOT).as_posix()}/{test_file.stem}"
        scanned.append(key)
        if not mirrors_source_module(pkg_dir, test_file):
            violations.append(key)
    return scanned, violations


class TestMatcher:
    """The matcher itself is locked with synthetic trees so it cannot rot."""

    def test_matching_module_name_passes(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        (pkg / "tests").mkdir(parents=True)
        (pkg / "app.py").write_text("", encoding="utf-8")
        test_file = pkg / "tests" / "test_app.py"
        test_file.write_text("", encoding="utf-8")

        assert mirrors_source_module(pkg, test_file) is True

    def test_unknown_module_name_fails(self, tmp_path: Path) -> None:
        pkg = tmp_path / "pkg"
        (pkg / "tests").mkdir(parents=True)
        (pkg / "app.py").write_text("", encoding="utf-8")
        test_file = pkg / "tests" / "test_app_run.py"
        test_file.write_text("", encoding="utf-8")

        assert mirrors_source_module(pkg, test_file) is False

    def test_stems_inside_the_tests_subtree_do_not_count(self, tmp_path: Path) -> None:
        """A helper defined only under ``tests/`` must not legitimise a name."""
        pkg = tmp_path / "pkg"
        (pkg / "tests").mkdir(parents=True)
        (pkg / "tests" / "helpers.py").write_text("", encoding="utf-8")
        test_file = pkg / "tests" / "test_helpers.py"
        test_file.write_text("", encoding="utf-8")

        assert mirrors_source_module(pkg, test_file) is False

    def test_nested_source_modules_count(self, tmp_path: Path) -> None:
        """The classifier walks subpackages: state/app_state.py backs
        test_app_state.py."""
        pkg = tmp_path / "pkg"
        (pkg / "state").mkdir(parents=True)
        (pkg / "state" / "app_state.py").write_text("", encoding="utf-8")
        (pkg / "tests").mkdir()
        test_file = pkg / "tests" / "test_app_state.py"
        test_file.write_text("", encoding="utf-8")

        assert mirrors_source_module(pkg, test_file) is True

    def test_test_prefix_is_stripped_before_lookup(self, tmp_path: Path) -> None:
        """Only the five-character ``test_`` prefix is removed; nothing else."""
        pkg = tmp_path / "pkg"
        (pkg / "tests").mkdir(parents=True)
        (pkg / "testing_utils.py").write_text("", encoding="utf-8")
        # stem "test_testing_utils" minus "test_" is "testing_utils"
        test_file = pkg / "tests" / "test_testing_utils.py"
        test_file.write_text("", encoding="utf-8")

        assert mirrors_source_module(pkg, test_file) is True


class TestAllowlistFrozen:
    def test_allowlist_is_frozen_at_thirty_entries(self) -> None:
        assert len(ALLOWLIST) == 30, (
            "ALLOWLIST must stay at exactly 30 entries — add new violations "
            "by fixing the test file's name, not by growing the allowlist"
        )

    def test_allowlist_keys_are_well_formed(self) -> None:
        for key in ALLOWLIST:
            pkg_name, _, stem = key.partition("/")
            assert pkg_name and stem.startswith("test_"), f"malformed key: {key}"

    def test_every_allowlisted_file_still_exists(self) -> None:
        missing = []
        for key in ALLOWLIST:
            pkg_name, _, stem = key.partition("/")
            if not (REPO_ROOT / pkg_name / "tests" / f"{stem}.py").is_file():
                missing.append(key)
        assert not missing, f"dead allowlist entries (file gone): {missing}"


class TestNamingLock:
    def test_every_package_test_file_mirrors_a_source_module(self) -> None:
        scanned, violations = _scan()

        # Non-vacuity: the scan must genuinely walk the real tree.  The
        # plan's original >= 840 floor is unreachable (the working tree
        # holds 243 test files in total, 227 of them inside package
        # `tests/` trees), so the floor is the measured reality, and the
        # ALLOWLIST coverage assertion below anchors the scan harder than
        # any raw count could.
        assert len(scanned) >= 220, f"scan only reached {len(scanned)} files"

        # Every allowlisted file must actually have been scanned — this
        # fails if package detection silently skips a whole package.
        not_scanned = set(ALLOWLIST) - set(scanned)
        assert not not_scanned, (
            f"allowlisted files never scanned: {sorted(not_scanned)}"
        )

        unexpected = [key for key in violations if key not in ALLOWLIST]
        assert not unexpected, (
            "test files that violate the test_<module>.py naming rule but "
            "are not allowlisted:\n" + "\n".join(f"  {k}" for k in unexpected)
        )
