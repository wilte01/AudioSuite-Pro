"""
Tests for audio_suite_shared.system_requirements.

Covers:
    - SystemRequirement.render: names the binary, its purpose, and each hint
    - find_missing_requirements: present/absent/partial probes, the injected
      resolver, and declaration-order preservation
    - format_requirement_report: names every missing binary and every install
      hint, in plain text (no rotting links)
    - TestGuideWordingLock: every ffmpeg-dependent tool's generated user guide
      states the requirement with the exact canonical wording, so the dialog a
      user sees and the guide they read cannot drift apart (plan A5; AGENTS.md
      §8 "generator is the source of truth").
"""

from __future__ import annotations

from pathlib import Path

from audio_suite_shared.system_requirements import (
    FFMPEG_PURPOSE,
    FFPROBE_PURPOSE,
    REQUIRED_EXECUTABLES,
    SystemRequirement,
    find_missing_requirements,
    format_requirement_report,
)

#: The tools whose production code shells out to ffmpeg/ffprobe (direct
#: invocation or via the shared pydub-based conversion helpers).  Derived by
#: grepping first-party non-test code for ffmpeg/ffprobe/pydub/AudioSegment;
#: update this table in lockstep when a tool gains or loses the dependency —
#: the wording lock below then enforces its guide states the requirement.
FFMPEG_DEPENDENT_TOOLS: tuple[tuple[str, str], ...] = (
    ("audio_enhancer", "Audio_Enhancer_User_Guide.docx"),
    ("audio_normalizer", "Audio_Normalizer_User_Guide.docx"),
    ("audio_refinery", "Audio_Refinery_User_Guide.docx"),
    ("cd_ripper", "CD_Ripper_User_Guide.docx"),
    ("music_format_converter", "Music_Format_Converter_User_Guide.docx"),
    ("noise_reduction", "Noise_Reduction_User_Guide.docx"),
    ("pop_click_remover", "Pop_Click_Remover_User_Guide.docx"),
    ("replaygain_analyzer", "ReplayGain_Analyzer_User_Guide.docx"),
    ("silence_trimmer", "Silence_Trimmer_User_Guide.docx"),
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


class TestSystemRequirementRender:
    def test_render_names_binary_purpose_and_hints(self):
        requirement = SystemRequirement(
            name="ffmpeg",
            purpose="decodes audio",
            install_hints=("Windows: winget install Gyan.FFmpeg",),
        )
        lines = requirement.render()
        assert lines[0] == "- ffmpeg (decodes audio)"
        assert lines[1] == "    install: Windows: winget install Gyan.FFmpeg"

    def test_declared_requirements_are_frozen_and_hints_are_plain_text(self):
        for requirement in REQUIRED_EXECUTABLES:
            assert hash(requirement), "requirements must be usable in sets"
            for hint in requirement.install_hints:
                assert "http" not in hint, (
                    f"{requirement.name}: hints must be plain install commands, "
                    "not URLs that rot silently in a dialog"
                )


class TestFindMissingRequirements:
    def test_present_binary_is_not_reported(self):
        assert find_missing_requirements(resolver=lambda _name: "/usr/bin/ffmpeg") == []

    def test_absent_binary_is_reported(self):
        missing = find_missing_requirements(resolver=lambda _name: None)
        assert [r.name for r in missing] == ["ffmpeg", "ffprobe"]

    def test_missing_ffprobe_with_ffmpeg_present_is_reported_separately(self):
        """The suite's subprocess allowlist treats ffmpeg/ffprobe as a pair, so
        a host with one but not the other must be distinguishable in the report."""
        on_path = {"ffmpeg": "/opt/ffmpeg/bin/ffmpeg.exe"}

        def resolver(name: str) -> str | None:
            return on_path.get(name)

        missing = find_missing_requirements(resolver=resolver)
        assert [r.name for r in missing] == ["ffprobe"]

    def test_result_preserves_declaration_order(self):
        missing = find_missing_requirements(resolver=lambda _name: None)
        assert [r.name for r in missing] == [r.name for r in REQUIRED_EXECUTABLES]

    def test_default_resolver_is_path_lookup(self, monkeypatch):
        """The default resolver must be shutil.which — the plan's A5 says to
        reuse an existing discovery mechanism, not re-implement one."""
        import audio_suite_shared.system_requirements as module

        seen: list[str] = []

        def recording_which(name: str) -> str | None:
            seen.append(name)
            return None

        monkeypatch.setattr(module.shutil, "which", recording_which)
        find_missing_requirements()
        assert seen == ["ffmpeg", "ffprobe"]


class TestFormatRequirementReport:
    def test_names_each_missing_binary_and_its_purpose(self):
        report = format_requirement_report(
            [r for r in REQUIRED_EXECUTABLES if r.name == "ffmpeg"]
        )
        assert "could not find 1 required system tool(s)" in report
        assert "ffmpeg" in report
        assert FFMPEG_PURPOSE in report
        assert "ffprobe" not in report

    def test_contains_every_install_hint(self):
        report = format_requirement_report(list(REQUIRED_EXECUTABLES))
        for requirement in REQUIRED_EXECUTABLES:
            for hint in requirement.install_hints:
                assert hint in report

    def test_states_launch_still_proceeds(self):
        report = format_requirement_report(list(REQUIRED_EXECUTABLES))
        assert "still starts" in report, (
            "the report must say the warning is non-blocking, or a user cannot "
            "tell it apart from the compile gate's block"
        )


class TestGuideWordingLock:
    """The generated user guides must quote the canonical requirement wording.

    AGENTS.md §8: the generator is the source of truth for generated docs, so
    this locks the *artifact* — a guide regenerated without the section, or
    with reworded hints, fails here.
    """

    @staticmethod
    def _guide_text(tool: str, filename: str) -> str:
        import docx

        path = _REPO_ROOT / "user_guides" / "individual_programs" / tool / filename
        document = docx.Document(str(path))
        return "\n".join(p.text for p in document.paragraphs)

    def test_every_ffmpeg_dependent_guide_states_the_requirement(self):
        for tool, filename in FFMPEG_DEPENDENT_TOOLS:
            text = self._guide_text(tool, filename)
            assert "System Requirements" in text, f"{tool}: section heading missing"
            assert FFMPEG_PURPOSE in text, f"{tool}: ffmpeg purpose wording drifted"
            assert FFPROBE_PURPOSE in text, f"{tool}: ffprobe purpose wording drifted"
            for hint in REQUIRED_EXECUTABLES[0].install_hints:
                assert hint in text, f"{tool}: install hint {hint!r} missing"

    def test_guide_lock_genuinely_discriminates(self):
        """Negative control against real data: a guide that legitimately has
        no such section (the key detector never shells out to ffmpeg) must
        fail the same assertions, proving the lock above cannot pass vacuously
        and that the section appears only where the dependency is real."""
        text = self._guide_text("key_detector", "Key_Detector_User_Guide.docx")
        assert "System Requirements" not in text
        assert FFPROBE_PURPOSE not in text
