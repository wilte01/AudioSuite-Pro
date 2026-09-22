"""
Tests for tempo_analyzer.core.tempo_schemes
Gap G-04: get_tempo_marking(), TEMPO_SCHEMES constants, DEFAULT_SCHEME
"""

import pytest

from tempo_analyzer.core.tempo_schemes import (
    DEFAULT_SCHEME,
    TEMPO_SCHEMES,
    get_tempo_marking,
)

# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_default_scheme_is_italian(self):
        assert DEFAULT_SCHEME == "Italian"

    def test_all_expected_schemes_present(self):
        expected = {
            "Italian",
            "English",
            "Descriptive",
            "Numeric",
            "Simplified",
            "Dance",
            "Running",
        }
        assert expected == set(TEMPO_SCHEMES.keys())

    def test_each_scheme_is_nonempty_list(self):
        for name, scheme in TEMPO_SCHEMES.items():
            assert isinstance(scheme, list) and len(scheme) > 0, name

    def test_each_entry_is_3_tuple(self):
        for name, scheme in TEMPO_SCHEMES.items():
            for entry in scheme:
                assert len(entry) == 3, f"{name}: entry {entry!r} is not a 3-tuple"

    def test_min_bpm_lte_max_bpm_in_every_entry(self):
        for name, scheme in TEMPO_SCHEMES.items():
            for min_b, max_b, label in scheme:
                if max_b is None:
                    continue
                assert min_b <= max_b, f"{name}: min {min_b} > max {max_b}"

    def test_ranges_cover_bpm_0_within_each_scheme(self):
        for name, scheme in TEMPO_SCHEMES.items():
            starts = [min_b for min_b, _, _ in scheme]
            assert 0 in starts, f"{name}: no range starting at 0"

    def test_exactly_one_open_ended_top_band_per_scheme(self):
        for name, scheme in TEMPO_SCHEMES.items():
            none_count = sum(1 for _, max_b, _ in scheme if max_b is None)
            assert none_count == 1, (
                f"{name}: expected exactly one open-ended band, found {none_count}"
            )

    def test_open_ended_band_is_last_in_list(self):
        for name, scheme in TEMPO_SCHEMES.items():
            assert scheme[-1][1] is None, (
                f"{name}: last entry is not the open-ended band"
            )

    def test_labels_are_nonempty_strings(self):
        for name, scheme in TEMPO_SCHEMES.items():
            for _, _, label in scheme:
                assert isinstance(label, str) and label.strip(), (
                    f"{name}: empty label found"
                )


# ── get_tempo_marking ─────────────────────────────────────────────────────────


class TestGetTempoMarkingItalian:
    """Italian scheme — comprehensive boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Italian"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Larghissimo"),
            (23, "Larghissimo"),
            (24, "Largo"),
            (40, "Largo"),
            (41, "Larghetto"),
            (66, "Larghetto"),
            (67, "Adagio"),
            (76, "Adagio"),
            (77, "Andante"),
            (98, "Andante"),
            (99, "Allegretto"),
            (110, "Allegretto"),
            (111, "Moderato"),
            (120, "Moderato"),
            (121, "Allegro"),
            (168, "Allegro"),
            (169, "Vivace"),
            (177, "Vivace"),
            (178, "Presto"),
            (200, "Presto"),
            (201, "Prestissimo"),
            (300, "Prestissimo"),
            (999, "Prestissimo"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected

    def test_typical_house_bpm(self):
        assert get_tempo_marking(128, self.markings) == "Allegro"

    def test_typical_dnb_bpm(self):
        assert get_tempo_marking(174, self.markings) == "Vivace"


class TestGetTempoMarkingEnglish:
    """English scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["English"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Very Slow"),
            (40, "Very Slow"),
            (41, "Slow"),
            (76, "Slow"),
            (77, "Moderate"),
            (108, "Moderate"),
            (109, "Fast"),
            (140, "Fast"),
            (141, "Very Fast"),
            (177, "Very Fast"),
            (178, "Extremely Fast"),
            (300, "Extremely Fast"),
            (999, "Extremely Fast"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingDescriptive:
    """Descriptive scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Descriptive"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Relaxed"),
            (60, "Relaxed"),
            (61, "Easy Pace"),
            (90, "Easy Pace"),
            (91, "Moderate Energy"),
            (120, "Moderate Energy"),
            (121, "Energetic"),
            (140, "Energetic"),
            (141, "High Energy"),
            (160, "High Energy"),
            (161, "Intense"),
            (180, "Intense"),
            (181, "Frantic"),
            (300, "Frantic"),
            (999, "Frantic"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingNumeric:
    """Numeric scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Numeric"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "0-60 BPM"),
            (60, "0-60 BPM"),
            (61, "61-80 BPM"),
            (80, "61-80 BPM"),
            (81, "81-100 BPM"),
            (100, "81-100 BPM"),
            (101, "101-120 BPM"),
            (120, "101-120 BPM"),
            (121, "121-140 BPM"),
            (140, "121-140 BPM"),
            (141, "141-160 BPM"),
            (160, "141-160 BPM"),
            (161, "161-180 BPM"),
            (180, "161-180 BPM"),
            (181, "181-200 BPM"),
            (200, "181-200 BPM"),
            (201, "200+ BPM"),
            (300, "200+ BPM"),
            (999, "200+ BPM"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingSimplified:
    """Simplified scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Simplified"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Slow"),
            (90, "Slow"),
            (91, "Medium"),
            (120, "Medium"),
            (121, "Fast"),
            (150, "Fast"),
            (151, "Very Fast"),
            (300, "Very Fast"),
        ],
    )
    def test_simplified_labels(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingDance:
    """Dance scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Dance"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Downtempo"),
            (90, "Downtempo"),
            (91, "Hip Hop"),
            (110, "Hip Hop"),
            (111, "House"),
            (130, "House"),
            (131, "Techno"),
            (145, "Techno"),
            (146, "Drum and Bass"),
            (170, "Drum and Bass"),
            (171, "Hardcore"),
            (300, "Hardcore"),
            (999, "Hardcore"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingRunning:
    """Running scheme — all boundary values."""

    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Running"]

    @pytest.mark.parametrize(
        "bpm,expected",
        [
            (1, "Walking Pace"),
            (120, "Walking Pace"),
            (121, "Easy Run"),
            (140, "Easy Run"),
            (141, "Moderate Run"),
            (160, "Moderate Run"),
            (161, "Fast Run"),
            (180, "Fast Run"),
            (181, "Sprint"),
            (300, "Sprint"),
            (999, "Sprint"),
        ],
    )
    def test_exact_boundaries(self, bpm, expected):
        assert get_tempo_marking(bpm, self.markings) == expected


class TestGetTempoMarkingEdgeCases:
    @pytest.fixture(autouse=True)
    def scheme(self):
        self.markings = TEMPO_SCHEMES["Italian"]

    def test_zero_bpm_returns_unknown(self):
        assert get_tempo_marking(0, self.markings) == "Unknown"

    def test_negative_bpm_returns_unknown(self):
        assert get_tempo_marking(-1, self.markings) == "Unknown"

    def test_negative_large_returns_unknown(self):
        assert get_tempo_marking(-999, self.markings) == "Unknown"

    def test_bpm_1000_resolves_to_top_band(self):
        assert get_tempo_marking(1000, self.markings) == "Prestissimo"

    def test_extreme_bpm_resolves_to_top_band(self):
        assert get_tempo_marking(50_000, self.markings) == "Prestissimo"

    def test_all_schemes_have_no_upper_limit(self):
        for name, markings in TEMPO_SCHEMES.items():
            result = get_tempo_marking(100_000, markings)
            assert result != "Unknown", f"{name} returned Unknown for BPM 100,000"

    def test_returns_string(self):
        result = get_tempo_marking(120, self.markings)
        assert isinstance(result, str)

    def test_empty_markings_returns_unknown(self):
        assert get_tempo_marking(120, []) == "Unknown"

    def test_all_schemes_cover_bpm_120(self):
        for name, markings in TEMPO_SCHEMES.items():
            result = get_tempo_marking(120, markings)
            assert result != "Unknown", f"{name} returned Unknown for BPM 120"

    def test_all_schemes_cover_bpm_1(self):
        for name, markings in TEMPO_SCHEMES.items():
            result = get_tempo_marking(1, markings)
            assert result != "Unknown", f"{name} returned Unknown for BPM 1"

    def test_all_schemes_cover_bpm_999(self):
        for name, markings in TEMPO_SCHEMES.items():
            result = get_tempo_marking(999, markings)
            assert result != "Unknown", f"{name} returned Unknown for BPM 999"

    # ── Custom-markings edge cases ─────────────────────────────────────────

    def test_custom_gapped_markings_returns_unknown_for_gap(self):
        """A BPM that falls in a gap between two ranges should return Unknown."""
        gapped = [(0, 50, "Low"), (60, 100, "High")]
        assert get_tempo_marking(55, gapped) == "Unknown"

    def test_custom_gapped_markings_resolves_first_band(self):
        gapped = [(0, 50, "Low"), (60, 100, "High")]
        assert get_tempo_marking(25, gapped) == "Low"

    def test_custom_gapped_markings_resolves_second_band(self):
        gapped = [(0, 50, "Low"), (60, 100, "High")]
        assert get_tempo_marking(80, gapped) == "High"

    def test_custom_overlapping_markings_first_match_wins(self):
        """When ranges overlap, the first matching entry must be returned."""
        overlapping = [(0, 80, "Early"), (40, 120, "Late")]
        assert get_tempo_marking(60, overlapping) == "Early"

    def test_custom_overlapping_markings_high_bpm_matches_second(self):
        overlapping = [(0, 80, "Early"), (40, 120, "Late")]
        assert get_tempo_marking(100, overlapping) == "Late"

    def test_custom_overlapping_markings_below_all_returns_unknown(self):
        """A BPM below all closed ranges (but positive) should return Unknown
        when there is no range starting at 0."""
        overlapping = [(10, 80, "Early"), (40, 120, "Late")]
        assert get_tempo_marking(5, overlapping) == "Unknown"

    def test_custom_single_band_closed_works(self):
        single = [(10, 20, "Narrow")]
        assert get_tempo_marking(15, single) == "Narrow"

    def test_custom_single_band_closed_outside_returns_unknown(self):
        single = [(10, 20, "Narrow")]
        assert get_tempo_marking(25, single) == "Unknown"

    def test_custom_open_ended_single_band(self):
        single = [(100, None, "Open")]
        assert get_tempo_marking(150, single) == "Open"
        assert get_tempo_marking(100, single) == "Open"

    def test_custom_open_ended_band_below_min_returns_unknown(self):
        single = [(100, None, "Open")]
        assert get_tempo_marking(50, single) == "Unknown"

    def test_custom_markings_with_float_bpm(self):
        """get_tempo_marking accepts float BPM via duck typing."""
        markings = [(0, 100, "Low"), (101, None, "High")]
        assert get_tempo_marking(99.5, markings) == "Low"
        assert get_tempo_marking(101.0, markings) == "High"
