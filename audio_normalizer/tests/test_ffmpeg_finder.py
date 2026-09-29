# -*- coding: utf-8 -*-
"""Tests for ``audio_normalizer.utils.ffmpeg_finder`` and the startupinfo helper.

The finder's three discovery sources and its "not found" contract are the
seam every ffmpeg-backed tool in this package depends on, so each branch is
driven with **real files on disk** rather than a fully mocked ``os.path``: a
returned path is asserted to be the actual file that was created.  Source 2 is
gated on ``isfile`` + ``os.access(..., os.X_OK)``, so every test that wants "no
local copy" denies all three probes through ``_deny_local_copy`` instead of
patching only ``exists``.

``ffmpeg_finder`` imports ``os``/``shutil``/``sys`` at module level, so per
AGENTS.md the patching target is the *importing* module's binding
(``audio_normalizer.utils.ffmpeg_finder.shutil.which``). Note that those
bindings are the real module objects, so ``monkeypatch`` (auto-restoring) is
used throughout rather than ``unittest.mock.patch``.
"""

from __future__ import annotations

import importlib
import os
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import ModuleType

import pytest

from audio_normalizer.utils import ffmpeg_finder
from audio_suite_shared.secure_subprocess import validate_executable
from audio_suite_shared.subprocess_utils import get_startupinfo
from audio_suite_shared.system_requirements import (
    FFMPEG_PURPOSE,
    REQUIRED_EXECUTABLES,
    find_missing_requirements,
    format_requirement_report,
)

#: The literal the finder returns when every source misses, and the value its
#: callers pass as argv[0] so the OS can raise the real error.
BARE_NAME = "ffmpeg"

#: The third-choice location, hard-coded in the finder for Windows only.
WINDOWS_FALLBACK = r"C:\ffmpeg\bin\ffmpeg.exe"


def _make_exe(directory: str, name: str) -> str:
    """Create a real, empty file standing in for an ffmpeg binary.

    The execute bit is set explicitly: source 2 gates on
    ``os.access(..., os.X_OK)``, and a file created with the default mode is
    not executable on POSIX, so without this every positive test would fail
    on the Linux CI leg while passing on Windows (where ``X_OK`` only checks
    existence).
    """
    path = os.path.join(directory, name)
    os.makedirs(directory, exist_ok=True)
    with open(path, "wb"):
        pass
    os.chmod(path, 0o755)
    return path


def _deny_local_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make sources 2 and 3 report nothing, independently of the host.

    Source 2 is gated on ``isfile`` + ``access`` and source 3 on ``exists``,
    so a test that means "there is no local copy" has to deny all three
    probes.  Denying only ``exists`` leaves the finder reading the real
    filesystem of whichever host runs the suite.
    """
    monkeypatch.setattr(ffmpeg_finder.os.path, "exists", lambda path: False)
    monkeypatch.setattr(ffmpeg_finder.os.path, "isfile", lambda path: False)
    monkeypatch.setattr(ffmpeg_finder.os, "access", lambda path, mode: False)


@contextmanager
def _fresh_finder(
    monkeypatch: pytest.MonkeyPatch,
    setup: Callable[[pytest.MonkeyPatch], None],
) -> Iterator[ModuleType]:
    """Reload the module under test with a prepared environment.

    ``FFMPEG_PATH`` is a module-level singleton, so a test that wants to
    observe how it is *computed* must re-execute the module body — which means
    the environment has to be patched **before** the reload, not after.  The
    inner ``monkeypatch.context()`` guarantees the patches are undone before
    the final reload restores the real host environment, so a reload-based
    test cannot leak a fake singleton into the rest of the session.
    """
    try:
        with monkeypatch.context() as inner:
            setup(inner)
            yield importlib.reload(ffmpeg_finder)
    finally:
        importlib.reload(ffmpeg_finder)


class TestPathHit:
    """Discovery source 1 — the system ``PATH``."""

    def test_a_path_hit_wins_over_every_other_source(
        self, tmp_path, monkeypatch
    ) -> None:
        hit = _make_exe(str(tmp_path / "bin"), "ffmpeg.exe")
        # Plant a *valid* competing copy at source 2 and a plausible-looking
        # source 3, so the winner is decided by precedence alone.
        _make_exe(str(tmp_path / "app"), "ffmpeg.exe")
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "win32")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: hit)
        monkeypatch.setattr(
            ffmpeg_finder.os.path, "exists", lambda path: str(path) != WINDOWS_FALLBACK
        )

        result = ffmpeg_finder._find_ffmpeg()

        assert result == os.path.abspath(hit)
        assert os.path.isfile(result)

    def test_a_relative_path_hit_is_returned_absolute(
        self, tmp_path, monkeypatch
    ) -> None:
        """``shutil.which`` may answer with a relative element of ``PATH``;
        the finder must not hand a relative argv[0] to the callers."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "linux")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: "bin/ffmpeg")

        result = ffmpeg_finder._find_ffmpeg()

        assert result == os.path.abspath(os.path.join("bin", "ffmpeg"))
        assert os.path.isabs(result)

    def test_the_live_singleton_is_either_a_real_absolute_path_or_the_bare_name(
        self,
    ) -> None:
        """Measured invariant of the value resolved on *this* host, whatever
        the host happens to have installed."""
        path = ffmpeg_finder.FFMPEG_PATH
        if path == BARE_NAME:
            assert shutil.which("ffmpeg") is None
        else:
            assert os.path.isabs(path)
            assert os.path.isfile(path)
            assert os.path.basename(path).lower().startswith("ffmpeg")


class TestAlongsideTheModule:
    """Discovery source 2 — a copy shipped beside the module or the exe."""

    @pytest.mark.parametrize(
        ("platform", "local_name"),
        [("win32", "ffmpeg.exe"), ("linux", "ffmpeg"), ("darwin", "ffmpeg")],
    )
    def test_the_beside_copy_is_used_when_path_has_none(
        self, tmp_path, monkeypatch, platform: str, local_name: str
    ) -> None:
        expected = _make_exe(str(tmp_path / "app"), local_name)
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", platform)
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)

        result = ffmpeg_finder._find_ffmpeg()

        assert result == os.path.abspath(expected)
        assert os.path.isfile(result)

    def test_the_beside_the_frozen_executable_copy_is_used_when_frozen(
        self, tmp_path, monkeypatch
    ) -> None:
        """Under PyInstaller the module lives in a temp unpack dir, so the
        bundled copy sits next to the executable, not next to the module."""
        exe_dir = str(tmp_path / "dist")
        expected = _make_exe(exe_dir, "ffmpeg.exe")
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "win32")
        monkeypatch.setattr(ffmpeg_finder.sys, "frozen", True, raising=False)
        monkeypatch.setattr(
            ffmpeg_finder.sys, "executable", os.path.join(exe_dir, "normalizer.exe")
        )
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "_MEI" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)

        result = ffmpeg_finder._find_ffmpeg()

        assert result == os.path.abspath(expected)

    def test_when_not_frozen_the_executable_directory_is_not_consulted(
        self, tmp_path, monkeypatch
    ) -> None:
        """Negative control for the branch above: the same planted exe-side
        copy must be ignored when ``sys.frozen`` is absent."""
        exe_dir = str(tmp_path / "dist")
        _make_exe(exe_dir, "ffmpeg.exe")
        monkeypatch.delattr(ffmpeg_finder.sys, "frozen", raising=False)
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "win32")
        monkeypatch.setattr(
            ffmpeg_finder.sys, "executable", os.path.join(exe_dir, "normalizer.exe")
        )
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "src" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        # Sources 2 and 3 are neutralised so the only thing that could return
        # the planted dist copy is the frozen branch above.
        _deny_local_copy(monkeypatch)

        result = ffmpeg_finder._find_ffmpeg()

        assert result == BARE_NAME


class TestWindowsFallback:
    """Discovery source 3 — the hard-coded ``C:\\ffmpeg\\bin`` location."""

    def test_the_windows_fallback_directory_is_the_third_choice(
        self, tmp_path, monkeypatch
    ) -> None:
        probed: list[str] = []

        def _record(path: object) -> bool:
            probed.append(str(path))
            return str(path) == WINDOWS_FALLBACK

        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "win32")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        # Source 2's own gate must miss too, or the fallback would never be
        # reached; only the fallback path reports a hit.
        monkeypatch.setattr(ffmpeg_finder.os.path, "isfile", _record)
        monkeypatch.setattr(ffmpeg_finder.os, "access", lambda path, mode: False)
        monkeypatch.setattr(ffmpeg_finder.os.path, "exists", _record)

        result = ffmpeg_finder._find_ffmpeg()

        assert result == WINDOWS_FALLBACK
        # The fallback is only probed after both earlier sources missed, and
        # the local copy was probed before it.
        assert WINDOWS_FALLBACK in probed
        assert probed.index(str(tmp_path / "app" / "ffmpeg.exe")) < probed.index(
            WINDOWS_FALLBACK
        )

    def test_the_windows_fallback_is_never_probed_off_windows(
        self, tmp_path, monkeypatch
    ) -> None:
        probed: list[str] = []

        def _record(path: object) -> bool:
            probed.append(str(path))
            return False

        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "linux")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        monkeypatch.setattr(ffmpeg_finder.os.path, "isfile", _record)
        monkeypatch.setattr(ffmpeg_finder.os, "access", lambda path, mode: False)
        monkeypatch.setattr(ffmpeg_finder.os.path, "exists", _record)

        result = ffmpeg_finder._find_ffmpeg()

        assert result == BARE_NAME
        assert WINDOWS_FALLBACK not in probed


class TestMissContract:
    """The documented "not found" behaviour the callers depend on."""

    def test_nothing_found_anywhere_returns_the_bare_name(
        self, tmp_path, monkeypatch
    ) -> None:
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "linux")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        _deny_local_copy(monkeypatch)

        assert ffmpeg_finder._find_ffmpeg() == BARE_NAME

    def test_the_bare_name_is_the_name_of_the_declared_requirement(self) -> None:
        """The two discovery mechanisms are decoupled by design (see the A5
        Decision Log), so the invariant worth locking is that they agree on
        *which executable is missing*."""
        names = [requirement.name for requirement in REQUIRED_EXECUTABLES]
        assert BARE_NAME in names

    def test_the_bare_name_passes_the_subprocess_allowlist(self) -> None:
        """The finder deliberately hands back an unresolved name "letting the
        OS raise a clear error".  That is only true if the suite's own
        security gate lets the name through first — otherwise a user would see
        ``SubprocessSecurityError`` instead of ``FileNotFoundError``."""
        assert validate_executable(BARE_NAME) is True

    def test_a_resolved_path_also_passes_the_subprocess_allowlist(
        self, tmp_path, monkeypatch
    ) -> None:
        hit = _make_exe(str(tmp_path / "bin"), "ffmpeg.exe")
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: hit)
        resolved = ffmpeg_finder._find_ffmpeg()
        assert validate_executable(resolved) is True

    def test_the_finder_and_the_preflight_agree_when_nothing_is_on_path(
        self, tmp_path, monkeypatch
    ) -> None:
        """The A5 startup dialog and the finder share the premise "a falsy
        lookup means ffmpeg is missing", and the dialog's wording comes from
        the shared constants rather than a re-spelled literal."""
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", "linux")
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        _deny_local_copy(monkeypatch)
        monkeypatch.setattr(
            ffmpeg_finder.shutil, "which", lambda name: None, raising=False
        )

        assert ffmpeg_finder._find_ffmpeg() == BARE_NAME

        missing = find_missing_requirements(
            resolver=lambda name: None if name == BARE_NAME else "irrelevant"
        )
        assert [requirement.name for requirement in missing] == ["ffmpeg"]
        report = format_requirement_report(missing)
        assert f"- ffmpeg ({FFMPEG_PURPOSE})" in report
        for hint in REQUIRED_EXECUTABLES[0].install_hints:
            assert f"install: {hint}" in report


class TestSourceTwoAcceptsOnlyRealExecutables:
    """Source 2 is gated on a real, executable file — the inverted defect.

    This class used to be ``TestNoExecutabilityCheck`` and pinned the
    opposite contract: it asserted that ``os.access`` was *never* consulted
    and that a *directory* named like the binary was accepted.  Both are now
    the defect A3 fixed, so the assertions are inverted rather than dropped.
    """

    @staticmethod
    def _local_name() -> str:
        return "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"

    def test_executability_is_consulted_for_the_local_copy(
        self, tmp_path, monkeypatch
    ) -> None:
        """``os.access(..., os.X_OK)`` is part of the gate, on every platform.

        The mode is asserted as well as the fact of the call: a probe with any
        other mode would not be the executability check this pins.
        """
        planted = _make_exe(str(tmp_path / "app"), self._local_name())
        probed: list[tuple[str, int]] = []
        real_access = os.access

        def _record(path: object, mode: int) -> bool:
            probed.append((str(path), mode))
            return real_access(path, mode)

        monkeypatch.setattr(ffmpeg_finder.sys, "platform", sys.platform)
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        monkeypatch.setattr(ffmpeg_finder.os, "access", _record)

        assert ffmpeg_finder._find_ffmpeg() == os.path.abspath(planted)
        assert (os.path.abspath(planted), os.X_OK) in probed

    @pytest.mark.parametrize(
        ("platform", "local_name"),
        [("win32", "ffmpeg.exe"), ("linux", "ffmpeg"), ("darwin", "ffmpeg")],
    )
    def test_a_directory_named_like_the_binary_is_rejected(
        self, tmp_path, monkeypatch, platform: str, local_name: str
    ) -> None:
        """The concrete consequence of the old existence-only gate, inverted.

        A *directory* called ``ffmpeg(.exe)`` beside the module satisfied
        ``os.path.exists``, so the finder handed the callers an argv[0] that
        could only ever fail at exec time.  Every platform is exercised, and
        source 3 is denied explicitly so the win32 leg cannot pass by finding
        a real ffmpeg in ``C:\\ffmpeg\\bin`` on whichever host runs the suite.
        """
        decoy = os.path.join(str(tmp_path / "app"), local_name)
        os.makedirs(decoy)
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", platform)
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            ffmpeg_finder.os.path, "exists", lambda path: str(path) != WINDOWS_FALLBACK
        )

        result = ffmpeg_finder._find_ffmpeg()

        assert result == BARE_NAME
        assert os.path.isdir(decoy)
        assert not os.path.isfile(decoy)

    def test_a_non_executable_file_follows_the_platform_rule(
        self, tmp_path, monkeypatch
    ) -> None:
        """A real file whose execute bit was cleared, checked on every host.

        POSIX gates the copy on the execute bit, so it is rejected; Windows has
        no execute bit at all (``os.access(X_OK)`` reports existence), so the
        platform itself accepts the copy.  Both outcomes are asserted rather
        than skipped, because that difference is precisely what
        ``platform_support.py`` records for the Windows arm of this finder —
        a skip would hide the half of the gate this host can never exercise.
        """
        planted = _make_exe(str(tmp_path / "app"), self._local_name())
        os.chmod(planted, 0o644)
        monkeypatch.setattr(ffmpeg_finder.sys, "platform", sys.platform)
        monkeypatch.setattr(ffmpeg_finder, "__file__", str(tmp_path / "app" / "f.py"))
        monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: None)
        monkeypatch.setattr(
            ffmpeg_finder.os.path, "exists", lambda path: str(path) != WINDOWS_FALLBACK
        )
        platform_accepts = os.access(planted, os.X_OK)

        result = ffmpeg_finder._find_ffmpeg()

        assert os.path.isfile(planted)
        if platform_accepts:
            assert result == os.path.abspath(planted)
        else:
            assert result == BARE_NAME


class TestModuleSingletonIsTheCache:
    """``FFMPEG_PATH`` is resolved once, when the module body executes."""

    def test_the_singleton_is_not_re_resolved_while_the_environment_changes(
        self, tmp_path, monkeypatch
    ) -> None:
        hit = _make_exe(str(tmp_path / "bin"), "ffmpeg")

        def _setup(mp: pytest.MonkeyPatch) -> None:
            mp.setattr(ffmpeg_finder.sys, "platform", "linux")
            _deny_local_copy(mp)
            mp.setattr(ffmpeg_finder.shutil, "which", lambda name: None)

        with _fresh_finder(monkeypatch, _setup) as reloaded:
            assert reloaded.FFMPEG_PATH == BARE_NAME
            # The environment gains a resolvable ffmpeg *after* the import.
            monkeypatch.setattr(ffmpeg_finder.shutil, "which", lambda name: hit)
            assert reloaded.FFMPEG_PATH == BARE_NAME
        # And the restore-reload left a value that matches a live resolution,
        # so the constant is never stale-but-silently-kept after an import.
        assert ffmpeg_finder.FFMPEG_PATH == ffmpeg_finder._find_ffmpeg()

    def test_reimporting_re_resolves_a_stale_singleton(
        self, tmp_path, monkeypatch
    ) -> None:
        """A cached path that has since become invalid is replaced on the next
        import, because the constant is recomputed rather than reused."""
        hit = _make_exe(str(tmp_path / "bin"), "ffmpeg")
        stale = str(tmp_path / "gone" / "ffmpeg")

        # ``__file__`` is redirected to an empty directory rather than the
        # probes being stubbed out: these two tests assert on the real
        # filesystem state of the resolved path (``os.path.isfile``/``lexists``
        # below are deliberately *not* patched, so the assertions cannot be
        # satisfied by a stub).
        app = str(tmp_path / "app")

        def _stale_env(mp: pytest.MonkeyPatch) -> None:
            mp.setattr(ffmpeg_finder.sys, "platform", "linux")
            mp.setattr(ffmpeg_finder, "__file__", os.path.join(app, "f.py"))
            mp.setattr(ffmpeg_finder.shutil, "which", lambda name: stale)

        with _fresh_finder(monkeypatch, _stale_env) as reloaded:
            assert reloaded.FFMPEG_PATH == stale
            assert not os.path.lexists(reloaded.FFMPEG_PATH)

        def _fresh_env(mp: pytest.MonkeyPatch) -> None:
            mp.setattr(ffmpeg_finder.sys, "platform", "linux")
            mp.setattr(ffmpeg_finder, "__file__", os.path.join(app, "f.py"))
            mp.setattr(ffmpeg_finder.shutil, "which", lambda name: hit)

        with _fresh_finder(monkeypatch, _fresh_env) as reloaded:
            assert reloaded.FFMPEG_PATH == os.path.abspath(hit)
            assert os.path.isfile(reloaded.FFMPEG_PATH)


class TestGetStartupinfo:
    """Startupinfo helper (canonical: audio_suite_shared.subprocess_utils)."""

    def test_returns_startupinfo_on_windows(self) -> None:
        si = get_startupinfo()
        assert si is not None

    def test_returns_none_on_non_windows(self) -> None:
        from unittest.mock import patch

        with patch(
            "audio_suite_shared.subprocess_utils.os.name",
            "posix",
        ):
            result = get_startupinfo()
        assert result is None
