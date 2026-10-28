"""
platform_support.py — The declared platform support matrix (plan G1, audit #20).

The suite is Windows-first.  Before this module, "does AudioSuite-Pro run on
Linux or macOS?" was unanswerable from the repository: the platform-conditional
code was real but undocumented, and the only automated signal came from a
Windows test suite.  This module is the *declaration* — the enumeration of
every platform-conditional branch in first-party code, classified into three
explicit tiers, together with the evidence that justifies each classification.

The tiers
---------

``portable-core``
    The non-Windows arm of the branch is implemented **and** a test exercises
    it under a simulated non-Windows platform value.  The branch is therefore
    deliberate rather than accidental.

``windows-only``
    The branch guards a genuinely Windows-only capability (Win32 drive and
    SCSI APIs, ``icacls`` ACL hardening, the Win32 console-suppression
    handles).  The non-Windows side is a documented stop, placeholder or
    no-op — never a silent different behaviour.

``unverified``
    A non-Windows arm exists in the code but **no test runs it** under any
    platform value, so nothing in the suite proves it behaves correctly.
    This tier is deliberately cheap and honest: when in doubt, a branch is
    Unverified rather than Portable (plan G1, "Risks").

What this module is *not*
-------------------------

A claim of certification for a foreign platform.  ``portable-core`` means "the
non-Windows branch is implemented and covered by a test that runs it under a
mocked platform value".  A declared *selection* of the suite also runs on a
real Ubuntu host on every push — the ``posix-smoke`` CI job, plan item R-12 of
``PLAN_audit_2026-10-24_deferred_p2p3.md`` — and it runs without a display, so
its Tk-dependent tests skip there.  That is the whole of the foreign-host
evidence: every other statement here is a statement about *the code and its
tests*, no tool has been driven end to end on Linux, and macOS has not been
exercised at all.  The README renders this caveat verbatim; an over-claim here
is the defect this item exists to remove.

Single source of truth
----------------------

``PLATFORM_BRANCHES`` is the declaration.  ``utilities/
generate_readme_platform_matrix.py`` renders the README section from it, and
``audio_suite_shared/tests/test_platform_support.py`` scans the first-party
tree and fails if a platform-conditional branch exists that is not listed here
— so a new ``if sys.platform == ...`` cannot be added without classifying it.

Changed in 1.4.0: the Windows Explorer shell-integration branch is gone with
the withdrawn feature (PLAN D73), so its matrix row and declaration were
removed in the same change.
Changed in 1.4.1: the ``os.name`` trap section's underline matches its title, so
the generated API reference renders the section instead of warning (PLAN D98).
Changed in 1.4.1: the diagnostic scripts are classified - the peak-RSS probe's
two ``sys.platform`` arms are declared, unverified for POSIX because their
``resource`` import cannot run on this host (PLAN D100).
Changed in 2.1.4: the CD ripper's eject and reveal branches moved out of
``ui/results_tab.py`` into ``core/drive_control.py`` and are declared as
portable core there, so the results-tab row now covers only the open-folder
dispatch (audit R-08, plan C3).
Changed in 2.1.0: declared the launcher venv bootstrap's platform branch
(``venv_bootstrap.py`` chooses ``Scripts/`` or ``bin/`` by platform value, and
both arms are tested with an explicit ``platform`` argument), so the
enumeration lock stays an exact bijection with the tree.
Changed in 2.1.0: the Master Driver's duplicate ``open_help`` resolver is gone
(PLAN_docs_consolidation P1.5) - ``master_driver/app.py`` routes its Help button
through the shared ``_open_help_standard``, so the private dispatch that was
declared here no longer exists and its three rows were removed in the same
change.
Changed in 2.1.6: the caveat now records the one foreign-host run that exists —
the ``posix-smoke`` job's declared selection on ``ubuntu-latest`` (R-12,
PLAN_audit_2026-10-24_deferred_p2p3.md) — and the sentence citing plan item A4
is gone.  That marker described the CI ffmpeg install, not a Linux leg; the
tier definitions are unchanged, because running a real host does not
reclassify a branch.

The ``os.name`` trap: patch ``sys.platform``, not ``os.name``
----------------------------------------------------------------

A test that wants to exercise a non-Windows arm must patch ``sys.platform``.
Patching ``os.name`` looks equivalent and is not: ``pathlib.Path()`` consults
``os.name`` when it *constructs*, so on a Windows host an ``os.name = "posix"``
patch makes every path built inside the patch a ``PosixPath`` — different
``.parts``, different ``is_absolute()``, different ``resolve()``.  The test
then measures a Windows interpreter running PosixPath semantics, a hybrid that
corresponds to no real platform, and any difference it reports is an artefact
of the patch rather than a property of the branch.

Two consequences, both visible in the table above:

* Branches keyed on ``os.name`` that also build a ``Path`` are left
  **Unverified** rather than given a test that would only prove the harness
  is self-consistent.
* Branches keyed on ``sys.platform`` are sound to simulate, because
  ``pathlib`` never reads it.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Tier constants ─────────────────────────────────────────────────────────────

PORTABLE_CORE = "portable-core"
WINDOWS_ONLY = "windows-only"
UNVERIFIED = "unverified"

#: Declaration order is the rendering order (most-supported first).
TIERS: tuple[str, ...] = (PORTABLE_CORE, WINDOWS_ONLY, UNVERIFIED)

TIER_TITLES: dict[str, str] = {
    PORTABLE_CORE: "Portable core",
    WINDOWS_ONLY: "Windows-only",
    UNVERIFIED: "Unverified",
}

TIER_DEFINITIONS: dict[str, str] = {
    PORTABLE_CORE: (
        "The non-Windows branch is implemented and a test runs it under a "
        "simulated non-Windows platform value."
    ),
    WINDOWS_ONLY: (
        "A genuinely Windows-only capability. The non-Windows side is a "
        "documented stop, placeholder or no-op."
    ),
    UNVERIFIED: (
        "A non-Windows branch exists but no test runs it, so nothing proves "
        "it behaves correctly. Untested, not unsupported."
    ),
}

#: The caveat that must accompany the rendered matrix verbatim.
MATRIX_CAVEAT = (
    "**A declared selection of this suite runs on a real Ubuntu host on every "
    "push — and nothing else has been executed on a foreign platform.** The "
    "`posix-smoke` CI job "
    "(PLAN_audit_2026-10-24_deferred_p2p3.md, item R-12) runs the CLI surface "
    "plus the module list named in `.github/workflows/ci.yml`, on "
    "`ubuntu-latest` **with no display**, and prints what the missing display "
    "cost — nothing today, because no module in that selection needs Tk, which "
    "is also why it moves no tier. The tier definitions are unchanged "
    '— "Portable core" still means *the non-Windows branch is implemented and '
    "covered by a test that runs it under a simulated platform value* — so no "
    "tool has been driven end to end on Linux, and macOS has not been "
    "exercised at all."
)


# ── Branch declaration ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PlatformBranch:
    """One platform-conditional site in first-party code.

    Attributes:
        module: Repository-relative module path with POSIX separators.
        source: The branch's source line, whitespace-normalised.  Together
            with ``module`` this is the stable identity used by the
            enumeration lock, so a line-number shift (an unrelated edit
            above it) does not invalidate the classification while a
            genuine re-classification does.
        tier: One of ``PORTABLE_CORE``, ``WINDOWS_ONLY``, ``UNVERIFIED``.
        subsystem: The human-named subsystem the branch belongs to.
        behaviour: What the non-Windows side does.
        evidence: The test that justifies the tier, or ``"none"`` for
            ``UNVERIFIED``.
        occurrences: How many times this exact branch appears in the module.
            A dispatch shared by two functions (``open_path`` and
            ``open_help``, say) is one classification but several sites, and
            the enumeration lock verifies the count so a second, untested
            copy cannot be added unnoticed.
        tool: The manifest id of the tool the branch belongs to, or ``None``
            for the shared layer and the Master Driver (which are on every
            tool's path and are declared as a surface, not per tool).
    """

    module: str
    source: str
    tier: str
    subsystem: str
    behaviour: str
    evidence: str
    occurrences: int = 1
    tool: str | None = None


_SHARED = "shared layer (audio_suite_shared)"
_DRIVER = "Master Driver"

PLATFORM_BRANCHES: tuple[PlatformBranch, ...] = (
    # ── Shared layer ──────────────────────────────────────────────────────────
    PlatformBranch(
        module="audio_suite_shared/platform_utils.py",
        source='if sys.platform == "win32":',
        tier=PORTABLE_CORE,
        subsystem="Open a file or folder (Help / Open buttons)",
        behaviour=(
            "win32 uses os.startfile; darwin shells out to `open`; every "
            "other platform uses `xdg-open`. All three arms are implemented."
        ),
        evidence="audio_suite_shared/tests/test_platform_utils.py",
        occurrences=2,
    ),
    PlatformBranch(
        module="audio_suite_shared/platform_utils.py",
        source="os.startfile(path)",
        tier=PORTABLE_CORE,
        subsystem="Open a file or folder (Help / Open buttons)",
        behaviour="The win32 arm of the three-way dispatch above.",
        evidence="audio_suite_shared/tests/test_platform_utils.py",
    ),
    PlatformBranch(
        module="audio_suite_shared/platform_utils.py",
        source='elif sys.platform == "darwin":',
        tier=PORTABLE_CORE,
        subsystem="Open a file or folder (Help / Open buttons)",
        behaviour="The macOS arm; the Linux/POSIX fallback follows it.",
        evidence="audio_suite_shared/tests/test_platform_utils.py",
        occurrences=2,
    ),
    PlatformBranch(
        module="audio_suite_shared/platform_utils.py",
        source="os.startfile(str(help_file))",
        tier=PORTABLE_CORE,
        subsystem="Open a generated user guide",
        behaviour="The win32 arm of the guide-launching dispatch.",
        evidence="audio_suite_shared/tests/test_platform_utils.py",
    ),
    PlatformBranch(
        module="audio_suite_shared/venv_bootstrap.py",
        source='if (platform or sys.platform).startswith("win"):',
        tier=PORTABLE_CORE,
        subsystem="Launcher re-execution into the project's .venv",
        behaviour=(
            "win32 finds the venv's Scripts/python.exe (or pythonw.exe when the "
            "launch is windowed); every other platform finds bin/python with a "
            "bin/python3 fallback. Both arms are implemented and tested with "
            "an explicit platform value, so neither depends on the host."
        ),
        evidence="audio_suite_shared/tests/test_venv_bootstrap.py",
    ),
    PlatformBranch(
        module="audio_suite_shared/platform_utils.py",
        source='if sys.platform != "win32":',
        tier=UNVERIFIED,
        subsystem="Saved window placement (`setup_window`)",
        behaviour=(
            "Non-Windows screens cannot be queried, so any position that is "
            "not wildly off-screen is accepted."
        ),
        evidence="none",
    ),
    PlatformBranch(
        module="audio_suite_shared/secure_subprocess.py",
        source='max_path_len = 260 if sys.platform == "win32" else 4096',
        tier=PORTABLE_CORE,
        subsystem="Subprocess argument validation",
        behaviour=(
            "Path-length ceiling: 260 on Windows (MAX_PATH), 4096 elsewhere "
            "(PATH_MAX). Read per call, so a non-Windows sys.platform is "
            "genuinely exercised."
        ),
        evidence=(
            "audio_suite_shared/tests/test_platform_support.py"
            "::TestPortableCoreCLI::test_posix_path_ceiling_is_4096_not_260"
        ),
    ),
    PlatformBranch(
        module="audio_suite_shared/security/input_validator.py",
        source='MAX_PATH_LENGTH = 260 if os.name == "nt" else 4096',
        tier=UNVERIFIED,
        subsystem="Path validation limits",
        behaviour=(
            "Same 260/4096 ceiling as the subprocess validator, but bound at "
            "import time, so patching os.name afterwards cannot change it — "
            "only a module reload under a different platform would."
        ),
        evidence="none",
    ),
    PlatformBranch(
        module="audio_suite_shared/security/input_validator.py",
        source='if os.name == "nt":',
        tier=UNVERIFIED,
        subsystem="Windows reserved device names",
        behaviour=(
            "An extra per-component fullmatch pass that runs only on Windows, "
            "on top of the platform-independent reserved-name and "
            "safe-character checks. It cannot be honestly exercised by "
            "patching os.name: pathlib.Path() consults os.name when it "
            "constructs, so such a test silently switches to PosixPath and "
            "measures a hybrid that exists on no real platform (see the "
            "os.name trap note in the module docstring)."
        ),
        evidence="none",
    ),
    PlatformBranch(
        module="audio_suite_shared/security/key_manager.py",
        source='if os.name == "nt":',
        tier=WINDOWS_ONLY,
        subsystem="Key-file permission hardening",
        behaviour=(
            "Windows restricts the key file with `icacls`; every other "
            "platform uses chmod 0600. The capability is available on both — "
            "only the mechanism is Windows-specific, so this downgrades no "
            "tool's tier."
        ),
        evidence=(
            "audio_suite_shared/tests/test_key_manager.py"
            "::TestUnixPermissionsAppliedWhenSaving"
        ),
    ),
    PlatformBranch(
        module="audio_suite_shared/suite_config.py",
        source='if os.name == "nt":',
        tier=WINDOWS_ONLY,
        subsystem="Config file cross-process lock",
        behaviour=(
            "Windows uses msvcrt.locking for exclusive file locks; "
            "every other platform uses fcntl.flock. Both arms are "
            "implemented; the capability is available on all platforms."
        ),
        evidence="audio_suite_shared/tests/test_i1_robustness.py",
        occurrences=2,
    ),
    PlatformBranch(
        module="audio_suite_shared/styles.py",
        source='if sys.platform != "win32":',
        tier=UNVERIFIED,
        subsystem="Light/Dark theme detection",
        behaviour=(
            "Only Windows reads the AppsUseLightTheme registry value; every "
            "other platform falls back to the documented 'Light' default."
        ),
        evidence="none",
    ),
    PlatformBranch(
        module="audio_suite_shared/subprocess_utils.py",
        source='if os.name == "nt":',
        tier=PORTABLE_CORE,
        subsystem="Console suppression for subprocesses",
        behaviour=(
            "Returns a hiding STARTUPINFO / CREATE_NO_WINDOW on Windows and "
            "None / 0 everywhere else, which Popen accepts unchanged."
        ),
        evidence=(
            "replaygain_analyzer/tests/test_replaygain_pipeline.py"
            "::TestCreateFlagsAndStartupInfo"
        ),
        occurrences=2,
    ),
    PlatformBranch(
        module="audio_suite_shared/ui_common.py",
        source='if sys.platform == "win32":',
        tier=PORTABLE_CORE,
        subsystem="Open the suite log file",
        behaviour=(
            "win32 os.startfile, darwin `open`, otherwise `xdg-open` — the "
            "same three-way dispatch as platform_utils."
        ),
        evidence="audio_suite_shared/tests/test_ui_common.py",
    ),
    PlatformBranch(
        module="audio_suite_shared/ui_common.py",
        source="os.startfile(log_file)",
        tier=PORTABLE_CORE,
        subsystem="Open the suite log file",
        behaviour="The win32 arm of the three-way dispatch above.",
        evidence="audio_suite_shared/tests/test_ui_common.py",
    ),
    PlatformBranch(
        module="audio_suite_shared/ui_common.py",
        source='elif sys.platform == "darwin":',
        tier=PORTABLE_CORE,
        subsystem="Open the suite log file",
        behaviour="The macOS arm; Linux/POSIX falls through to `xdg-open`.",
        evidence="audio_suite_shared/tests/test_ui_common.py",
    ),
    # ── Per-tool packages ─────────────────────────────────────────────────────
    PlatformBranch(
        module="album_art_normalizer/album_art_normalizer.py",
        source="system = platform.system()",
        tier=PORTABLE_CORE,
        subsystem="Open the containing folder",
        behaviour=(
            "Dispatches on platform.system() to os.startfile / `open` / `xdg-open`."
        ),
        evidence="album_art_normalizer/tests/test_album_art_normalizer.py",
        tool="album_art_normalizer",
    ),
    PlatformBranch(
        module="album_art_normalizer/album_art_normalizer.py",
        source="os.startfile(path)",
        tier=PORTABLE_CORE,
        subsystem="Open the containing folder",
        behaviour="The Windows arm of the three-way dispatch above.",
        evidence="album_art_normalizer/tests/test_album_art_normalizer.py",
        tool="album_art_normalizer",
    ),
    PlatformBranch(
        module="audio_normalizer/utils/ffmpeg_finder.py",
        source='if sys.platform == "win32":',
        tier=PORTABLE_CORE,
        subsystem="ffmpeg discovery",
        behaviour=(
            "Adds the Windows-only `C:\\ffmpeg\\bin` fallback location; PATH "
            "and module-local discovery still apply on every platform."
        ),
        evidence="audio_normalizer/tests/test_ffmpeg_finder.py",
        tool="audio_normalizer",
    ),
    PlatformBranch(
        module="audio_normalizer/utils/ffmpeg_finder.py",
        source=('local_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"'),
        tier=PORTABLE_CORE,
        subsystem="ffmpeg discovery",
        behaviour="Binary filename extension only.",
        evidence="audio_normalizer/tests/test_ffmpeg_finder.py",
        tool="audio_normalizer",
    ),
    PlatformBranch(
        module="replaygain_analyzer/core/ffmpeg_metrics.py",
        source='if os.name == "nt":',
        tier=UNVERIFIED,
        subsystem="ffmpeg discovery",
        behaviour=(
            "Windows checks for an ffmpeg.exe shipped beside the module "
            "first; every other platform goes straight to PATH."
        ),
        evidence="none",
        occurrences=1,
        tool="replaygain",
    ),
    # ── CD Ripper (Windows-only subsystem) ────────────────────────────────────
    PlatformBranch(
        module="cd_ripper/core/disc.py",
        source='return os.name == "nt"',
        tier=WINDOWS_ONLY,
        subsystem="CD drive enumeration",
        behaviour=(
            "platform_supported() is the single gate: it reports False "
            "off-Windows and the drive list is empty, so the UI never offers "
            "a device extraction cannot act on."
        ),
        evidence="cd_ripper/tests/test_ripper_platform_fail_fast.py",
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/core/drive_handler.py",
        source='if sys.platform == "win32":',
        tier=WINDOWS_ONLY,
        subsystem="SCSI pass-through device I/O",
        behaviour=(
            "Imports ctypes.wintypes and loads kernel32 with use_last_error; "
            "off-Windows both are placeholders and every call site that needs "
            "them is guarded."
        ),
        evidence="cd_ripper/tests/test_ripper_platform_fail_fast.py",
        occurrences=2,
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/core/drive_handler.py",
        source='if sys.platform != "win32":',
        tier=WINDOWS_ONLY,
        subsystem="SCSI pass-through device I/O",
        behaviour=(
            "Fails fast with AudioExternalToolError naming ctypes.windll as "
            "the missing requirement, instead of an AttributeError."
        ),
        evidence="cd_ripper/tests/test_ripper_platform_fail_fast.py",
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/core/drive_handler.py",
        source='f"ctypes.windll, unavailable on {sys.platform!r}). "',
        tier=WINDOWS_ONLY,
        subsystem="SCSI pass-through device I/O",
        behaviour=(
            "The fail-fast message, which names the platform it was refused "
            "on so the limitation is never silent."
        ),
        evidence="cd_ripper/tests/test_ripper_platform_fail_fast.py",
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/ui/results_tab.py",
        source='if os.name == "nt":',
        tier=UNVERIFIED,
        subsystem="Rip results: open output folder",
        behaviour=(
            "Windows uses os.startfile; elsewhere the code shells out to "
            "`xdg-open` through the secure wrapper. No test runs the "
            "non-Windows arm. Eject and reveal are no longer branched here: "
            "they moved to core/drive_control.py, classified as portable core above."
        ),
        evidence="none",
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/core/drive_control.py",
        source='if sys.platform == "win32":',
        tier=PORTABLE_CORE,
        subsystem="Rip results: eject the tray / reveal a ripped file",
        behaviour=(
            "win32 opens the tray through MCI (no process at all) and "
            "selects the file with `explorer.exe /select,`; every other "
            "platform runs `eject` and `xdg-open` through the secure "
            "wrapper. Both arms are implemented and both are driven by a "
            "simulated sys.platform in the module's own suite."
        ),
        evidence="cd_ripper/tests/test_drive_control.py",
        occurrences=2,
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/ui/results_tab.py",
        source="os.startfile(out_dir)",
        tier=UNVERIFIED,
        subsystem="Rip results: open output folder",
        behaviour="The Windows arm of the open-folder dispatch above.",
        evidence="none",
        tool="cd_ripper",
    ),
    PlatformBranch(
        module="cd_ripper/ui/setup_tab.py",
        source=('_local_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"'),
        tier=UNVERIFIED,
        subsystem="ffmpeg discovery (rip setup tab)",
        behaviour="Binary filename extension only.",
        evidence="none",
        tool="cd_ripper",
    ),
    # ── Master Driver ─────────────────────────────────────────────────────────
    PlatformBranch(
        module="master_driver/ui/cards/typography_card.py",
        source=(
            '] + _PLATFORM_FONTS.get(sys.platform, ["DejaVu Sans", "Liberation Sans"])'
        ),
        tier=UNVERIFIED,
        subsystem="Typography card font list",
        behaviour=(
            "Windows and macOS get their own font families; every other "
            "platform gets the DejaVu/Liberation fallback, which is computed "
            "at import time and so is not re-evaluated by a patched "
            "sys.platform."
        ),
        evidence="none",
    ),
    # ── Diagnostic scripts ────────────────────────────────────────────────────
    PlatformBranch(
        module="utilities/measure_worker_memory.py",
        source='if sys.platform == "win32":',
        tier=UNVERIFIED,
        subsystem="Peak-RSS measurement for the worker-memory budget",
        behaviour=(
            "Windows reads PeakWorkingSetSize through GetProcessMemoryInfo, "
            "and that arm is what this host exercises every run "
            "(utilities/tests/test_measure_worker_memory.py asserts the value "
            "is non-zero and responds to a 64 MB allocation). The other arm "
            "cannot be tested on this host, so the helper is untested for "
            "POSIX rather than unsupported: a patched sys.platform would hit "
            "`import resource` and raise ImportError instead of measuring."
        ),
        evidence="none",
    ),
    PlatformBranch(
        module="utilities/measure_worker_memory.py",
        source='if sys.platform == "darwin":',
        tier=UNVERIFIED,
        subsystem="Peak-RSS measurement for the worker-memory budget",
        behaviour=(
            "ru_maxrss is bytes on macOS and KiB on Linux, so the arm exists, "
            "but it cannot be simulated on a Windows host for the same reason "
            "as the branch above: the POSIX arm imports `resource`, which does "
            "not exist here."
        ),
        evidence="none",
    ),
)


# ── Derived views (no second list) ─────────────────────────────────────────────


def branches_for_tier(tier: str) -> tuple[PlatformBranch, ...]:
    """Return every branch classified *tier*, in declaration order.

    Args:
        tier: One of the module-level tier constants.

    Returns:
        The matching branches, or an empty tuple for an unknown tier.
    """
    return tuple(branch for branch in PLATFORM_BRANCHES if branch.tier == tier)


def tool_tier(tool_id: str) -> str:
    """Return the support tier of the tool with manifest id *tool_id*.

    The tier is derived from the declaration rather than from a second list:
    a tool is Windows-only if and only if one of its own branches is
    Windows-only.  Every other tool is Portable core — meaning its own
    package holds no platform-conditional code at all.

    Args:
        tool_id: The manifest id (the single source of truth used for the
            card filename, the CLI command and the driver toggle key).

    Returns:
        ``WINDOWS_ONLY`` or ``PORTABLE_CORE``.  Unverified branches are
        reported by :func:`branches_for_tier`, not by widening a tool's
        tier, because an untested branch in a tool's own package is only
        possible for a Windows-only tool today.
    """
    if any(
        branch.tool == tool_id and branch.tier == WINDOWS_ONLY
        for branch in PLATFORM_BRANCHES
    ):
        return WINDOWS_ONLY
    return PORTABLE_CORE


def windows_only_tools() -> tuple[str, ...]:
    """Return the manifest ids of every Windows-only tool, sorted."""
    ids = {
        branch.tool
        for branch in PLATFORM_BRANCHES
        if branch.tier == WINDOWS_ONLY and branch.tool is not None
    }
    return tuple(sorted(ids))


def tier_counts() -> dict[str, int]:
    """Return the number of declared branches per tier, in tier order."""
    return {tier: len(branches_for_tier(tier)) for tier in TIERS}


def render_matrix_table() -> str:
    """Render the branch enumeration as a Markdown table.

    Returns:
        A Markdown table with one row per declared branch, grouped by tier
        (most-supported first) and ordered by module within a tier.  The
        module cell carries the declaration's stable identity so a reader
        can find the branch, and the evidence cell states which test
        justifies the tier (``none`` for Unverified).
    """
    lines = [
        "| Tier | Module | Subsystem | Non-Windows behaviour | Evidence |",
        "|---|---|---|---|---|",
    ]
    for tier in TIERS:
        for branch in sorted(
            branches_for_tier(tier), key=lambda b: (b.module, b.source)
        ):
            tool = f" (tool `{branch.tool}`)" if branch.tool else ""
            behaviour = branch.behaviour.replace("|", "\\|")
            lines.append(
                f"| {TIER_TITLES[tier]} | `{branch.module}`{tool} "
                f"| {branch.subsystem} | {behaviour} | {branch.evidence} |"
            )
    return "\n".join(lines)


def render_tier_summary() -> str:
    """Render the per-tier summary bullets with their definitions."""
    counts = tier_counts()
    lines: list[str] = []
    for tier in TIERS:
        lines.append(
            f"* **{TIER_TITLES[tier]}** ({counts[tier]} declared branch"
            f"{'es' if counts[tier] != 1 else ''}) — "
            f"{TIER_DEFINITIONS[tier]}"
        )
    return "\n".join(lines)
