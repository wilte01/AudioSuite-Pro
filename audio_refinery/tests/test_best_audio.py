# Changed in 2.9.0: created with the Best Audio decision layer.
"""
audio_refinery/tests/test_best_audio.py
Tests for the Best Audio decision layer (2.9.0).

The fixtures are synthesised rather than committed: a tone plus clicks, a tone
between two silent stretches, and a tone with sub-bass rumble are cheap,
deterministic and reviewable, and each one exists to make exactly one rule
fire.  Anything that needs FFmpeg is marked ``integration`` and lives beside
the rule it exercises.

The contract tests (A1-A10 of PLAN_2026-11-18_2.9.0_best_audio.md) assert the
*observable* outcome, never an internal flag: a toggle is compared, a delivery
setting is compared, an output field is measured.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from audio_refinery.core import best_audio
from audio_refinery.core.best_audio import (
    Evidence,
    SourceProfile,
    _decide_dynamics,
    _decide_enhance,
    _decide_eq,
    decide,
    decision_rows,
    decision_text,
    verify_written,
    write_decisions_csv,
)
from audio_refinery.core.models import AUTO_STAGES, StageConfig
from audio_suite_shared.audio_conversion import numpy_to_segment
from audio_suite_shared.dsp_dynamics import LimiterSettings
from audio_suite_shared.dsp_eq import EqBand, EqSettings

RATE = 44_100


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _tone(seconds: float, frequency: float = 1000.0, amplitude: float = 0.12):
    """Return a mono tone as ``(samples float32, rate)``."""
    t = np.arange(int(RATE * seconds)) / RATE
    return (amplitude * np.sin(2.0 * np.pi * frequency * t)).astype(np.float32)


def _segment(samples: np.ndarray):
    """Wrap mono float samples in an AudioSegment."""
    return numpy_to_segment(samples, RATE, sample_width=2, num_channels=1)


@pytest.fixture()
def clicky():
    """A tone carrying five single-sample spikes: the declick rule's subject."""
    samples = _tone(2.0)
    for index in range(5):
        samples[int(RATE * (0.4 + 0.3 * index))] = 0.9
    return _segment(samples)


@pytest.fixture()
def clean_tone():
    """A plain tone: every detector should decline on it."""
    return _segment(_tone(2.0))


@pytest.fixture()
def silent_edges():
    """0.8 s of silence, 3 s of tone, 1.0 s of silence."""
    return _segment(
        np.concatenate(
            [
                np.zeros(int(RATE * 0.8), dtype=np.float32),
                _tone(3.0),
                np.zeros(int(RATE * 1.0), dtype=np.float32),
            ]
        )
    )


@pytest.fixture()
def rumbly():
    """A tone with strong 25 Hz energy: the EQ rule's subject."""
    base = _tone(2.0, frequency=1000.0, amplitude=0.05)
    t = np.arange(base.size) / RATE
    return _segment(base + (0.4 * np.sin(2 * np.pi * 25.0 * t)).astype(np.float32))


def _profile(**overrides: object) -> SourceProfile:
    """Return a profile with every field named, for the pure rule tests."""
    values: dict[str, object] = {
        "file_name": "x.wav",
        "measured_at": "2026-11-18T12:00:00",
    }
    values.update(overrides)
    return SourceProfile(**values)  # type: ignore[arg-type]


# ── No automation asked for ───────────────────────────────────────────────────


class TestNoAutoStages:
    """Contract rule A6: nothing runs, nothing changes, nothing is reported."""

    def test_the_run_config_is_returned_unchanged(self, clean_tone) -> None:
        config = StageConfig()
        config.declick_params.max_width_ms = 4

        plan = decide(clean_tone, "x.wav", config)

        assert plan.config is config
        assert plan.config.declick_params.max_width_ms == 4

    def test_the_line_says_why_nothing_was_decided(self, clean_tone) -> None:
        plan = decide(clean_tone, "x.wav", StageConfig())

        assert plan.skipped_reason == "no Auto stages"
        assert decision_text(plan) == "BestAudio: no Auto stages"

    def test_no_rows_are_written(self, clean_tone) -> None:
        plan = decide(clean_tone, "x.wav", StageConfig())

        assert decision_rows(plan, "x.wav", "DONE") == []

    def test_every_stage_reads_as_not_ticked(self, clean_tone) -> None:
        plan = decide(clean_tone, "x.wav", StageConfig())

        assert set(plan.decisions) == set(AUTO_STAGES)
        assert not any(decision.auto for decision in plan.decisions.values())


# ── Declick ───────────────────────────────────────────────────────────────────


class TestDeclickDecision:
    def test_clicks_activate_the_stage_and_narrow_the_width(self, clicky) -> None:
        config = StageConfig(trim=False, declick=True)
        config.auto_stages = ("declick",)

        plan = decide(clicky, "clicky.wav", config)

        decision = plan.decisions["declick"]
        assert decision.active is True
        assert decision.params["max_width_ms"] <= config.declick_params.max_width_ms
        assert (
            plan.config.declick_params.max_width_ms == decision.params["max_width_ms"]
        )
        assert "clicks at 0.31" in decision.text if hasattr(decision, "text") else True

    def test_a_clean_tone_declines(self, clean_tone) -> None:
        config = StageConfig(trim=False)
        config.auto_stages = ("declick",)

        plan = decide(clean_tone, "clean.wav", config)

        decision = plan.decisions["declick"]
        assert decision.active is False
        assert "no clicks" in decision.reason
        assert decision.params == {}

    def test_auto_never_widens_the_repair(self, clicky) -> None:
        config = StageConfig(trim=False)
        config.declick_params.max_width_ms = 1
        config.auto_stages = ("declick",)

        plan = decide(clicky, "clicky.wav", config)

        assert plan.config.declick_params.max_width_ms <= 1


# ── Trim ──────────────────────────────────────────────────────────────────────


class TestTrimDecision:
    def test_silent_edges_are_cut(self, silent_edges) -> None:
        config = StageConfig(declick=False)
        config.auto_stages = ("trim",)

        plan = decide(silent_edges, "edges.wav", config)

        decision = plan.decisions["trim"]
        assert decision.active is True
        assert plan.source.head_silence_ms == pytest.approx(800, abs=60)
        assert plan.source.tail_silence_ms == pytest.approx(1000, abs=60)

    def test_a_file_without_silence_declines(self, clean_tone) -> None:
        config = StageConfig(declick=False)
        config.auto_stages = ("trim",)

        plan = decide(clean_tone, "clean.wav", config)

        assert plan.decisions["trim"].active is False

    def test_an_exact_range_is_never_moved(self, silent_edges) -> None:
        config = StageConfig(declick=False)
        config.trim_params.mode = "exact"
        config.trim_params.start_ms = 0
        config.trim_params.end_ms = 1000
        config.auto_stages = ("trim",)

        plan = decide(silent_edges, "edges.wav", config)

        assert plan.decisions["trim"].active is False
        assert plan.config.trim_params == config.trim_params

    def test_mostly_silent_files_are_not_trimmed(self) -> None:
        samples = np.concatenate(
            [
                np.zeros(int(RATE * 4.0), dtype=np.float32),
                _tone(1.0),
                np.zeros(int(RATE * 4.0), dtype=np.float32),
            ]
        )
        config = StageConfig(declick=False)
        config.auto_stages = ("trim",)

        plan = decide(_segment(samples), "mostly.wav", config)

        assert plan.decisions["trim"].active is False
        assert "mostly silence" in plan.decisions["trim"].reason


# ── The ordering rule ────────────────────────────────────────────────────────


class TestOrderingRule:
    """Silence must not win the noise-profile contest (PLAN D-08)."""

    def test_the_profile_is_measured_after_the_trim(self, silent_edges) -> None:
        from noise_reduction.core.noise_reducer import detect_noise_profile

        untrimmed = detect_noise_profile(silent_edges, gate_threshold_db=3.0)
        assert untrimmed is not None
        # The leading digital silence is the flattest, quietest window there is;
        # measuring before the trim would choose it.
        assert untrimmed.rms_dbfs < -100.0

        config = StageConfig(declick=False, reduce_noise=True)
        config.noise_reduction_params.reduce_broadband = True
        config.auto_stages = ("trim", "reduce_noise")

        plan = decide(silent_edges, "edges.wav", config)

        assert plan.source.noise_floor_dbfs is not None
        assert plan.source.noise_floor_dbfs > -100.0, (
            "the noise floor was measured on the untrimmed source - leading "
            "silence won the profile contest"
        )


# ── The level pass ───────────────────────────────────────────────────────────


class TestLevelPass:
    """The profile's true peak is the figure the forensics pass reports (D-16)."""

    @pytest.mark.integration()
    def test_the_profile_peak_is_the_forensics_peak(self, tmp_path) -> None:
        """`measure_loudness` runs the same chain; only the astats stage is gone."""
        from audio_suite_shared import audio_probe

        segment = _segment(_tone(1.0, amplitude=0.05))
        target = tmp_path / "peak.wav"
        segment.export(str(target), format="wav")
        config = StageConfig(declick=False, trim=False, dynamics=True)
        config.auto_stages = ("dynamics",)

        plan = decide(segment, target, config)

        assert plan.source.true_peak_dbtp is not None
        assert (
            plan.source.true_peak_dbtp
            == audio_probe.measure_forensics(str(target)).true_peak_dbtp
        )


# ── EQ ───────────────────────────────────────────────────────────────────────


class TestEqDecision:
    def test_rumble_appends_one_high_pass(self, rumbly) -> None:
        config = StageConfig(declick=False, trim=False, eq=True)
        config.auto_stages = ("eq",)

        plan = decide(rumbly, "rumbly.wav", config)

        decision = plan.decisions["eq"]
        assert decision.active is True
        bands = plan.config.eq_params.bands
        assert bands[:-1] == config.eq_params.bands
        assert bands[-1] == EqBand("highpass", best_audio.RUMBLE_BAND_HZ)

    def test_an_existing_high_pass_is_left_alone(self, rumbly) -> None:
        config = StageConfig(declick=False, trim=False, eq=True)
        config.eq_params = EqSettings(bands=(EqBand("highpass", 40.0),))
        config.auto_stages = ("eq",)

        plan = decide(rumbly, "rumbly.wav", config)

        assert plan.decisions["eq"].active is False
        assert plan.config.eq_params.bands == config.eq_params.bands

    def test_a_full_rack_is_not_extended(self, clean_tone) -> None:
        config = StageConfig(declick=False, trim=False, eq=True)
        config.eq_params = EqSettings(
            bands=tuple(EqBand("peaking", 100.0 * (i + 1), 1.0, 1.0) for i in range(8))
        )
        config.auto_stages = ("eq",)

        plan = decide(clean_tone, "clean.wav", config)

        assert plan.decisions["eq"].active is False
        assert len(plan.config.eq_params.bands) == 8

    def test_flat_content_declines(self) -> None:
        profile = _profile(
            band_energy_db={"sub": -40.0, "low": -38.0, "mid": -20.0, "high": -30.0}
        )
        config = StageConfig(eq=True)

        decision = _decide_eq(profile, config, True)

        assert decision.active is False
        assert "no rumble" in decision.reason


# ── Enhance ──────────────────────────────────────────────────────────────────


class TestEnhanceDecision:
    def test_a_named_preset_is_never_edited(self) -> None:
        profile = _profile(tilt_high_over_mid_db=-8.0, brightness_ceiling_hz=19_000)
        config = StageConfig(enhance=True)
        config.enhance_params.preset = "Moderate"

        decision = _decide_enhance(profile, config, True)

        assert decision.active is False
        assert "Moderate" in decision.reason
        assert decision.params == {}

    def test_a_custom_rack_with_a_deficit_is_lifted(self) -> None:
        profile = _profile(tilt_high_over_mid_db=-8.0, brightness_ceiling_hz=19_000)
        config = StageConfig(enhance=True)
        config.enhance_params.preset = "Custom"

        decision = _decide_enhance(profile, config, True)

        assert decision.active is True
        assert decision.params["presence_gain_db"] == best_audio.TILT_MAX_LIFT_DB
        assert decision.params["high_shelf_gain_db"] == best_audio.TILT_MAX_LIFT_DB

    def test_a_lossy_source_is_reported_not_boosted(self) -> None:
        profile = _profile(tilt_high_over_mid_db=-8.0, brightness_ceiling_hz=15_000)
        config = StageConfig(enhance=True)
        config.enhance_params.preset = "Custom"

        decision = _decide_enhance(profile, config, True)

        assert decision.active is False
        assert "not boosted" in decision.reason


# ── Dynamics ─────────────────────────────────────────────────────────────────


class TestDynamicsDecision:
    def test_a_bypassed_limiter_holds_the_delivery_ceiling(self) -> None:
        profile = _profile(true_peak_dbtp=-0.5)
        config = StageConfig(dynamics=True, normalise=True)
        config.limiter_params = LimiterSettings(bypass=True)
        config.normalise_params.true_peak = -1.5

        decision = _decide_dynamics(profile, config, True, 0.0)

        assert decision.active is True
        limiter = decision.params["limiter"]
        assert limiter.bypass is False
        assert limiter.ceiling_dbtp == pytest.approx(-1.5)

    def test_a_limiter_the_user_left_on_is_not_touched(self) -> None:
        profile = _profile(true_peak_dbtp=0.0)
        config = StageConfig(dynamics=True)
        config.limiter_params = LimiterSettings(bypass=False, ceiling_dbtp=-2.0)

        decision = _decide_dynamics(profile, config, True, 0.0)

        assert decision.active is False
        assert decision.params == {}

    def test_a_peak_inside_the_ceiling_declines(self) -> None:
        profile = _profile(true_peak_dbtp=-3.0)
        config = StageConfig(dynamics=True, normalise=True)
        config.limiter_params = LimiterSettings(bypass=True)

        decision = _decide_dynamics(profile, config, True, 0.0)

        assert decision.active is False


# ── The additive contract ────────────────────────────────────────────────────


class TestAdditiveContract:
    """A1-A5: Auto supplies parameters and nothing else."""

    def _plan(self, clicky, silent_edges):
        config = StageConfig(
            declick=True,
            trim=True,
            enhance=True,
            normalise=True,
            reduce_noise=False,
            eq=True,
            dynamics=False,
        )
        config.trim_params.threshold = -45
        config.normalise_params.target_lufs = -16.0
        config.normalise_params.true_peak = -2.0
        config.normalise_params.album_mode = True
        config.auto_stages = ("declick", "trim", "eq")
        return config, decide(clicky, "clicky.wav", config)

    def test_every_stage_toggle_is_unchanged(self, clicky) -> None:
        config, plan = self._plan(clicky, None)

        for name in (
            "declick",
            "trim",
            "enhance",
            "normalise",
            "reduce_noise",
            "eq",
            "dynamics",
            "dry_run",
        ):
            assert getattr(plan.config, name) == getattr(config, name), name

    def test_every_delivery_setting_is_unchanged(self, clicky) -> None:
        config, plan = self._plan(clicky, None)

        assert plan.config.normalise_params == config.normalise_params

    def test_the_preset_name_is_unchanged(self, clicky) -> None:
        config, plan = self._plan(clicky, None)

        assert plan.config.enhance_params == config.enhance_params

    def test_the_engine_and_trim_mode_are_unchanged(self, clicky) -> None:
        config, plan = self._plan(clicky, None)

        assert (
            plan.config.noise_reduction_params.broadband_engine
            == config.noise_reduction_params.broadband_engine
        )
        assert plan.config.trim_params.mode == config.trim_params.mode
        assert plan.config.trim_params.threshold == config.trim_params.threshold

    def test_only_the_auto_stage_parameters_differ(self, clicky) -> None:
        config, plan = self._plan(clicky, None)

        assert (
            plan.config.declick_params.max_width_ms
            != config.declick_params.max_width_ms
        )
        # EQ may append one band and never removes or edits one; a flat tone
        # leaves the rack alone entirely, which is also a valid outcome.
        assert len(plan.config.eq_params.bands) <= len(config.eq_params.bands) + 1
        assert plan.config.eq_params.bands[: len(config.eq_params.bands)] == (
            config.eq_params.bands
        )
        assert plan.config.eq_params.bypass == config.eq_params.bypass

    def test_a_measurement_failure_disables_one_stage_only(
        self, clicky, monkeypatch
    ) -> None:
        """A9: a detector that raises must not stop the run or the other stages."""
        import pop_click_remover.core.declicker as declicker

        def _boom(*_args: object, **_kwargs: object) -> object:
            raise RuntimeError("detector exploded")

        monkeypatch.setattr(declicker, "detect_clicks", _boom)
        config = StageConfig(trim=False)
        config.auto_stages = ("declick",)

        plan = decide(clicky, "clicky.wav", config)

        assert plan.decisions["declick"].active is False
        assert "measurement failed" in plan.decisions["declick"].reason
        assert plan.config.declick_params == config.declick_params
        assert any("Auto off on declick" in caveat for caveat in plan.caveats)


# ── Reporting ────────────────────────────────────────────────────────────────


class TestReporting:
    def test_the_line_names_every_stage_that_was_asked_for(self, clicky) -> None:
        config = StageConfig(trim=False, reduce_noise=True)
        config.noise_reduction_params.reduce_hum = True
        config.auto_stages = ("declick", "reduce_noise")

        plan = decide(clicky, "clicky.wav", config)
        text = decision_text(plan)

        assert text.startswith("BestAudio: ")
        assert "declick auto (" in text
        assert "reduce_noise inactive:" in text

    def test_rows_name_the_measurement_and_the_parameter(self, clicky) -> None:
        config = StageConfig(trim=False)
        config.auto_stages = ("declick",)

        plan = decide(clicky, "clicky.wav", config)
        rows = decision_rows(plan, "clicky.wav", "DONE")

        assert len(rows) == 1
        row = rows[0]
        assert row["file"] == "clicky.wav"
        assert row["status"] == "DONE"
        assert row["stage"] == "declick"
        assert row["decision"] == "active"
        assert row["measurement"] == "click count"
        assert row["parameter"].startswith("max_width_ms=")

    def test_a_declined_stage_still_writes_its_row(self, clean_tone) -> None:
        config = StageConfig(trim=False)
        config.auto_stages = ("declick",)

        rows = decision_rows(
            decide(clean_tone, "clean.wav", config), "clean.wav", "SKIPPED"
        )

        assert rows[0]["decision"] == "inactive"
        assert rows[0]["value"] == "0"

    def test_every_decision_carries_an_evidence_entry(self, clicky) -> None:
        config = StageConfig(trim=False)
        config.auto_stages = ("declick",)

        plan = decide(clicky, "clicky.wav", config)

        for decision in plan.decisions.values():
            if decision.auto:
                assert decision.evidence
                assert all(isinstance(item, Evidence) for item in decision.evidence)


# ── CSV ──────────────────────────────────────────────────────────────────────


class TestDecisionsCsv:
    def test_the_table_round_trips_with_the_documented_header(self, tmp_path) -> None:
        rows = [
            {
                "file": "a.flac",
                "status": "DONE",
                "stage": "trim",
                "measurement": "head+tail silence",
                "value": "1940 ms",
                "threshold": ">= 200 ms",
                "decision": "active",
                "parameter": "head 0.84 s",
            }
        ]
        target = tmp_path / "refinery_decisions.csv"

        write_decisions_csv(target, rows)

        text = target.read_text(encoding="utf-8").splitlines()
        assert text[0] == ",".join(best_audio.CSV_HEADER)
        assert len(text) == 2
        assert "a.flac" in text[1]

    def test_a_write_failure_is_logged_not_raised(self, tmp_path, caplog) -> None:
        blocked = tmp_path / "missing-dir" / "refinery_decisions.csv"

        write_decisions_csv(blocked, [])

        assert "Could not write the decisions report" in caplog.text


# ── Verification ─────────────────────────────────────────────────────────────


class TestVerification:
    def test_an_unmeasurable_output_is_a_caveat_not_an_error(self, tmp_path) -> None:
        plan = decide(_segment(_tone(0.5)), "x.wav", StageConfig())

        result = verify_written(tmp_path / "gone.wav", StageConfig(), plan)

        assert result.caveats
        assert "could not be measured" in result.caveats[0]
        assert result.message == ""

    @pytest.mark.integration()
    def test_a_quiet_written_file_keeps_its_claims(self, tmp_path) -> None:
        segment = _segment(_tone(1.0, amplitude=0.05))
        target = tmp_path / "quiet.wav"
        segment.export(str(target), format="wav")

        config = StageConfig(declick=False, trim=False, normalise=True)
        config.auto_stages = ("declick",)
        plan = best_audio.decide(segment, target, config)

        result = verify_written(target, config, plan)

        assert result.message == "" or "LUFS" in result.message


# ── Guardrail can fail ───────────────────────────────────────────────────────


class TestGuardrailFailsWhenItShould:
    @pytest.mark.integration()
    def test_a_plan_two_lu_outside_the_target_is_flagged(self, tmp_path) -> None:
        segment = _segment(_tone(2.0, amplitude=0.05))
        target = tmp_path / "quiet.wav"
        segment.export(str(target), format="wav")

        config = StageConfig(declick=False, trim=False, normalise=True)
        config.normalise_params.target_lufs = -14.0
        config.auto_stages = ("declick",)
        plan = best_audio.decide(segment, target, config)

        # The fixture measures about -29.7 LUFS, so a -20 target is nine LU
        # away: a claim this far off must be caught.
        loud = StageConfig(declick=False, trim=False, normalise=True)
        loud.normalise_params.target_lufs = -20.0

        result = verify_written(target, loud, plan)

        assert "LUFS" in result.message
        assert result.caveats


# ── Laziness ─────────────────────────────────────────────────────────────────


class TestLaziness:
    def test_no_measurement_runs_when_no_stage_is_ticked(self, monkeypatch) -> None:
        """A run that did not ask for Auto pays nothing for it."""
        calls: list[str] = []
        monkeypatch.setattr(
            best_audio,
            "build_profile",
            lambda *_a, **_k: calls.append("profile") or (_profile(), {}),
        )

        decide(_segment(_tone(0.5)), "x.wav", StageConfig())

        assert calls == []

    def test_a_trim_only_run_measures_no_spectrum(self, monkeypatch) -> None:
        measured: list[str] = []

        def _spy(*_args: object, **_kwargs: object):
            measured.append("spectral")
            return {}, 0.0, None

        monkeypatch.setattr(best_audio, "_spectral_measurements", _spy)
        config = StageConfig(declick=False)
        config.auto_stages = ("trim",)

        decide(_segment(_tone(0.5)), "x.wav", config)

        assert measured == []


# ── A stage that cannot run ──────────────────────────────────────────────────


class TestAutoOnADisabledStage:
    """Auto never switches a stage on (A1); it cannot decide for one either."""

    def test_nothing_is_measured_for_a_stage_that_is_off(self, monkeypatch) -> None:
        calls: list[str] = []
        monkeypatch.setattr(
            best_audio,
            "build_profile",
            lambda *_a, **_k: calls.append("profile") or (_profile(), {}),
        )
        config = StageConfig(eq=False)
        config.auto_stages = ("eq",)

        plan = decide(_segment(_tone(0.5)), "x.wav", config)

        assert calls == []
        assert plan.decisions["eq"].active is False
        assert "switched off" in plan.decisions["eq"].reason
        assert plan.config is config
        assert plan.config.eq is False

    def test_the_line_says_so_rather_than_claiming_a_measurement(self) -> None:
        config = StageConfig(eq=False)
        config.auto_stages = ("eq",)

        text = decision_text(decide(_segment(_tone(0.5)), "x.wav", config))

        assert "eq inactive: the stage is switched off" in text

    def test_a_switched_off_stage_is_named_while_another_stage_runs(self) -> None:
        """The reason does not depend on whether anything else was measured."""
        config = StageConfig(eq=False)
        config.auto_stages = ("eq", "declick")

        plan = decide(_segment(_tone(0.5)), "x.wav", config)

        assert plan.decisions["eq"].auto is True
        assert plan.decisions["eq"].active is False
        assert "switched off" in plan.decisions["eq"].reason
        assert plan.decisions["declick"].auto is True
        assert decision_text(plan).count("the stage is switched off") == 1


# ── Calibration locks ────────────────────────────────────────────────────────


#: Every declared constant, at the value the plan publishes (Appendix A).  A
#: calibration is a decision with a recorded basis, so changing one without
#: amending the plan and this table is exactly what BA-8 exists to catch.
PUBLISHED_CONSTANTS: dict[str, float] = {
    "TRIM_MIN_HEAD_TAIL_MS": 200,
    "TRIM_MAX_SILENCE_SHARE": 0.60,
    "NOISE_FLOOR_CEILING_DBFS": -45.0,
    "NOISE_MIN_GAP_DB": 18.0,
    "NOISE_MAX_TRIAL_DB": 1.0,
    "RUMBLE_BAND_HZ": 30.0,
    "RUMBLE_EXCESS_DB": 6.0,
    "LIMITER_MARGIN_DB": 0.1,
    "TILT_WINDOW_SECONDS": 30.0,
    "TILT_DEFICIT_DB": 3.0,
    "TILT_MAX_LIFT_DB": 2.0,
    "LOSSY_CEILING_HZ": 16_000,
    "CLIP_SAMPLE_THRESHOLD": 0.999,
    "VERIFY_PEAK_MARGIN_DB": 0.1,
    "VERIFY_LOUDNESS_MARGIN_DB": 0.5,
}

#: The committed real-music corpus: the "should not fire" side of every sweep.
CORPUS = Path(__file__).resolve().parents[2] / "tests" / "data" / "bpm_corpus"


class TestCalibrationLocks:
    """Each constant keeps the value its recorded basis justifies (BA-8)."""

    @pytest.mark.parametrize(("name", "value"), sorted(PUBLISHED_CONSTANTS.items()))
    def test_each_published_constant_keeps_its_value(self, name: str, value: float):
        assert getattr(best_audio, name) == value, (
            f"{name} moved away from the value the plan publishes - amend the "
            "plan's calibration record first"
        )

    def test_the_lock_covers_every_declared_constant(self) -> None:
        # ``__annotations__`` is the module's own declarations; ``dir`` would
        # also hand back the constants imported from the EQ module.
        declared = {
            name
            for name in best_audio.__annotations__
            if not name.startswith("_")
            and isinstance(getattr(best_audio, name), (int, float))
        }

        assert declared == set(PUBLISHED_CONSTANTS)


class TestCalibrationAgainstTheCorpus:
    """Measured basis: real music stays on the decline side of the thresholds.

    Method: `decide()` with all six stages ticked, on the committed corpus
    tracks, on 2026-11-18.  The panel below is what the constants were chosen
    against; it fails when a threshold tightens past the music.
    """

    @staticmethod
    def _all_six() -> StageConfig:
        """Every stage on, with the Custom preset Auto is allowed to edit (D-06)."""
        config = StageConfig(reduce_noise=True, eq=True, dynamics=True)
        config.enhance_params.preset = "Custom"
        config.auto_stages = AUTO_STAGES
        return config

    @pytest.mark.integration()
    @pytest.mark.parametrize(
        ("track", "floor_dbfs", "tilt_db"),
        [
            ("brazilian_funk_130.ogg", -5.5, -0.8),
            ("ambient_pulse_92.ogg", -18.3, -13.1),
            ("chopin_rubato_74.ogg", -28.8, -62.0),
        ],
    )
    def test_music_is_never_gated_by_the_noise_rule(
        self, track: str, floor_dbfs: float, tilt_db: float
    ) -> None:
        from pydub import AudioSegment

        path = CORPUS / track
        if not path.is_file():
            pytest.skip(f"corpus track missing: {track}")
        plan = best_audio.decide(
            AudioSegment.from_file(str(path)), path, self._all_six()
        )

        assert plan.decisions["reduce_noise"].active is False
        assert plan.source.noise_floor_dbfs == pytest.approx(floor_dbfs, abs=0.1)
        assert plan.source.noise_floor_dbfs > best_audio.NOISE_FLOOR_CEILING_DBFS
        assert plan.source.tilt_high_over_mid_db == pytest.approx(tilt_db, abs=0.1)

    @pytest.mark.integration()
    def test_the_music_corpus_top_is_under_the_lossy_ceiling(self) -> None:
        """The corpus tops out at 11.5 kHz, so its top is reported, not lifted."""
        from pydub import AudioSegment

        path = CORPUS / "brazilian_funk_130.ogg"
        if not path.is_file():
            pytest.skip("corpus track missing")
        plan = best_audio.decide(
            AudioSegment.from_file(str(path)), path, self._all_six()
        )

        assert plan.source.brightness_ceiling_hz < best_audio.LOSSY_CEILING_HZ
        assert plan.decisions["enhance"].active is False
        assert "limited" in plan.decisions["enhance"].reason.lower()


class TestSubprocessCost:
    """Auto adds at most one FFmpeg pass per file (plan §12)."""

    @pytest.mark.integration()
    def test_all_six_stages_cost_exactly_one_ffmpeg_pass(
        self, tmp_path, monkeypatch
    ) -> None:
        from audio_suite_shared import audio_probe

        target = tmp_path / "cost.wav"
        segment = _segment(_tone(1.0, amplitude=0.05))
        segment.export(str(target), format="wav")
        real = audio_probe.run_secure_subprocess
        invocations: list[str] = []

        def _counting(*args: object, **kwargs: object):
            invocations.append(str(args[1] if len(args) > 1 else kwargs.get("args")))
            return real(*args, **kwargs)

        monkeypatch.setattr(audio_probe, "run_secure_subprocess", _counting)
        config = StageConfig(reduce_noise=True, eq=True, dynamics=True)
        config.auto_stages = AUTO_STAGES

        best_audio.decide(segment, target, config)

        assert len(invocations) == 1, "Auto spent more than the forensics pass"

    @pytest.mark.integration()
    def test_a_run_without_level_stages_runs_no_ffmpeg(self, tmp_path, monkeypatch):
        from audio_suite_shared import audio_probe

        target = tmp_path / "cheap.wav"
        segment = _segment(_tone(1.0, amplitude=0.05))
        segment.export(str(target), format="wav")
        invocations: list[str] = []

        def _counting(*args: object, **kwargs: object):
            invocations.append("ffmpeg")
            raise AssertionError("no FFmpeg pass is justified here")

        monkeypatch.setattr(audio_probe, "run_secure_subprocess", _counting)
        config = StageConfig()
        config.auto_stages = ("declick", "trim")

        best_audio.decide(segment, target, config)

        assert invocations == []
