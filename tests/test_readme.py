"""Tests for the README tool index and its cross-surface registration.

Changed in 1.3.0: the metadata lock now expects 28 tool rows (Spectral Viewer).

Plan iteration 5, item E1 (audit #10): the README's tool index must be
generated from the tool manifest instead of hand-maintained rows that drift
from ``audio_suite_shared/tool_plugin.py``. These locks convert that into an
enforced invariant:

1. *Drift lock* — the README table block is byte-identical to a fresh render
   from the manifest (``utilities/generate_readme_tool_index.py``), so a tool
   added without a README row, launcher, card, CLI command or guide fails
   here at the earliest point.
2. *Registration lock* — for every manifest id the launcher ``.pyw`` file
   exists, the Master Driver card module exists (following the documented
   ``{tool_id}_card`` name plus the ``_CARD_MODULE_OVERRIDES`` registry used
   by ``utilities_window.py``), a registered CLI subcommand resolves, and the
   guide document is registered in ``guide_to_program`` and exists on disk.
3. *Metadata lock* — ``pyproject.toml`` ships the README (``readme`` field)
   and the README states the A5 ffmpeg/ffprobe requirement the launch
   preflight enforces, with the same install commands.
4. *Standards lock* — plan iteration 7 item A4: the README records the
   engineering standard (audit A8's "record it") where new contributors read
   first. The gate commands are read from ``CONTRIBUTING.md``, the normative
   source, so the README summary cannot drift from the enforced gate.
"""

from __future__ import annotations

import importlib
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import ModuleType

import pytest
import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"

_BEGIN = "<!-- TOOL INDEX: BEGIN"
_END = "<!-- TOOL INDEX: END"
_END_SUFFIX = " -->"

# The embedded REFINE tab replaces a card for the single refinery tool, the
# same way utilities_window's converter/undo entries are handled specially.
_EMBEDDED_TAB_TOOLS = frozenset({"audio_refinery"})


@pytest.fixture(scope="module")
def tool_index_module() -> ModuleType:
    """Import the generator by file path (``utilities`` is not a package)."""
    spec = spec_from_file_location(
        "generate_readme_tool_index",
        REPO_ROOT / "utilities" / "generate_readme_tool_index.py",
    )
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def readme_text() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide_registry(tool_index_module: ModuleType) -> dict[str, str]:
    extracted: dict[str, str] = tool_index_module.extract_guide_registry()
    return extracted


@pytest.fixture(scope="module")
def card_overrides() -> dict[str, str]:
    utilities_window = importlib.import_module("master_driver.ui.utilities_window")
    return dict(utilities_window._CARD_MODULE_OVERRIDES)


class TestIndexGeneration:
    """The README table is generated, current, and complete."""

    def test_readme_block_matches_a_fresh_render_from_the_manifest(
        self,
        readme_text: str,
        tool_index_module: ModuleType,
    ) -> None:
        begin = readme_text.find(_BEGIN)
        end = readme_text.rfind(_END)
        assert begin != -1 and end != -1, "TOOL INDEX markers are missing"
        end_of_marker = end + len(_END) + len(_END_SUFFIX)
        current = readme_text[begin:end_of_marker].replace("\r\n", "\n")
        fresh = tool_index_module.render_tool_index()
        assert current == fresh, (
            "README tool index drifted from the manifest — re-run "
            "utilities/generate_readme_tool_index.py after editing "
            "audio_suite_shared/tool_plugin.py"
        )

    def test_every_manifest_id_has_a_row(self, tool_index_module: ModuleType) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        block = tool_index_module.render_tool_index().replace("\r\n", "\n")
        assert block, "the generator produced an empty index"
        for manifest in get_registry().all:
            assert f"| {manifest.name} | {manifest.description} |" in block, (
                f"tool {manifest.id!r} ({manifest.name}) has no README row"
            )


class TestMetadataLock:
    """The distribution metadata ships the README and its index is whole."""

    def test_pyproject_ships_the_readme_and_28_tool_rows(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
            pyproject = tomllib.load(fh)
        project = pyproject["project"]
        assert isinstance(project, dict)
        declared_readme = project.get("readme")
        assert declared_readme == "README.md", "pyproject.toml must ship the README"
        assert declared_readme == README.name
        assert len(get_registry().all) == 28


class TestRegistrationLock:
    """Manifest ↔ launcher ↔ card ↔ CLI ↔ guide all agree, per tool."""

    @staticmethod
    def _assert_surface(manifest, card_overrides: dict[str, str]) -> None:
        launcher = REPO_ROOT / manifest.pyw_filename
        assert launcher.exists(), f"{manifest.id}: launcher {launcher} missing"

        if manifest.id in _EMBEDDED_TAB_TOOLS:
            embedded = REPO_ROOT / "master_driver" / "ui" / "refinery_tab.py"
            assert embedded.exists(), (
                f"{manifest.id}: its Master Driver UI is an embedded tab "
                "(not a card), which must exist"
            )
        else:
            card_name = card_overrides.get(manifest.id, f"{manifest.id}_card")
            card = REPO_ROOT / "master_driver" / "ui" / "cards" / f"{card_name}.py"
            assert card.exists(), (
                f"{manifest.id}: Master Driver card {card} missing "
                "(see AGENTS.md 'Master Driver Card Naming')"
            )

        if manifest.cli_command is not None:
            cliapp = importlib.import_module("audio_suite_shared.cli_app")
            assert manifest.cli_command in cliapp.cli.commands, (
                f"{manifest.id}: CLI subcommand {manifest.cli_command!r} not "
                "registered in audio_suite_shared.cli_app"
            )

    def test_all_tools_are_registered_on_every_surface(
        self, card_overrides: dict[str, str]
    ) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        for manifest in get_registry().all:
            self._assert_surface(manifest, card_overrides)


class TestGuideRegistry:
    """Every tool's guide is the registered one and exists on disk."""

    def test_every_tool_guide_is_registered_and_present(
        self, tool_index_module: ModuleType, guide_registry: dict[str, str]
    ) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        for manifest in get_registry().all:
            guide_name = tool_index_module.guide_filename_for(
                manifest.id, manifest.pyw_filename
            )
            folder = guide_registry.get(guide_name)
            assert folder, (
                f"{manifest.id}: guide {guide_name!r} is not registered in "
                "guide_to_program (platform_utils.py)"
            )
            path = (
                REPO_ROOT / "user_guides" / "individual_programs" / folder / guide_name
            )
            assert path.exists(), f"{manifest.id}: guide artifact {path} missing"


class TestFfmpegWording:
    """The README states the same requirement the A5 launch preflight does."""

    @staticmethod
    def _requirement_over_readme(readme_text: str, purpose: str) -> str:
        import audio_suite_shared.system_requirements as sr

        required = [r for r in sr.REQUIRED_EXECUTABLES if r.purpose == purpose]
        assert len(required) == 1
        requirement = required[0]
        assert purpose in readme_text, (
            f"{requirement.name}: the README omits the A5 purpose sentence"
        )
        for hint in requirement.install_hints:
            assert hint in readme_text, (
                f"{requirement.name}: the README install commands must "
                f"match system_requirements.py verbatim (missing {hint!r})"
            )
        return requirement.name

    def test_readme_states_the_a5_ffmpeg_requirement(self, readme_text: str) -> None:
        import audio_suite_shared.system_requirements as sr

        ffmpeg = self._requirement_over_readme(readme_text, sr.FFMPEG_PURPOSE)
        ffprobe = self._requirement_over_readme(readme_text, sr.FFPROBE_PURPOSE)
        assert {ffmpeg, ffprobe} == {"ffmpeg", "ffprobe"}


class TestEngineeringStandards:
    """The README records the engineering standard where contributors read first.

    Plan iteration 7, item A4 (audit A8's "record it"). The gate commands are
    read out of ``CONTRIBUTING.md`` — the normative source — rather than
    hardcoded here, so this summary cannot drift from the gate that is actually
    enforced, and a seventh command added there fails here until the README
    catches up.
    """

    _HEADING = "## Engineering standards"
    _CONTRIBUTING = "CONTRIBUTING.md"

    @pytest.fixture(scope="class")
    @staticmethod
    def standards_section(readme_text: str) -> str:
        start = readme_text.find("## Engineering standards")
        assert start != -1, (
            "README.md is missing the '## Engineering standards' section (item A4)"
        )
        remainder = readme_text[start + len("## Engineering standards") :]
        end = remainder.find("\n## ")
        section = remainder[:end] if end != -1 else remainder
        assert len(section.split()) > 40, (
            "the standards section is too thin to be useful; item A4 asks for "
            "the gate, the typing standard, the audio rule and the pointers"
        )
        return section

    @pytest.fixture(scope="class")
    @staticmethod
    def gate_commands() -> list[str]:
        """The six gate command lines, as written in CONTRIBUTING.md."""
        contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
        gate_start = contributing.find("## The mandatory Phase Gate")
        assert gate_start != -1, "CONTRIBUTING.md lost its Phase Gate heading"
        block_start = contributing.find("```pwsh", gate_start)
        assert block_start != -1, "CONTRIBUTING.md's Phase Gate has no pwsh block"
        block = contributing[block_start : contributing.find("```", block_start + 7)]
        commands = [
            line.strip()
            for line in block.splitlines()
            if line.strip().startswith(("python -m ", "$env:"))
        ]
        # Non-vacuity, as a floor rather than an equality: this guards a
        # mis-parse that finds nothing, and deliberately does NOT pin the
        # count to six. Pinning it would make adding a seventh gate command
        # fail here with a bare "parsed 7" instead of reaching the
        # per-command assertion, whose message names the command the README
        # is missing — the diagnostic a maintainer actually needs.
        assert len(commands) >= 6, (
            f"expected at least the six gate commands, parsed {len(commands)}: "
            f"{commands} — the gate block or this parser has drifted"
        )
        return commands

    def test_section_names_every_gate_command(
        self, standards_section: str, gate_commands: list[str]
    ) -> None:
        for command in gate_commands:
            assert command in standards_section, (
                f"the README standards section omits the gate command {command!r}; "
                f"keep it in sync with {self._CONTRIBUTING}"
            )

    def test_section_states_the_typing_standard(self, standards_section: str) -> None:
        assert "--strict" in standards_section, "the mypy --strict mode is unstated"
        assert "annotat" in standards_section.lower(), (
            "the annotation standard is unstated"
        )

    def test_section_states_the_audio_correctness_rule(
        self, standards_section: str
    ) -> None:
        lowered = standards_section.lower()
        assert "audio correctness" in lowered, "the audio rule is unstated"
        # Stems, not one inflected form: the rule may be phrased "decode",
        # "decoding" or "decoded" and all three satisfy it.
        assert "decod" in lowered, (
            "the audio rule must require decoding the result and measuring it"
        )
        assert "measur" in lowered, "the audio rule omits measuring the result"
        assert "reading back" in lowered, (
            "the audio rule must reject validating a fix by reading back the "
            "state the code just wrote — that proves self-consistency, not "
            "correctness"
        )

    def test_section_points_at_the_normative_sources(
        self, standards_section: str
    ) -> None:
        for source in ("AGENTS.md", self._CONTRIBUTING):
            assert source in standards_section, f"the README omits {source}"
        assert "normative" in standards_section.lower(), (
            "AGENTS.md and CONTRIBUTING.md must be marked normative so they win "
            "on any conflict with this summary"
        )

    def test_standards_section_precedes_contributing(self, readme_text: str) -> None:
        standards = readme_text.find(self._HEADING)
        contributing = readme_text.find("\n## Contributing")
        assert standards != -1 and contributing != -1
        assert standards < contributing, (
            "item A4 places the standards section after the architecture "
            "overview, before Contributing"
        )
