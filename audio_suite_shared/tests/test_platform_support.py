"""Tests for the declared platform support matrix (plan G1, audit #20).

The declaration in ``audio_suite_shared/platform_support.py`` is only
worth having if it cannot drift from the code it describes.  These tests
make that mechanical:

1. *Enumeration lock* — an AST scan of the first-party tree finds every
   ``sys.platform`` / ``os.name`` / ``platform.system()`` / ``os.startfile``
   site, and the scan must be an exact bijection with ``PLATFORM_BRANCHES``:
   nothing undeclared, nothing declared that has gone away, and identical
   multiplicity.  The scan reads the AST, so a platform token inside a
   comment or a string literal is not mistaken for a branch.
2. *Lock-is-real lock* — a synthetic in-memory source proves the scanner
   actually reports an undeclared branch, so a green enumeration lock can
   never be an artefact of a scanner that finds nothing.
3. *Tier integrity* — a Portable-core claim must cite a test; an Unverified
   claim must admit it has none; a ``tool`` must be a real manifest id.
4. *Evidence lock* — every cited test path must exist on disk, so a
   re-classification cannot lean on a deleted test.
5. *Derivation lock* — the tool tiers are derived from the declaration, and
   the rendered README (matrix section and the tool index ``Platform``
   column) must match a fresh render.

The declaration is deliberately conservative: a branch with a non-Windows
arm that no test runs is Unverified, not Portable.  "Untested, not
unsupported" is the honest reading of that tier.

Changed in 1.3.0: the portable-core set grows to 27 tools / 26 portable CLI
commands with the Spectral Viewer (D42).

Changed in 2.0.0: the portable-core set grows to 28 tools / 27 portable CLI
commands with the Stem Separator (Sprint 6, Item 6.1).  Its ML stack is an
optional extra rather than a platform branch: without it the tool still opens,
validates a run and completes a dry run on every platform.

Changed in 2.1.0: reads only first-party manifests, so a plugin tool cannot skew the
platform matrix.
"""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from collections import Counter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest

from audio_suite_shared.platform_support import (
    MATRIX_CAVEAT,
    PLATFORM_BRANCHES,
    PORTABLE_CORE,
    TIERS,
    UNVERIFIED,
    WINDOWS_ONLY,
    branches_for_tier,
    render_matrix_table,
    render_tier_summary,
    tier_counts,
    tool_tier,
    windows_only_tools,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
README = REPO_ROOT / "README.md"

#: Directory names whose .py files are not first-party production code.
#: ``utilities`` is deliberately NOT excluded: it is first-party code and the
#: lock is stronger for covering it.
_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".github",
        ".idea",
        ".junie",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "audiosuite_pro.egg-info",
        "build",
        "dist",
        "htmlcov",
        "logs",
        "node_modules",
        "test",
        "tests",
        "user_guides",
        "venv",
    }
)

#: The platform-conditional expressions the matrix must account for.
_PLATFORM_ATTRS = frozenset(
    {"sys.platform", "os.name", "os.startfile", "platform.system"}
)

_BEGIN = "<!-- PLATFORM MATRIX: BEGIN"
_END = "<!-- PLATFORM MATRIX: END"
_END_SUFFIX = " -->"


def _dotted(node: ast.expr) -> str | None:
    """Return ``a.b.c`` for an attribute/name chain, else None."""
    parts: list[str] = []
    cur: ast.expr = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if not isinstance(cur, ast.Name):
        return None
    parts.append(cur.id)
    return ".".join(reversed(parts))


def scan_source(source: str) -> Counter[tuple[str, str]]:
    """Count platform-conditional sites in *source*, keyed by normalised line.

    Working from the AST (rather than a regex over the text) is what makes
    this safe to enforce: ``sys.platform`` mentioned in a comment or a
    docstring is not a branch, and cannot be silently added to the matrix.

    Args:
        source: Python source text.

    Returns:
        A counter of ``(normalised source line, count)``.  Normalisation
        collapses runs of whitespace, so re-indenting a branch does not
        invalidate its classification.
    """
    lines = source.splitlines()
    counter: Counter[tuple[str, str]] = Counter()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Attribute):
            continue
        if _dotted(node) not in _PLATFORM_ATTRS or node.end_lineno is None:
            continue
        # end_lineno, not lineno: a call such as platform.system() is itself
        # an ast.Attribute whose own lineno is the line, but a multi-line
        # expression must be attributed to the line carrying the token.
        text = lines[node.end_lineno - 1]
        counter[(" ".join(text.strip().split()), 1)] += 1
    return counter


def scan_tree() -> Counter[tuple[str, str]]:
    """Scan every first-party production module for platform branches."""
    counter: Counter[tuple[str, str]] = Counter()
    for path in sorted(REPO_ROOT.rglob("*.py")):
        rel = path.relative_to(REPO_ROOT)
        if any(part in _EXCLUDED_DIRS for part in rel.parts):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            continue
        for (text, _), count in scan_source(source).items():
            counter[(rel.as_posix(), text)] += count
    return counter


def declared_counter() -> Counter[tuple[str, str]]:
    """Return the declaration's own site counts, keyed like :func:`scan_tree`."""
    counter: Counter[tuple[str, str]] = Counter()
    for branch in PLATFORM_BRANCHES:
        counter[(branch.module, branch.source)] += branch.occurrences
    return counter


def _load_generator(name: str) -> ModuleType:
    """Import a ``utilities/`` script by path (it is not a package)."""
    spec = spec_from_file_location(
        f"generate_{name}", REPO_ROOT / "utilities" / f"generate_readme_{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestEnumerationLock:
    """The declaration is an exact bijection with the code."""

    @staticmethod
    @pytest.fixture(scope="class")
    def scanned() -> Counter[tuple[str, str]]:
        return scan_tree()

    def test_every_platform_branch_in_the_tree_is_declared(
        self, scanned: Counter[tuple[str, str]]
    ) -> None:
        declared = declared_counter()
        undeclared = sorted(set(scanned) - set(declared))
        assert not undeclared, (
            "Platform-conditional code with no entry in "
            f"audio_suite_shared/platform_support.py: {undeclared}. Classify it "
            "as portable-core (with the test that runs its non-Windows arm), "
            "windows-only, or unverified — an unclassified branch is the exact "
            "ambiguity this matrix exists to remove."
        )
        assert scanned == declared, (
            "Declared branch multiplicity drifted from the code: "
            f"code={dict(scanned)} declared={dict(declared)}"
        )

    def test_no_declared_branch_has_vanished(self) -> None:
        stale = sorted(set(declared_counter()) - set(scan_tree()))
        assert not stale, (
            f"PLATFORM_BRANCHES declares branches that no longer exist: {stale}. "
            "Remove the row, or restore the code — an orphaned row is a claim "
            "about code that is not there."
        )

    def test_enumeration_lock_can_actually_fail(self) -> None:
        """A green enumeration lock must not be a scanner that finds nothing.

        Proved on synthetic source rather than by editing the repository, so
        the check is hermetic: if the scanner ever stops reporting branches,
        this fails and the lock above stops being trustworthy.
        """
        source = textwrap.dedent(
            """\
            import os
            import platform
            import sys


            def pick(path):
                if sys.platform == "win32":
                    return os.startfile(path)
                return platform.system()
            """
        )
        found = {text: count for (text, _), count in scan_source(source).items()}
        assert found == {
            'if sys.platform == "win32":': 1,
            "return os.startfile(path)": 1,
            "return platform.system()": 1,
        }
        # And the synthetic branch is genuinely undeclared, so the lock's
        # failure mode is reachable.
        assert set(found) - {text for text, _ in declared_counter()}

    def test_scanner_ignores_comments_and_docstrings(self) -> None:
        """A platform token in prose must not be counted as a branch."""
        source = textwrap.dedent(
            '''\
            """Uses sys.platform and os.startfile on win32."""


            def note():
                # os.name == "nt" is discussed here, not branched on.
                return None
            '''
        )
        assert not scan_source(source)

    def test_declaration_has_no_duplicate_keys(self) -> None:
        keys = [(branch.module, branch.source) for branch in PLATFORM_BRANCHES]
        duplicates = [key for key, count in Counter(keys).items() if count > 1]
        assert not duplicates, (
            f"PLATFORM_BRANCHES repeats a branch key: {duplicates}. Use the "
            "occurrences field to record multiplicity instead."
        )

    def test_declaration_covers_a_meaningful_number_of_branches(self) -> None:
        """Guards against a scan that silently stops seeing production code."""
        assert len(PLATFORM_BRANCHES) >= 20
        assert sum(b.occurrences for b in PLATFORM_BRANCHES) >= 30


class TestTierIntegrity:
    """The classification obeys its own rules."""

    def test_every_branch_has_a_known_tier(self) -> None:
        unknown = sorted({b.tier for b in PLATFORM_BRANCHES if b.tier not in TIERS})
        assert not unknown, f"Unknown tier(s) declared: {unknown}"

    def test_portable_core_claims_cite_the_test_that_justifies_them(self) -> None:
        uncited = [
            f"{b.module} :: {b.source}"
            for b in branches_for_tier(PORTABLE_CORE)
            if b.evidence == "none"
        ]
        assert not uncited, (
            "A portable-core branch must name the test that runs its "
            f"non-Windows arm; these cite none: {uncited}. Either cite the "
            "test or demote the branch to unverified — a portable claim with "
            "no test is the over-claim this item removes."
        )

    def test_unverified_branches_admit_they_have_no_evidence(self) -> None:
        overclaimed = [
            f"{b.module} :: {b.source}"
            for b in branches_for_tier(UNVERIFIED)
            if b.evidence != "none"
        ]
        assert not overclaimed, (
            "An unverified branch that cites evidence is mis-classified — it "
            f"is portable-core: {overclaimed}"
        )

    def test_every_branch_documents_its_non_windows_behaviour(self) -> None:
        empty = [
            f"{b.module} :: {b.source}"
            for b in PLATFORM_BRANCHES
            if not b.behaviour.strip()
        ]
        assert not empty, f"Branches with no documented behaviour: {empty}"

    def test_windows_only_branches_never_downgrade_a_portable_tool(self) -> None:
        """A shared-layer Windows-only branch must not mark a tool Windows-only.

        ``key_manager`` hardens the key file with ``icacls`` on Windows and
        ``chmod 0600`` elsewhere: the *capability* is portable, only the
        mechanism is not.  Key storage must stay available on POSIX.
        """
        shared_windows_only = [
            b for b in branches_for_tier(WINDOWS_ONLY) if b.tool is None
        ]
        assert shared_windows_only, (
            "expected the shared-layer icacls branch to be declared "
            "windows-only with tool=None"
        )
        for branch in shared_windows_only:
            assert branch.module.startswith("audio_suite_shared/")

    def test_occurrences_are_positive(self) -> None:
        bad = [
            f"{b.module} :: {b.source}" for b in PLATFORM_BRANCHES if b.occurrences < 1
        ]
        assert not bad, f"Branch occurrences must be >= 1: {bad}"


class TestEvidenceLock:
    """A tier claim cannot lean on a test that does not exist."""

    def test_every_cited_test_path_exists(self) -> None:
        missing: list[str] = []
        for branch in PLATFORM_BRANCHES:
            if branch.evidence == "none":
                continue
            # Strip any "::Class::test" selector before touching the disk.
            path_part = branch.evidence.split("::", 1)[0]
            if not (REPO_ROOT / path_part).exists():
                missing.append(f"{branch.module} cites {path_part}")
        assert not missing, (
            "Matrix evidence points at files that do not exist: "
            f"{missing}. Re-classify the branch, or fix the citation."
        )


class TestToolTiers:
    """Tool tiers are derived from the declaration, not a second list."""

    def test_cd_ripper_is_the_only_windows_only_tool(self) -> None:
        assert windows_only_tools() == ("cd_ripper",)

    def test_every_manifest_tool_resolves_to_a_tier(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        tools = get_registry().first_party
        assert len(tools) == 30
        for manifest in tools:
            assert tool_tier(manifest.id) in TIERS

    def test_tool_tier_is_derived_from_its_own_branches(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        for manifest in get_registry().first_party:
            expected = (
                WINDOWS_ONLY
                if any(
                    b.tool == manifest.id and b.tier == WINDOWS_ONLY
                    for b in PLATFORM_BRANCHES
                )
                else PORTABLE_CORE
            )
            assert tool_tier(manifest.id) == expected, manifest.id

    def test_every_branch_tool_is_a_manifest_id(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        ids = {manifest.id for manifest in get_registry().first_party}
        unknown = sorted(
            {b.tool for b in PLATFORM_BRANCHES if b.tool is not None} - ids
        )
        assert not unknown, (
            f"PLATFORM_BRANCHES attributes branches to unknown tool ids: "
            f"{unknown}. The manifest id is the single source of truth."
        )

    def test_tier_counts_cover_every_branch_exactly_once(self) -> None:
        counts = tier_counts()
        assert set(counts) == set(TIERS)
        assert sum(counts.values()) == len(PLATFORM_BRANCHES)
        assert all(count > 0 for count in counts.values()), (
            f"a declared tier has no branches: {counts}"
        )

    def test_unknown_tier_yields_no_branches(self) -> None:
        assert branches_for_tier("not-a-tier") == ()


class TestReadmeDriftLock:
    """README renders exactly what the declaration says."""

    def test_matrix_section_matches_a_fresh_render(self) -> None:
        generator = _load_generator("platform_matrix")
        text = README.read_text(encoding="utf-8")
        begin = text.find(_BEGIN)
        end = text.rfind(_END)
        assert begin != -1 and end != -1, "PLATFORM MATRIX markers are missing"
        end_of_marker = end + len(_END) + len(_END_SUFFIX)
        current = text[begin:end_of_marker].replace("\r\n", "\n")
        fresh = generator.render_platform_matrix()
        assert current == fresh, (
            "README platform matrix drifted from "
            "audio_suite_shared/platform_support.py — re-run "
            "utilities/generate_readme_platform_matrix.py"
        )

    def test_readme_states_the_caveat_verbatim(self) -> None:
        """The anti-over-claim caveat is part of the generated block."""
        assert MATRIX_CAVEAT in README.read_text(encoding="utf-8")
        assert "No tool in this suite has been executed on a real Linux" in (
            README.read_text(encoding="utf-8")
        )

    def test_readme_does_not_claim_cross_platform_certification(self) -> None:
        """Regression lock for the over-claim G1 was raised to remove."""
        text = README.read_text(encoding="utf-8").lower()
        for phrase in (
            "cross-platform",
            "fully cross-platform",
            "works on linux and macos",
        ):
            assert phrase not in text, (
                f"README still claims {phrase!r}; platform support is declared "
                "as the tiered matrix, and no foreign host has been exercised"
            )

    def test_tool_index_platform_column_matches_the_declaration(self) -> None:
        from audio_suite_shared.platform_support import TIER_TITLES
        from audio_suite_shared.tool_plugin import get_registry

        generator = _load_generator("tool_index")
        block = generator.render_tool_index().replace("\r\n", "\n")
        assert "| Platform |" in block
        for manifest in get_registry().first_party:
            expected = TIER_TITLES[tool_tier(manifest.id)]
            row = next(
                line
                for line in block.splitlines()
                if line.startswith(f"| {manifest.name} |")
            )
            assert row.endswith(f"| {expected} |"), (
                f"{manifest.id}: tool index row does not end with the declared "
                f"tier {expected!r}: {row}"
            )

    def test_matrix_table_mentions_every_declared_module(self) -> None:
        table = render_matrix_table()
        for module in {b.module for b in PLATFORM_BRANCHES}:
            assert f"`{module}`" in table, f"{module} missing from the matrix table"
        assert render_tier_summary().count("* **") == len(TIERS)


class TestPortableCoreCLI:
    """The portable core is *executed* under a non-Windows platform, not asserted.

    Plan G1's mitigation for "classification can be wrong in the permissive
    direction" is that a tool may only be called portable if its core path
    actually runs under a mocked non-Windows ``sys.platform``.  So these tests
    drive the real Click entry point with the platform value patched, and a
    failure here means the matrix is over-claiming.

    The whole class patches ``sys.platform`` and never ``os.name`` — see the
    "os.name trap" note in ``platform_support``'s docstring: ``pathlib.Path()``
    consults ``os.name`` at construction, so an ``os.name`` patch would build
    PosixPaths on a Windows host and measure a hybrid that exists on no real
    platform.
    """

    @staticmethod
    def _portable_commands() -> list[str]:
        """Return the CLI commands of every portable-core tool."""
        from audio_suite_shared.tool_plugin import get_registry

        return [
            manifest.cli_command
            for manifest in get_registry().first_party
            if manifest.cli_command and tool_tier(manifest.id) == PORTABLE_CORE
        ]

    def test_the_portable_set_covers_every_tool_but_cd_ripper(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        tools = get_registry().first_party
        with_cli = [m for m in tools if m.cli_command]
        assert [m.id for m in tools if tool_tier(m.id) == WINDOWS_ONLY] == ["cd_ripper"]
        # The one documented gap: Undo Tag Edits is GUI-only, so there is no
        # subcommand to drive under a mocked platform. Named here so that a
        # *new* tool without one is a failure, not a silent pass.
        assert [m.id for m in tools if not m.cli_command] == ["undo_tag_edits"]
        assert len(with_cli) == 29
        # 28 of the 29 are portable-core; cd-rip is the Windows-only one.
        assert len(self._portable_commands()) == 28

    @pytest.mark.parametrize("command", _portable_commands())
    def test_portable_tool_help_resolves_under_a_non_windows_platform(
        self, command: str
    ) -> None:
        """Each portable tool's CLI must load and describe itself off-Windows."""
        from click.testing import CliRunner

        from audio_suite_shared.cli_app import cli

        with patch("sys.platform", "linux"):
            result = CliRunner().invoke(cli, [command, "--help"])
        assert result.exit_code == 0, (
            f"'{command} --help' failed under a mocked Linux platform: "
            f"{result.output}{result.exception!r}"
        )
        assert "Usage:" in result.output

    def test_a_real_command_runs_end_to_end_under_a_non_windows_platform(
        self, tmp_path: Path
    ) -> None:
        """Not just ``--help``: a real scan completes and reports real counts.

        ``stats`` is the honest end of the portable core — pure Python and
        mutagen, no ffmpeg, no GUI — so it exercises the shared decode path
        the matrix claims is platform-independent.
        """
        import json

        from click.testing import CliRunner

        from audio_suite_shared.cli_app import cli

        music = tmp_path / "music"
        music.mkdir()
        (music / "a.mp3").write_bytes(b"fake mp3")
        (music / "b.flac").write_bytes(b"fake flac")

        with patch("sys.platform", "linux"):
            result = CliRunner().invoke(cli, ["stats", str(music), "--json"])
        assert result.exit_code == 0, (
            f"'stats' failed under a mocked Linux platform: {result.output}"
            f"{result.exception!r}"
        )
        # ``result.output`` is stdout+stderr merged (Click >= 8.2), and the
        # scan logs a full traceback per unreadable file, so slicing from the
        # first "{" only parses when the merge order happens to favour stdout.
        # The JSON contract is the stdout channel; read that.
        payload = json.loads(result.stdout)
        assert payload["total_files"] == 2
        assert payload["scan_path"] == str(music)

    def test_the_windows_only_tool_gates_itself_on_posix(self) -> None:
        """cd_ripper must refuse clearly, not degrade silently.

        Patching ``os.name`` is sound *here* specifically because
        ``platform_supported()`` only compares ``os.name`` and
        ``list_cd_drives()`` returns before it reaches ``ctypes`` — neither
        constructs a ``Path``, so the trap documented in the matrix does not
        apply. The deeper fail-fast behaviour (no ``ctypes.windll`` access
        off-Windows) is locked in cd_ripper/tests/test_ripper_platform_fail_fast.py,
        which the matrix cites as this tier's evidence.
        """
        from cd_ripper.core import disc

        with patch.object(disc.os, "name", "posix"):
            assert disc.platform_supported() is False
            assert disc.list_cd_drives() == []

    def test_posix_path_ceiling_is_4096_not_260(self, tmp_path: Path) -> None:
        """Evidence for the secure_subprocess matrix row: the arm really runs.

        The ceiling is read per call, so patching ``sys.platform`` genuinely
        selects the POSIX branch rather than restating a constant — the
        difference between the two outcomes is the proof.
        """
        from audio_suite_shared.secure_subprocess import (
            SubprocessSecurityError,
            validate_arguments,
        )

        long_arg = str(tmp_path / ("a" * 300))
        with patch("sys.platform", "win32"):
            with pytest.raises(SubprocessSecurityError, match="too long"):
                validate_arguments([long_arg])
        with patch("sys.platform", "linux"):
            assert validate_arguments([long_arg]) == [long_arg]

    def test_patching_sys_platform_does_not_disturb_pathlib(self) -> None:
        """Why the matrix prefers sys.platform: pathlib ignores it entirely."""
        from pathlib import Path

        before = type(Path("x")).__name__
        with patch("sys.platform", "linux"):
            assert type(Path("x")).__name__ == before
            assert Path("C:/tmp/a b").is_absolute() == (before == "WindowsPath")

    def test_patching_os_name_would_flip_pathlib_flavour(self) -> None:
        """Regression lock for the ``os.name`` trap documented in the matrix.

        Proved directly, because the failure mode it guards against is
        invisible: a test that patches ``os.name`` on Windows looks like it is
        simulating POSIX, while silently building PosixPaths and measuring a
        platform that does not exist.  This asserts the trap is real, so a
        future author who reaches for ``os.name`` sees why the two
        ``input_validator`` rows stay Unverified.
        """
        import os
        from pathlib import Path, PureWindowsPath

        if os.name != "nt":  # pragma: no cover - the trap is Windows-specific
            pytest.skip("os.name trap only manifests on a Windows host")
        with patch.object(os, "name", "posix"):
            assert not isinstance(Path("C:/tmp/x"), PureWindowsPath)
            assert Path("C:/tmp/x").is_absolute() is False


class TestAttributableSkips:
    """Windows-only subsystems must be skipped *attributably*, or not at all.

    Plan G1: "For each Windows-only subsystem, add a skip with a reason naming
    the platform requirement, so the B4 blanket mechanism is not the thing
    hiding it."  A blanket display/GUI skip (B4) is fine for a widget, but it
    must not be what conceals a platform-dependent code path — a test that is
    skipped for the wrong reason reports green on a platform that cannot run
    it.  These tests make the reason mandatory and check each Windows-only
    subsystem is accounted for.
    """

    @staticmethod
    def _test_files() -> list[Path]:
        """Every first-party test module (the *opposite* filter to the scan).

        The branch scan excludes test directories because a platform token in
        a test is a mock, not a branch; this walk needs those very files.
        Only virtualenv and cache directories are dropped.
        """
        ignored = _EXCLUDED_DIRS - {"test", "tests"}
        files: list[Path] = []
        for path in sorted(REPO_ROOT.rglob("test_*.py")):
            rel = path.relative_to(REPO_ROOT)
            if any(part in ignored for part in rel.parts):
                continue
            files.append(path)
        return files

    @staticmethod
    def _platform_gated_skips(path: Path) -> list[tuple[int, str | None]]:
        """Return ``(lineno, reason)`` for every platform-conditioned skip.

        Both spellings are handled, because they carry their information in
        different places:

        * ``pytest.mark.skipif(<cond>, reason=...)`` — the condition is the
          first positional argument and the reason must be a keyword.
        * ``pytest.skip("...")`` — the message *is* the reason, and the
          platform condition lives in the enclosing ``if``.

        A skip counts as platform-conditioned when that condition mentions
        ``os.name``, ``sys.platform`` or ``platform.system()``.
        """
        found: list[tuple[int, str | None]] = []
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = _dotted(node.func) or ""
            keyword_reason: str | None = None
            for keyword in node.keywords:
                if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
                    keyword_reason = str(keyword.value.value)

            if func.endswith("skipif"):
                if not node.args:
                    continue
                condition = ast.unparse(node.args[0])
                reason = keyword_reason
            elif func.endswith("skip"):
                message = (
                    str(node.args[0].value)
                    if node.args and isinstance(node.args[0], ast.Constant)
                    else keyword_reason
                )
                enclosing = parents.get(node)
                condition = (
                    ast.unparse(enclosing.test) if isinstance(enclosing, ast.If) else ""
                )
                reason = message or keyword_reason
            else:
                continue

            if not any(
                token in condition
                for token in ("os.name", "sys.platform", "platform.system")
            ):
                continue
            found.append((node.lineno, reason))
        return found

    def test_every_platform_skip_names_its_platform_requirement(self) -> None:
        silent: list[str] = []
        for path in self._test_files():
            for lineno, reason in self._platform_gated_skips(path):
                rel = path.relative_to(REPO_ROOT).as_posix()
                if not reason or not reason.strip():
                    silent.append(f"{rel}:{lineno} (no reason)")
                elif not any(
                    word in reason.lower()
                    for word in ("win32", "windows", "nt", "posix", "linux", "mac")
                ):
                    # A reason that does not name the platform is a
                    # "skip because I said so" marker, not an attribution.
                    silent.append(
                        f"{rel}:{lineno} (reason does not name a platform: {reason!r})"
                    )
        assert not silent, (
            f"Platform-gated skips must name the platform requirement: {silent}"
        )

    def test_windows_only_subsystems_are_accounted_for(self) -> None:
        """Each Windows-only module's package is either skipped or fully mocked."""
        packages = {
            branch.module.split("/")[0]
            for branch in PLATFORM_BRANCHES
            if branch.tier == WINDOWS_ONLY
        }
        assert packages, "no Windows-only subsystem declared"

        for package in sorted(packages):
            tests_dir = REPO_ROOT / package / "tests"
            if not tests_dir.is_dir():
                pytest.fail(
                    f"{package} has a Windows-only subsystem but no test "
                    "directory, so its platform behaviour is unverified"
                )
            gated = [
                (path, lineno, reason)
                for path in self._test_files()
                if package in path.relative_to(REPO_ROOT).parts
                for lineno, reason in self._platform_gated_skips(path)
            ]
            rel_paths = {path.relative_to(REPO_ROOT).as_posix() for path, _, _ in gated}
            if gated:
                assert all(reason for _, _, reason in gated), (
                    f"{package}: a platform-gated skip has no reason: "
                    f"{[r for r in rel_paths]}"
                )
            else:
                # No platform-gated skip at all: the suite must be mocking the
                # Win32 layer, i.e. run everywhere.  Assert it really does run
                # by collecting the package's tests in this interpreter.
                collected = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        f"{tests_dir.relative_to(REPO_ROOT)}",
                        "--collect-only",
                        "-q",
                        "--no-header",
                        "-p",
                        "no:cacheprovider",
                    ],
                    capture_output=True,
                    text=True,
                    cwd=REPO_ROOT,
                    check=False,
                )
                assert collected.returncode == 0, collected.stdout + collected.stderr

    def test_cd_ripper_declares_its_win32_requirement(self) -> None:
        """The real Windows-only tool must have an attributable skip."""
        gated = [
            (path.relative_to(REPO_ROOT).as_posix(), reason)
            for path in self._test_files()
            if path.relative_to(REPO_ROOT).parts[0] == "cd_ripper"
            for _, reason in self._platform_gated_skips(path)
        ]
        assert gated, (
            "cd_ripper is the Windows-only tool but declares no platform-gated "
            "skip; its Win32 tests must say so rather than be hidden"
        )
        assert any(reason and "win32" in reason.lower() for _, reason in gated), (
            f"cd_ripper skips do not name the Win32 requirement: {gated}"
        )


class TestModulePurity:
    """The declaration module must be importable without a GUI.

    ``platform_support`` is imported by generators and by a headless test
    run, so it must not drag in tkinter.  A purity claim cannot be verified
    in-process (the root conftest already imports tkinter), so the check runs
    in a subprocess with ``sys.modules["tkinter"] = None`` — any import of
    tkinter then raises — plus a negative control proving the shadowing
    genuinely blocks the import rather than silently passing.
    """

    def test_imports_without_tkinter(self) -> None:
        program = textwrap.dedent(
            """\
            import sys
            sys.modules["tkinter"] = None
            from audio_suite_shared.platform_support import PLATFORM_BRANCHES
            print(len(PLATFORM_BRANCHES))
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert int(result.stdout.strip()) == len(PLATFORM_BRANCHES)

    def test_negative_control_the_shadowing_actually_blocks(self) -> None:
        program = textwrap.dedent(
            """\
            import sys
            sys.modules["tkinter"] = None
            try:
                import tkinter
            except ImportError:
                print("blocked")
            else:
                print("NOT blocked")
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "blocked"
