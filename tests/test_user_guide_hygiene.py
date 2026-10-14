"""Tests for the user-guide tree's generator and backup hygiene.

Plan iteration 7, item A2: every individual-program user guide must be
reproducible from a committed generator script, and no backup or superseded
artifact may remain tracked. These locks convert that into an enforced
invariant so the tree cannot silently rot again:

1. *Generator lock* - every directory under
   ``user_guides/individual_programs/`` that contains a committed
   ``*_User_Guide.docx`` also contains a committed ``generate_guide.py``.
   A hand-edited guide with no generator is undetectable after the fact,
   which is how the Tempo Analyzer guide drifted out of date for years.
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
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_ROOT = REPO_ROOT / "user_guides" / "individual_programs"

# Directories that legitimately hold no generated guide. Empty by design: a
# new entry here is a deliberate, reviewed decision to exempt a directory.
GENERATOR_EXEMPT_DIRS: frozenset[str] = frozenset()


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

    def test_guide_root_exists(self) -> None:
        """The individual-program guide tree is the subject of these locks."""
        assert GUIDE_ROOT.is_dir(), f"missing guide root: {GUIDE_ROOT}"

    def test_every_guide_has_a_generator(self, tracked: list[str]) -> None:
        """Each directory shipping a user guide also ships its generator."""
        guides = [
            p for p in _under(tracked, GUIDE_ROOT) if p.endswith("_User_Guide.docx")
        ]
        assert guides, "no committed user guides found - locks would pass vacuously"

        offenders: list[str] = []
        for guide in guides:
            directory = Path(guide).parent
            if directory.name in GENERATOR_EXEMPT_DIRS:
                continue
            # `guide` is a git-relative POSIX path, so the expected generator
            # path is built in the same form instead of via Path arithmetic
            # against the absolute repo root (which would raise ValueError).
            generator = f"{directory.as_posix()}/generate_guide.py"
            if generator not in tracked:
                offenders.append(
                    f"{directory.name}: {Path(guide).name} has no generator"
                )

        assert not offenders, (
            "user guides without a committed generate_guide.py "
            "(add the generator, or add the directory to "
            "GENERATOR_EXEMPT_DIRS with a documented reason):\n  "
            + "\n  ".join(offenders)
        )

    def test_generators_are_syntactically_valid(self) -> None:
        """Each generator byte-compiles, so a guide can actually be rebuilt."""
        generators = sorted(GUIDE_ROOT.glob("*/generate_guide.py"))
        assert generators, "no generators found - locks would pass vacuously"
        for generator in generators:
            compile(
                generator.read_text(encoding="utf-8"),
                str(generator),
                "exec",
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
