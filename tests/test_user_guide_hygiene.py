"""Tests for the user-guide tree's generator and backup hygiene.

Plan iteration 7, item A2: every individual-program user guide must be
reproducible from a committed generator script, and no backup or superseded
artifact may remain tracked. These locks convert that into an enforced
invariant so the tree cannot silently rot again:

1. *Source lock* - every tracked ``.docx``/``.pptx`` under ``user_guides/``
   is either rendered from a Markdown source beside it, or written by a
   committed generator, or one of three named files awaiting retirement. A
   hand-edited guide with no source is undetectable after the fact, which is
   how the Tempo Analyzer guide drifted out of date for years; a new binary
   fails this lock until someone gives it a source deliberately.
2. *Backup lock* - no ``*.bak``/``*.bak*`` file is tracked anywhere under
   ``user_guides/``. These are dead weight that can never be regenerated or
   reviewed, and they silently mask the fact that a guide is stale.
3. *Logging-guide lock* - no ``*_Logging_Guide.docx`` is tracked. The
   per-tool logging guides were superseded by the in-app log files and the
   per-tool "Log Files" section of each user guide; a central logging guide
   may be reintroduced later, but it is not a per-tool artifact.
4. *Generator lock* - no ``generate_logging_guide.py`` remains, matching (3).
5. *Changelog lock* - ``CHANGELOG.md``'s ``[Unreleased]`` section is never blank.
   The file declares Keep-a-Changelog and SemVer compliance, so an empty
   ``[Unreleased]`` is a silent lie: a release-sized iteration lands with
   nothing recorded. An explicit "nothing yet" line satisfies the lock; a bare
   heading does not.
6. *Guide-version lock* - any guide showing a version must render it from
   ``audio_suite_shared.project_version.declared_version()`` (plan D15), not a
   literal, so a release bump never leaves a stale label behind.

The tracked-file set is read through ``git ls-files`` so the locks assert on
what is actually *committed*, not on what merely exists in a working tree -
an untracked stray file cannot fail CI, and a tracked one must.

Changed in 1.0.1: adds lock (6), which pins every guide's version subtitle to
``declared_version()`` (plan D15).
Changed in 2.1.0: adds ``TestSuiteOverviewGenerators`` (lock 7), which extends
the generator principle to the suite-level artefacts outside
``individual_programs/`` - the logging guide and the new-user presentation. The
six ``.docx`` with no generator at all are dispositioned per file in
PLAN_docs_consolidation (§6); the byte-level freshness check for every artefact
lands with P4.1.
Changed in 2.1.0: lock (1) now covers **every** tracked ``.docx``/``.pptx`` in
``user_guides/``, not just ``individual_programs/``, so a new binary can no
longer appear outside the rendered tree (PLAN_docs_consolidation P4.1). The
three files still awaiting retirement are listed with a reason, and the list
length is asserted, so it cannot quietly grow. Designed artefacts (the
presentation) and derived ones (the logging guide, whose sample log lines are
rendered from the live formatter) stay generator-backed; a ``.pptx`` layout is
code, not prose, and a Markdown source for it would be a lossy duplicate.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_ROOT = REPO_ROOT / "user_guides" / "individual_programs"

#: The one renderer every guide artefact comes from.
RENDERER = REPO_ROOT / "utilities" / "build_user_guides.py"


def _load_renderer() -> Any:
    """Load the shared guide renderer as a module.

    The renderer is a script under ``utilities/`` (not an importable package),
    so it is loaded by path. It is registered in ``sys.modules`` first because
    ``@dataclass`` resolves annotations through that mapping.

    Returns:
        The loaded module, typed ``Any``: a script has no static surface here.

    Raises:
        AssertionError: If the renderer is missing or cannot be loaded, which
            would make the source/artefact locks pass vacuously.
    """
    assert RENDERER.is_file(), f"shared guide renderer missing: {RENDERER}"
    spec = importlib.util.spec_from_file_location("guide_renderer", RENDERER)
    assert spec is not None and spec.loader is not None, f"cannot load {RENDERER}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["guide_renderer"] = module
    spec.loader.exec_module(module)
    return module


def _markdown_sources() -> list[Path]:
    """Return every Markdown guide source under ``user_guides/``.

    Returns:
        Source paths, sorted.
    """
    return sorted((REPO_ROOT / "user_guides").rglob("*_User_Guide.md"))


def tracked_paths() -> list[str]:
    """Return every tracked path in the repository, POSIX-style.

    Returns:
        Sorted, forward-slashed paths relative to the repo root.

    Raises:
        subprocess.CalledProcessError: if git is unavailable or the tree is
            not a git repository.
    """
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return sorted(result.stdout.splitlines())


@pytest.fixture(scope="module")
def tracked() -> list[str]:
    """Tracked repository paths, shared across the module."""
    return tracked_paths()


def _under(tracked: list[str], directory: Path) -> list[str]:
    """Filter tracked paths to those inside ``directory``."""
    prefix = directory.relative_to(REPO_ROOT).as_posix() + "/"
    return [path for path in tracked if path.startswith(prefix)]


class TestGeneratorHygiene:
    """Every committed user guide must be reproducible."""

    #: Artefacts written by a committed generator rather than a Markdown source.
    GENERATOR_BACKED: frozenset[str] = frozenset(
        {
            "user_guides/suite_overview/LOGGING_SYSTEM_GUIDE.docx",
            "user_guides/suite_overview/AudioSuite-Pro_New_User_Presentation.pptx",
        }
    )

    #: Artefacts that still have no source at all, per PLAN §6 (D9).
    #: Empty since the three orphans were retired into ``docs/`` (P4.1 close-out).
    PENDING_RETIREMENT: dict[str, str] = {}

    def test_guide_root_exists(self) -> None:
        """The individual-program guide tree is the subject of these locks."""
        assert GUIDE_ROOT.is_dir(), f"missing guide root: {GUIDE_ROOT}"

    def test_every_artefact_is_reproducible(self, tracked: list[str]) -> None:
        """Every tracked ``.docx``/``.pptx`` has a source or a generator.

        This is the whole-tree form of the old ``individual_programs`` lock:
        a binary that nothing can rebuild is exactly what accumulated outside
        the rendered tree before (PLAN_docs_consolidation P4.1). Three states
        are accepted, and nothing else:

        * **Markdown-backed** - a ``.md`` source beside the artefact. Its
          freshness is asserted by :meth:`test_artefacts_match_their_sources`.
        * **Generator-backed** - a committed script that names the artefact in
          its own text (see :class:`TestSuiteOverviewGenerators`). Freshness is
          not compared, because regenerating a designed deck or a guide whose
          sample lines come from the live formatter would rewrite a tracked
          binary during the test run.
        * **Pending retirement** - a binary with no source yet, each entry
          naming the plan's disposition. The list is empty today: the three
          orphan guides were retired into `docs/` and deleted. It stays
          length-asserted so re-opening that state means editing the plan and
          this test together, deliberately.

        The allowed sets are data, but the counts are asserted: adding a
        pending file, or silently dropping one, fails here.
        """
        artefacts = [
            path
            for path in tracked
            if path.startswith("user_guides/")
            and Path(path).suffix in {".docx", ".pptx"}
            # ``git ls-files`` still lists a file deleted but not yet committed;
            # a deletion cannot carry a Markdown source, so the lock judges the
            # binaries that exist (the same fix PLAN D15b made tree-wide).
            and (REPO_ROOT / path).is_file()
        ]
        assert len(artefacts) >= 30, (
            f"only {len(artefacts)} artefacts found - the scan is broken, so "
            "this lock would pass vacuously"
        )

        assert len(self.PENDING_RETIREMENT) == 0, (
            "a binary was parked for retirement again; retire it into docs/ "
            "and delete it, or record why in the plan's §6 deliberately"
        )
        assert len(self.GENERATOR_BACKED) == 2, (
            "the generator-backed list changed size; a new designed artefact "
            "needs its own generator and a deliberate entry here"
        )

        offenders: list[str] = []
        for artefact in artefacts:
            if artefact in self.PENDING_RETIREMENT:
                if not (REPO_ROOT / artefact).is_file():
                    offenders.append(
                        f"{artefact}: listed for retirement but no longer on disk; "
                        "drop the entry with the file"
                    )
                continue
            if artefact in self.GENERATOR_BACKED:
                continue  # TestSuiteOverviewGenerators owns the generator checks
            source = Path(artefact).with_suffix(".md").as_posix()
            if not (REPO_ROOT / source).is_file():
                offenders.append(
                    f"{artefact}: no Markdown source, no generator and no "
                    "retirement entry - add the source (then run "
                    "`python utilities/build_user_guides.py`) or classify it"
                )

        unknown = sorted(
            (set(self.PENDING_RETIREMENT) | self.GENERATOR_BACKED) - set(artefacts)
        )
        offenders.extend(
            f"{path}: classified but not a tracked artefact" for path in unknown
        )

        assert not offenders, (
            "unreproducible documentation binaries:\n  " + "\n  ".join(offenders)
        )

    def test_sources_parse_through_the_renderer(self) -> None:
        """Every source parses with a title, so the renderer can rebuild it."""
        sources = _markdown_sources()
        assert sources, "no guide sources found - locks would pass vacuously"
        renderer = _load_renderer()
        for source in sources:
            guide = renderer.parse_guide(source.read_text(encoding="utf-8"), source)
            assert guide.title, f"{source}: parsed with an empty title"

    def test_artefacts_match_their_sources(self) -> None:
        """Each committed artefact is what the renderer produces from its source.

        The walk is tree-wide, not ``individual_programs/``-wide: the whole-tree
        lock accepts a Markdown source anywhere under ``user_guides/``, so the
        freshness check has to follow the same subject or a suite-level source
        would be accepted without ever being compared to its artefact.
        """
        sources = _markdown_sources()
        assert sources, "no guide sources found - locks would pass vacuously"
        renderer = _load_renderer()
        problems: list[str] = []
        for source in sources:
            problems.extend(renderer.check_guide(source))
        assert not problems, (
            "committed user-guide artefacts are stale; run "
            "`python utilities/build_user_guides.py`:\n  " + "\n  ".join(problems)
        )


class TestNoBackupArtifacts:
    """Backup copies of guides are never a deliverable."""

    def test_no_backup_files_tracked(self, tracked: list[str]) -> None:
        """No ``.bak`` file is tracked under user_guides/."""
        offenders = [
            path
            for path in _under(tracked, REPO_ROOT / "user_guides")
            if ".bak" in Path(path).name
        ]
        assert not offenders, (
            "tracked backup files under user_guides/ - regenerate the guide "
            "from its generator instead of keeping a .bak copy:\n  "
            + "\n  ".join(offenders)
        )


class TestNoPerToolLoggingGuides:
    """Per-tool logging guides were superseded by each user guide."""

    def test_no_logging_guide_tracked(self, tracked: list[str]) -> None:
        """No ``*_Logging_Guide.docx`` is tracked."""
        offenders = [p for p in tracked if p.endswith("_Logging_Guide.docx")]
        assert not offenders, (
            "per-tool logging guides are tracked again - the log behaviour is "
            "documented in each user guide's 'Log Files' section:\n  "
            + "\n  ".join(offenders)
        )

    def test_no_logging_guide_generator_tracked(self, tracked: list[str]) -> None:
        """No ``generate_logging_guide.py`` remains."""
        offenders = [p for p in tracked if p.endswith("generate_logging_guide.py")]
        assert not offenders, (
            "per-tool logging-guide generators are tracked again:\n  "
            + "\n  ".join(offenders)
        )


def _registered_guide_filenames() -> list[str]:
    """Extract the ``guide_to_program`` keys from ``platform_utils``.

    ``guide_to_program`` is a function-local dict inside ``open_help``, so it
    is not importable. The keys are read with ``ast`` rather than by
    splitting source lines, so a reformatted or re-indented dict is still
    parsed correctly.

    Returns:
        Every guide filename registered for the Help button.

    Raises:
        AssertionError: if the dict or a key cannot be found.
    """
    import ast

    source_path = REPO_ROOT / "audio_suite_shared" / "platform_utils.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "guide_to_program" not in targets:
            continue
        if not isinstance(node.value, ast.Dict):
            break
        names = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        assert names, "guide_to_program parsed as an empty dict"
        return [str(name) for name in names]

    raise AssertionError("guide_to_program dict not found in platform_utils.py")


class TestGuideRegistration:
    """Registered help guides must still exist on disk.

    ``open_help`` is never invoked here: a registered name shells out to the
    OS opener, and an unregistered one raises a modal ``messagebox``. Either
    would hang a headless run, so this lock stays purely static.
    """

    def test_registered_guides_exist(self) -> None:
        """Every ``guide_to_program`` entry resolves to a file on disk."""
        registered = _registered_guide_filenames()
        assert registered, "no guide filenames parsed from guide_to_program"

        directories = [d for d in sorted(GUIDE_ROOT.iterdir()) if d.is_dir()]
        assert directories, "no guide directories found"

        missing = [
            name
            for name in registered
            if not any((directory / name).is_file() for directory in directories)
        ]
        assert not missing, (
            "guide_to_program references guides that do not exist:\n  "
            + "\n  ".join(missing)
        )

    def test_no_logging_guide_is_registered(self) -> None:
        """A removed logging guide must not linger in the Help registry."""
        offenders = [n for n in _registered_guide_filenames() if "Logging" in n]
        assert not offenders, (
            "platform_utils.guide_to_program still registers removed logging "
            "guides:\n  " + "\n  ".join(offenders)
        )


# ---------------------------------------------------------------------------
# CHANGELOG hygiene
# ---------------------------------------------------------------------------

CHANGELOG = REPO_ROOT / "CHANGELOG.md"

#: Heading that opens the not-yet-versioned section.
UNRELEASED_MARKER = "## [Unreleased]"

#: A maintainer may legitimately declare an empty section - but only in words.
#: Any of these phrases counts as that declaration.
_EXPLICIT_EMPTY_PHRASES: tuple[str, ...] = (
    "nothing yet",
    "nothing to record",
    "no changes yet",
    "_nothing recorded_",
)


def _changelog_text() -> str:
    """Return the changelog's full text.

    Returns:
        The decoded contents of ``CHANGELOG.md``.
    """
    return CHANGELOG.read_text(encoding="utf-8")


def _unreleased_section() -> str:
    """Extract the body of the ``[Unreleased]`` section.

    The extraction is bounded by the next version heading, so a malformed
    changelog cannot make this return the whole file.

    Returns:
        The section's text with surrounding blank lines removed.

    Raises:
        AssertionError: if the ``[Unreleased]`` heading is absent, or if no
            later version heading bounds it (which would mean the parse
            matched nothing rather than finding an empty section).
    """
    text = _changelog_text()
    assert UNRELEASED_MARKER in text, (
        f"{CHANGELOG.name} has no {UNRELEASED_MARKER!r} heading"
    )
    remainder = text.split(UNRELEASED_MARKER, 1)[1]
    section: list[str] = []
    for line in remainder.splitlines():
        if line.startswith("## "):
            break
        section.append(line)
    else:
        raise AssertionError(
            f"{CHANGELOG.name}: {UNRELEASED_MARKER!r} is not followed by a version "
            "heading - the section boundary could not be found, so this check "
            "would pass vacuously"
        )
    return "\n".join(section).strip()


class TestChangelogHygiene:
    """``CHANGELOG.md`` must not carry a blank ``[Unreleased]`` section."""

    def test_unreleased_section_is_populated_or_explicitly_empty(self) -> None:
        """Record the release-sized changes, or say in words that there are none.

        Non-vacuity comes from ``_unreleased_section``, which fails when the
        heading or its boundary is missing - so this test can never pass by
        matching nothing.
        """
        section = _unreleased_section()
        if any(phrase in section.lower() for phrase in _EXPLICIT_EMPTY_PHRASES):
            return
        assert section, (
            f"{CHANGELOG.name}: the {UNRELEASED_MARKER!r} section is empty. "
            "Record the user-visible changes under Keep-a-Changelog headings "
            "('### Added' / '### Changed' / '### Fixed'), or state explicitly "
            "that there is nothing to record (e.g. 'Nothing yet.')."
        )

    def test_version_headings_are_well_formed(self) -> None:
        """Every section heading names a version and, if released, a date."""
        headings = [
            line
            for line in _changelog_text().splitlines()
            if line.startswith("## ") and not line.startswith("### ")
        ]
        assert len(headings) >= 2, (
            f"{CHANGELOG.name}: expected an [Unreleased] heading plus at least "
            f"one released version, found {headings}"
        )
        released = [h for h in headings if h != UNRELEASED_MARKER]
        assert released, f"{CHANGELOG.name}: no released version section found"
        for heading in released:
            assert heading.startswith("## ["), (
                f"{CHANGELOG.name}: version heading is not bracketed: {heading!r}"
            )
            assert " - " in heading, (
                f"{CHANGELOG.name}: released version heading has no date: {heading!r}"
            )

    def test_keep_a_changelog_and_semver_are_declared(self) -> None:
        """The compliance the lock relies on is stated in the file itself."""
        text = _changelog_text()
        assert "keepachangelog.com" in text.lower(), (
            f"{CHANGELOG.name} must cite Keep a Changelog for the format the "
            "hygiene lock enforces"
        )
        assert "semver.org" in text.lower(), (
            f"{CHANGELOG.name} must cite SemVer for the versioning the lock enforces"
        )


#: Every guide version subtitle opens with this literal (D15 shape).
_VERSION_PREFIX = "Version "


class TestGuideVersionLabels:
    """Any guide that displays a version must source it dynamically (plan D15)."""

    def test_version_labels_track_the_declared_version(
        self, tracked: list[str]
    ) -> None:
        """A version subtitle reads ``Version <declared_version()> — <Month Year>``.

        The subtitle is discovered by scanning each tracked guide's paragraphs,
        so a guide that hardcodes a version fails here instead of silently
        drifting. The generation month varies, so only the version is locked.
        """
        from docx import Document

        from audio_suite_shared.project_version import declared_version

        expected = f"Version {declared_version()} \u2014 "
        guides = [
            path
            for path in _under(tracked, GUIDE_ROOT)
            if path.endswith("_User_Guide.docx")
        ]
        assert guides, "no committed user guides found - the lock would pass vacuously"

        labelled = 0
        offenders: list[str] = []
        for guide in guides:
            document = Document(str(REPO_ROOT / guide))
            for paragraph in document.paragraphs:
                text = paragraph.text.strip()
                if not text.startswith(_VERSION_PREFIX):
                    continue
                labelled += 1
                if not text.startswith(expected):
                    offenders.append(f"{guide}: {text!r}")
                break

        assert labelled, (
            "no guide carries a version subtitle - the lock would pass vacuously"
        )
        assert not offenders, (
            "guide version subtitles must be sourced dynamically "
            f"({expected!r}); found hardcoded/stale labels:\n  "
            + "\n  ".join(offenders)
        )


class TestSuiteOverviewGenerators:
    """Suite-level artefacts stay reproducible from a committed generator.

    Lock (7), PLAN_docs_consolidation P1.8. Locks (1)-(4) only cover
    ``individual_programs/``, which is how six hand-made ``.docx`` accumulated
    outside it. This lock covers the suite-level artefacts that *do* have a
    generator, so one cannot lose its script in a refactor. The remaining
    orphans are dispositioned per file in the plan (§6) rather than exempted
    here.

    The generators are read as text, never imported: their module bodies write
    the artefact on import, so importing one would rewrite a committed file
    during a test run. Byte-level freshness (regenerate, then compare zip
    entries) is P4.1, not this lock.
    """

    #: (generator path, artefact filename) pairs this lock holds to.
    BACKED_ARTEFACTS: tuple[tuple[str, str], ...] = (
        (
            "user_guides/suite_overview/generate_logging_system_guide.py",
            "LOGGING_SYSTEM_GUIDE.docx",
        ),
        (
            "user_guides/suite_overview/generate_presentation.py",
            "AudioSuite-Pro_New_User_Presentation.pptx",
        ),
    )

    def test_each_suite_artefact_has_its_generator(self, tracked: list[str]) -> None:
        """Every listed artefact ships with the script that writes it."""
        assert len(self.BACKED_ARTEFACTS) >= 2, (
            "the checked set is empty - this lock would pass vacuously"
        )
        offenders: list[str] = []
        for generator, artefact in self.BACKED_ARTEFACTS:
            generator_path = REPO_ROOT / generator
            if generator not in tracked:
                offenders.append(f"{generator}: generator is not tracked")
                continue
            if not generator_path.is_file():
                offenders.append(f"{generator}: generator is missing on disk")
                continue
            source = generator_path.read_text(encoding="utf-8")
            if artefact not in source:
                offenders.append(
                    f"{generator}: never names {artefact!r} - it cannot be the "
                    "generator for that artefact"
                )
            if not (GUIDE_ROOT.parent / "suite_overview" / artefact).is_file():
                offenders.append(f"{artefact}: artefact is missing on disk")
        assert not offenders, (
            "suite-level generator hygiene problems:\n  " + "\n  ".join(offenders)
        )
