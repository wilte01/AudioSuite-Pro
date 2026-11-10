"""
Tests for audio_suite_shared.tool_plugin (G-NEW — Plugin System).

Verifies ToolManifest, ToolRegistry construction, and the first-party
manifest definitions.

Changed in 1.3.0: the expected sets add the ``spectral_viewer`` manifest
(Sprint 3, D42).
Changed in 2.0.0: the expected sets add the ``stem_separator`` manifest and
its ``stems`` command (Sprint 6, Item 6.1).

Changed in 2.1.0: the registry now holds plugin manifests beside the first-party ones.

Changed in 2.3.0: the expected sets add the ``duplicate_finder`` and
``restoration`` manifests (F-02, F-08a in ``PLAN_functional_backlog.md``).

Changed in 2.6.0 (U-04): the five DSP tools REFINE runs as pipeline stages
stopped shipping a launcher, CLI command and guide, so they leave the
registry entirely (32 manifests -> 27).  The lock below asserts their
absence from every surface and that the pipeline still runs their cores
(``PLAN_restoration_2026-10-31.md``).

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).
Changed in 2.5.0: the frozen counts and command set gain the Track Splitter (F-E4)
and then the Channel Tools utility (F-E6).

Changed in 2.6.0: the tabs' grouping is locked here - every first-party tool
names a group declared for its category, every declared group has cards, the
``order`` values are contiguous blocks of ten, and the Utilities names are
alphabetical inside a block.  ENRICH keeps its dependency-vetted order inside a
group instead, which the lock asserts by forbidding a reorder
(PLAN_2026-11-08_util_card_grouping.md, PLAN_2026-11-08_enrich_card_grouping.md).
"""

from pathlib import Path

import pytest

from audio_suite_shared.exceptions import AudioConfigurationError
from audio_suite_shared.tool_plugin import (
    ENRICH_GROUPS,
    OTHER_GROUP_TITLE,
    PLUGINS_GROUP_TITLE,
    UTILITY_GROUPS,
    ToolManifest,
    ToolRegistry,
    enrich_sections,
    get_registry,
    utility_sections,
)


class TestToolManifest:
    def test_minimal_construction(self):
        m = ToolManifest(
            id="test", name="Test", category="enrich", pyw_filename="test.pyw"
        )
        assert m.id == "test"
        assert m.name == "Test"
        assert m.category == "enrich"
        assert m.pyw_filename == "test.pyw"

    def test_frozen(self):
        m = ToolManifest(id="a", name="A", category="b", pyw_filename="c")
        import dataclasses

        assert dataclasses.is_dataclass(m)
        assert m.id == "a"


class TestToolRegistry:
    def test_empty_registry(self):
        r = ToolRegistry()
        assert len(r) == 0
        assert r.all == []
        assert r.by_category("enrich") == []
        assert r.get("nonexistent") is None

    def test_register_and_get(self):
        r = ToolRegistry()
        m = ToolManifest(
            id="foo", name="Foo", category="enrich", pyw_filename="foo.pyw"
        )
        r.register(m)
        assert r.get("foo") is m
        assert "foo" in r

    def test_register_duplicate_raises(self):
        r = ToolRegistry()
        r.register(ToolManifest(id="dup", name="A", category="e", pyw_filename="a.pyw"))
        import pytest

        with pytest.raises(AudioConfigurationError, match="dup"):
            r.register(
                ToolManifest(id="dup", name="B", category="u", pyw_filename="b.pyw")
            )

    def test_by_category_filters(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="b", name="B", category="utility", pyw_filename="b.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="c", name="C", category="enrich", pyw_filename="c.pyw", order=20
            )
        )

        enrich = r.by_category("enrich")
        assert len(enrich) == 2
        assert all(m.category == "enrich" for m in enrich)

        utility = r.by_category("utility")
        assert len(utility) == 1
        assert utility[0].id == "b"

    def test_by_category_sorted_by_order(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="z", name="Z", category="enrich", pyw_filename="z.pyw", order=50
            )
        )
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="m", name="M", category="enrich", pyw_filename="m.pyw", order=30
            )
        )

        ids = [m.id for m in r.by_category("enrich")]
        assert ids == ["a", "m", "z"]

    def test_all_sorted(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="b", name="B", category="utility", pyw_filename="b.pyw", order=20
            )
        )
        r.register(
            ToolManifest(
                id="a", name="A", category="enrich", pyw_filename="a.pyw", order=10
            )
        )
        r.register(
            ToolManifest(
                id="c", name="C", category="refinery", pyw_filename="c.pyw", order=30
            )
        )

        all_m = r.all
        assert len(all_m) == 3
        # Sorted by (category, order)
        assert all_m[0].id == "a"  # enrich, 10
        assert all_m[1].id == "c"  # refinery, 30
        assert all_m[2].id == "b"  # utility, 20

    def test_by_cli(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(
                id="a", name="A", category="e", pyw_filename="a.pyw", cli_command="alfa"
            )
        )
        r.register(ToolManifest(id="b", name="B", category="e", pyw_filename="b.pyw"))
        r.register(
            ToolManifest(
                id="c",
                name="C",
                category="e",
                pyw_filename="c.pyw",
                cli_command="charlie",
            )
        )

        cli_cmds = r.by_cli()
        assert len(cli_cmds) == 2
        assert [m.cli_command for m in cli_cmds] == ["alfa", "charlie"]


class TestDefaultRegistry:
    def test_get_registry_is_singleton(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_registry_is_populated(self):
        r = get_registry()
        assert len(r) >= 16  # all first-party tools
        assert len(r.first_party) == 32  # 11 enrich + 20 utility + 1 refinery
        # A plugin adds a registry entry, never a first-party one.
        assert len(r) == len(r.first_party) + len(r.plugins)
        assert r.plugins, "the shipped example plugin did not register"

    def test_plugin_and_first_party_populations_are_disjoint(self):
        r = get_registry()
        first_party = {m.id for m in r.first_party}
        plugins = {m.id for m in r.plugins}

        assert first_party & plugins == set()
        assert all(m.plugin for m in r.plugins)
        assert all(not m.plugin for m in r.first_party)

    def test_plugins_sort_after_first_party_tools(self):
        """A plugin must not displace a shipped tool's documented position."""
        r = get_registry()
        plugin_flags = [manifest.plugin for manifest in r.by_category("utility")]

        assert any(plugin_flags), "no plugin in the utility category; test vacuous"
        first_plugin = plugin_flags.index(True)
        assert all(plugin_flags[first_plugin:])

    def test_has_all_enrich_tools(self):
        r = get_registry()
        ids = {m.id for m in r.first_party if m.category == "enrich"}
        expected = {
            "scrubber",
            "replaygain",
            "fingerprinter",
            "album_genre",
            "genre_sync",
            "bpm",
            "tempo",
            "key",
            "mood_analyzer",
            "art",
            "lyrics_manager",
        }
        assert ids == expected

    def test_has_all_utility_tools(self):
        r = get_registry()
        ids = {m.id for m in r.first_party if m.category == "utility"}
        expected = {
            "converter",
            "asx_extractor",
            "cue_sheet",
            "album_art_normalizer",
            "artwork",
            "cd_ripper",
            "mood_analysis_batch",
            "library_stats",
            "track_splitter",
            "audio_joiner",
            "file_reorganizer",
            "tag_field_updater",
            "tag_editor",
            "undo_tag_edits",
            "spectral_viewer",
            "stem_separator",
            "ml_denoiser",
            "duplicate_finder",
            "restoration",
            "channel_tools",
        }
        assert ids == expected

    def test_has_refinery(self):
        r = get_registry()
        ids = {m.id for m in r.first_party if m.category == "refinery"}
        assert "audio_refinery" in ids

    def test_cli_commands_match_expected(self):
        r = get_registry()
        commands = {m.cli_command for m in r.first_party if m.cli_command}
        expected = {
            "scrub",
            "fingerprint",
            "replaygain",
            "genre-sync",
            "bpm",
            "tempo",
            "key",
            "mood-analyzer",
            "join",
            "convert",
            "stats",
            "split",
            "reorganize",
            "album-genre",
            "album-art",
            "asx-extract",
            "artnormalize",
            "cd-rip",
            "mood-analysis-batch",
            "tag-update",
            "tag-edit",
            "lyrics",
            "spectrogram",
            "denoise",
            "stems",
            "duplicates",
            "declip",
            "channels",
            # Plan G2: the CLI subcommand is `refine`, and the manifest now
            # says so instead of leaving audio_refinery CLI-less by omission.
            "refine",
        }
        assert commands == expected

    def test_standalone_tools(self):
        r = get_registry()
        standalone = {m.id for m in r.first_party if m.standalone}
        expected = {
            "cd_ripper",
            "mood_analysis_batch",
            "library_stats",
            "track_splitter",
            "audio_joiner",
            "fingerprinter",
            "audio_refinery",
            "file_reorganizer",
            "tag_field_updater",
            "tag_editor",
            "undo_tag_edits",
            "spectral_viewer",
            "stem_separator",
            "ml_denoiser",
            "duplicate_finder",
            "restoration",
            "channel_tools",
        }
        assert standalone == expected

    def test_undo_tool_closes_its_group(self):
        """Undo sits last in Tags & Artwork: tag work finishes with its undo.

        It used to sit last in the whole category, which is only true while
        every other utility outranks it.  The grouping gives it a position that
        means something instead (PLAN_2026-11-08_util_card_grouping.md).
        """
        r = get_registry()
        tags_group = [
            m.id
            for m in r.driver_by_category("utility")
            if not m.plugin and m.group == "tags"
        ]

        assert tags_group[-1] == "undo_tag_edits"

    def test_registry_is_frozen(self):
        r = get_registry()
        import pytest

        m = ToolManifest(id="late", name="Late", category="e", pyw_filename="late.pyw")
        with pytest.raises(AudioConfigurationError):
            r.register(m)

    def test_all_returns_a_copy_not_a_live_view(self):
        """Mutating a returned list must not touch the shared registry."""
        r = get_registry()
        before = len(r.all)
        r.all.clear()
        assert len(r.all) == before
        assert len(r) == before

    def test_by_category_returns_a_copy_not_a_live_view(self):
        r = get_registry()
        before = len(r.by_category("utility"))
        r.by_category("utility").clear()
        assert len(r.by_category("utility")) == before

    def test_all_manifests_are_frozen_dataclasses(self):
        """The registry's manifest data itself must resist in-place edits."""
        import dataclasses

        import pytest

        for m in get_registry().all:
            assert dataclasses.is_dataclass(m)
            with pytest.raises(dataclasses.FrozenInstanceError):
                m.name = "tampered"  # type: ignore[misc]


#: The five DSP tools REFINE runs as pipeline stages, and the stage each one
#: became.  They are not tools any more: no manifest, launcher, CLI command,
#: window or guide - only the library REFINE imports (U-04).
REMOVED_TOOLS: dict[str, str] = {
    "pop_click_remover": "declick",
    "silence_trimmer": "trim",
    "noise_reduction": "reduce_noise",
    "audio_enhancer": "enhance",
    "audio_normalizer": "normalise",
}


class TestRemovedStandaloneTools:
    """U-04: five tools leave every surface, and REFINE keeps their work.

    The first test is the removal; the rest prove it was a removal and not a
    half-one, and that the capability did not go with it.
    """

    def test_the_five_are_not_registered(self):
        r = get_registry()
        ids = {m.id for m in r.all}

        assert ids.isdisjoint(REMOVED_TOOLS), sorted(ids & set(REMOVED_TOOLS))
        for tool_id in REMOVED_TOOLS:
            assert r.get(tool_id) is None, tool_id

    def test_the_utilities_tab_loses_them_with_the_registry(self):
        """19 first-party utilities, and the tab offers every one."""
        r = get_registry()
        utilities = [m.id for m in r.by_category("utility") if not m.plugin]
        cards = [m.id for m in r.driver_by_category("utility") if not m.plugin]

        assert len(utilities) == 20, utilities
        assert sorted(cards) == sorted(utilities)

    def test_no_launcher_and_no_command_survive(self):
        from audio_suite_shared.cli_app import cli

        root = Path(__file__).resolve().parents[2]
        commands = set(cli.commands)

        for tool_id, _stage in REMOVED_TOOLS.items():
            lowered = tool_id.replace("_", "-")
            launchers = [
                path
                for path in root.glob("*.pyw")
                if lowered.replace("-", "_") in path.stem.lower().replace("-", "_")
            ]
            assert launchers == [], f"{tool_id}: launcher(s) {launchers} still ship"
            assert lowered not in commands, tool_id

    def test_no_card_and_no_package_app_survive(self):
        """A deleted card or window leaves no module a lazy import could find."""
        import importlib

        for tool_id in REMOVED_TOOLS:
            for module in (
                f"master_driver.ui.cards.{tool_id}_card",
                f"{tool_id}.app",
                f"{tool_id}.cli",
            ):
                with pytest.raises(ModuleNotFoundError):
                    importlib.import_module(module)

    def test_each_package_still_exposes_only_its_library(self):
        """The package is REFINE's library now, not an application."""
        import importlib

        for tool_id in REMOVED_TOOLS:
            package = importlib.import_module(tool_id)
            assert package.__all__ == [], tool_id
            assert not hasattr(package, "NoiseReductionApp"), tool_id

    def test_refine_runs_every_core_the_tools_shipped(self):
        """The capability moved into the pipeline; it did not disappear."""
        from audio_refinery.core import pipeline
        from audio_refinery.core.models import StageConfig

        source = Path(pipeline.__file__).read_text(encoding="utf-8")
        for module in (
            "pop_click_remover.core.declicker",
            "silence_trimmer.core.trimmer",
            "noise_reduction.core.noise_reducer",
            "audio_enhancer.core.models",
            "audio_normalizer.core.normalizer",
        ):
            assert module in source, f"REFINE no longer imports {module}"

        config = StageConfig()
        assert config.declick is True
        assert config.trim is True
        assert config.enhance is True
        assert config.normalise is True
        assert config.reduce_noise in (True, False)


class TestPluginRegistration:
    """A plugin manifest joins the registry without being able to break it."""

    def _plugin_manifest(self, tool_id: str) -> ToolManifest:
        return ToolManifest(
            id=tool_id,
            name="Plugin Tool",
            category="utility",
            pyw_filename="plugins/demo/Demo.pyw",
            plugin=True,
            origin="/plugins/demo",
        )

    def test_register_plugin_adds_the_manifest(self):
        r = ToolRegistry()

        assert r.register_plugin(self._plugin_manifest("demo_tool")) is True
        assert r.get("demo_tool") is not None
        assert [m.id for m in r.plugins] == ["demo_tool"]
        assert r.plugin_problems == []

    def test_a_duplicate_plugin_is_recorded_not_raised(self):
        r = ToolRegistry()
        r.register_plugin(self._plugin_manifest("demo_tool"))

        assert r.register_plugin(self._plugin_manifest("demo_tool")) is False
        assert r.plugin_problems and "demo_tool" in r.plugin_problems[0]

    def test_a_plugin_colliding_with_a_first_party_id_is_recorded(self):
        r = ToolRegistry()
        r.register(
            ToolManifest(id="bpm", name="BPM", category="enrich", pyw_filename="b.pyw")
        )

        assert r.register_plugin(self._plugin_manifest("bpm")) is False
        assert r.get("bpm") is not None  # type: ignore[union-attr]
        assert r.get("bpm").name == "BPM"  # type: ignore[union-attr]

    def test_register_plugin_refuses_a_first_party_manifest(self):
        r = ToolRegistry()

        with pytest.raises(AudioConfigurationError):
            r.register_plugin(
                ToolManifest(id="x", name="X", category="utility", pyw_filename="x.pyw")
            )

    def test_a_cli_only_plugin_is_not_a_driver_tool(self):
        r = ToolRegistry()
        r.register_plugin(
            ToolManifest(
                id="cli_only",
                name="CLI Only",
                category="utility",
                pyw_filename="",
                plugin=True,
                entry_point="demo.tool:main",
                cli_command="demo",
            )
        )

        assert r.get("cli_only").is_driver_tool is False  # type: ignore[union-attr]
        assert [m.id for m in r.driver_manifests] == []
        assert [m.id for m in r.driver_by_category("utility")] == []


class TestUtilityGrouping:
    """The Utilities tab's groups, and the ordering rule behind them.

    The tab renders this order and a sequential batch runs its steps in it, so
    the grouping is manifest data with two requirements per tool: name a
    declared group, and take the next order in that group's block of ten with
    the name alphabetical among its siblings.  A new tool that skips either
    fails here instead of landing at the bottom of the tab.
    """

    @staticmethod
    def _utilities() -> list[ToolManifest]:
        return [
            manifest
            for manifest in get_registry().driver_by_category("utility")
            if not manifest.plugin
        ]

    def test_every_first_party_utility_names_a_declared_group(self):
        keys = {key for key, _title in UTILITY_GROUPS}

        for manifest in self._utilities():
            assert manifest.group in keys, manifest.id

    def test_every_declared_group_has_cards(self):
        used = {manifest.group for manifest in self._utilities()}

        assert [key for key, _title in UTILITY_GROUPS if key not in used] == []

    def test_orders_are_contiguous_blocks_of_ten(self):
        """No ties and no gaps: a tie is what made the old order feel random."""
        utilities = self._utilities()

        assert [manifest.order for manifest in utilities] == [
            10 * (index + 1) for index in range(len(utilities))
        ]

    def test_a_group_occupies_one_contiguous_block(self):
        seen: list[str] = []
        for manifest in self._utilities():
            if not seen or seen[-1] != manifest.group:
                assert manifest.group not in seen, manifest.group
                seen.append(manifest.group)

        assert seen == [key for key, _title in UTILITY_GROUPS]

    def test_names_are_alphabetical_inside_each_group(self):
        for key, title in UTILITY_GROUPS:
            names = [
                manifest.name.casefold()
                for manifest in self._utilities()
                if manifest.group == key
            ]

            assert names == sorted(names), title


class TestEnrichGrouping:
    """The Enrich tab's groups, and the run order they must not disturb.

    The groups are contiguous runs of the enrich order, so renumbering them
    changes no run.  That is deliberate: Tempo Analyzer reads the BPM tag BPM
    Analyzer writes, and the shipped deck explains every other position, so an
    alphabetical re-sort here would silently reorder a batch.
    """

    #: The enrich order is dependency-vetted and frozen: grouping must not move
    #: a tool past another one.
    RUN_ORDER: tuple[str, ...] = (
        "scrubber",
        "fingerprinter",
        "replaygain",
        "album_genre",
        "genre_sync",
        "bpm",
        "tempo",
        "key",
        "mood_analyzer",
        "art",
        "lyrics_manager",
    )

    @staticmethod
    def _enrich() -> list[ToolManifest]:
        return [
            manifest
            for manifest in get_registry().driver_by_category("enrich")
            if not manifest.plugin
        ]

    def test_every_first_party_enrich_tool_names_a_declared_group(self):
        keys = {key for key, _title in ENRICH_GROUPS}

        for manifest in self._enrich():
            assert manifest.group in keys, manifest.id

    def test_every_declared_group_has_cards(self):
        used = {manifest.group for manifest in self._enrich()}

        assert [key for key, _title in ENRICH_GROUPS if key not in used] == []

    def test_orders_are_contiguous_blocks_of_ten(self):
        enrich = self._enrich()

        assert [manifest.order for manifest in enrich] == [
            10 * (index + 1) for index in range(len(enrich))
        ]

    def test_a_group_occupies_one_contiguous_block(self):
        seen: list[str] = []
        for manifest in self._enrich():
            if not seen or seen[-1] != manifest.group:
                assert manifest.group not in seen, manifest.group
                seen.append(manifest.group)

        assert seen == [key for key, _title in ENRICH_GROUPS]

    def test_grouping_did_not_reorder_the_run(self):
        """Renumbering is display-only: the enrich sequence is unchanged."""
        assert tuple(manifest.id for manifest in self._enrich()) == self.RUN_ORDER

    def test_a_dependency_still_runs_before_its_dependant(self):
        ids = [manifest.id for manifest in self._enrich()]

        assert ids.index("bpm") < ids.index("tempo")


class TestEnrichSections:
    """``enrich_sections`` is the one place the Enrich tab's captions come from."""

    def test_sections_cover_every_manifest_once_in_order(self):
        manifests = get_registry().driver_by_category("enrich")

        covered = [
            manifest.id
            for _heading, section in enrich_sections(manifests)
            for manifest in section
        ]

        assert covered == [manifest.id for manifest in manifests]

    def test_the_headings_are_the_declared_titles(self):
        first_party = [
            manifest
            for manifest in get_registry().driver_by_category("enrich")
            if not manifest.plugin
        ]

        headings = [heading for heading, _section in enrich_sections(first_party)]

        assert headings == [title for _key, title in ENRICH_GROUPS]

    def test_a_plugin_renders_last_in_its_own_section(self):
        first_party = ToolManifest(
            id="first_party",
            name="First Party",
            category="enrich",
            pyw_filename="First.pyw",
            group="analysis",
            order=10,
        )
        plugin = ToolManifest(
            id="plugin_tool",
            name="A Plugin",
            category="enrich",
            pyw_filename="Plugin.pyw",
            plugin=True,
            order=1,
        )

        sections = enrich_sections([plugin, first_party])

        assert [heading for heading, _section in sections] == [
            dict(ENRICH_GROUPS)["analysis"],
            PLUGINS_GROUP_TITLE,
        ]
        assert [m.id for m in sections[-1][1]] == ["plugin_tool"]

    def test_an_undeclared_group_keeps_its_card(self):
        stray = ToolManifest(
            id="stray",
            name="Stray Tool",
            category="enrich",
            pyw_filename="Stray.pyw",
            group="typo",
            order=10,
        )

        assert enrich_sections([stray]) == [(OTHER_GROUP_TITLE, [stray])]


class TestUtilitySections:
    """``utility_sections`` is the one place the tab's captions come from."""

    def test_sections_cover_every_manifest_once_in_order(self):
        manifests = get_registry().driver_by_category("utility")

        covered = [
            manifest.id
            for _heading, section in utility_sections(manifests)
            for manifest in section
        ]

        assert covered == [manifest.id for manifest in manifests]

    def test_the_headings_are_the_declared_titles_then_plugins(self):
        headings = [
            heading
            for heading, _section in utility_sections(
                get_registry().driver_by_category("utility")
            )
        ]

        assert headings[:-1] == [title for _key, title in UTILITY_GROUPS]
        assert headings[-1] == PLUGINS_GROUP_TITLE

    def test_a_plugin_always_renders_last_in_its_own_section(self):
        first_party = ToolManifest(
            id="first_party",
            name="First Party",
            category="utility",
            pyw_filename="First.pyw",
            group="repair",
            order=10,
        )
        plugin = ToolManifest(
            id="plugin_tool",
            name="A Plugin",
            category="utility",
            pyw_filename="Plugin.pyw",
            plugin=True,
            order=1,
        )

        sections = utility_sections([plugin, first_party])

        assert [heading for heading, _section in sections] == [
            dict(UTILITY_GROUPS)["repair"],
            PLUGINS_GROUP_TITLE,
        ]
        assert [m.id for m in sections[-1][1]] == ["plugin_tool"]

    def test_an_undeclared_group_keeps_its_card(self):
        """A typo'd group must cost a caption, never the card itself."""
        stray = ToolManifest(
            id="stray",
            name="Stray Tool",
            category="utility",
            pyw_filename="Stray.pyw",
            group="typo",
            order=10,
        )

        assert utility_sections([stray]) == [(OTHER_GROUP_TITLE, [stray])]
