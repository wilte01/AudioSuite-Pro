"""Tests for audio_fingerprinter.utils.cli_args."""

from __future__ import annotations

from audio_fingerprinter.utils.cli_args import (
    FingerprintArgs,
    parse,
    validate_args,
)


class TestParse:
    def test_empty_argv(self):
        args = parse(["prog"])
        assert args.folder_path == ""
        assert args.lookup_enabled is True
        assert args.write_tags is False

    def test_folder_path(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_no_lookup(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--no-lookup"])
        assert args.lookup_enabled is False

    def test_lookup(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--lookup"])
        assert args.lookup_enabled is True

    def test_write_tags(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--write-tags"])
        assert args.write_tags is True

    def test_threshold(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--threshold", "0.8"])
        assert args.threshold == 0.8

    def test_max_length(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--max-length", "300"])
        assert args.max_length == 300

    def test_fpcalc_path(self, tmp_path):
        exe = tmp_path / "fpcalc.exe"
        exe.write_bytes(b"\x00")
        args = parse(["prog", str(tmp_path), "--fpcalc", str(exe)])
        assert args.fpcalc_path == str(exe)

    def test_api_key(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--api-key", "mykey123"])
        assert args.api_key == "mykey123"

    def test_dry_mode(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry"])
        assert args.live_mode is False

    def test_live_mode(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_auto_start(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start"])
        assert args.auto_start is True

    def test_end_no_end(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--end", "--no-end"])
        assert args.auto_end is False

    def test_clear_logs(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--clear-logs"])
        assert args.clear_logs is True

    def test_parallel_run(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--parallel-run"])
        assert args.parallel_run is True

    def test_invalid_threshold_ignored(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--threshold", "abc"])
        assert args.threshold == 0.5

    def test_invalid_max_length_ignored(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--max-length", "abc"])
        assert args.max_length == 120

    def test_write_mbids(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--write-mbids"])
        assert args.write_mbids is True

    def test_no_write_mbids(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--no-write-mbids"])
        assert args.write_mbids is False

    def test_mbid_region_normalised_to_uppercase(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--mbid-region", "gb"])
        assert args.mbid_region == "GB"

    def test_mbid_region_default_empty(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.mbid_region == ""


class TestValidateArgs:
    def test_valid_args(self):
        args = FingerprintArgs(threshold=0.5, max_length=120)
        errors = validate_args(args)
        assert errors == []

    def test_threshold_below_zero(self):
        args = FingerprintArgs(threshold=-0.1)
        errors = validate_args(args)
        assert any("Threshold" in e for e in errors)

    def test_threshold_above_one(self):
        args = FingerprintArgs(threshold=1.5)
        errors = validate_args(args)
        assert any("Threshold" in e for e in errors)

    def test_max_length_too_small(self):
        args = FingerprintArgs(max_length=0)
        errors = validate_args(args)
        assert any("Max length" in e for e in errors)

    def test_max_length_too_large(self):
        args = FingerprintArgs(max_length=999)
        errors = validate_args(args)
        assert any("Max length" in e for e in errors)

    def test_nonexistent_fpcalc_path(self):
        args = FingerprintArgs(fpcalc_path="/nonexistent/fpcalc")
        errors = validate_args(args)
        assert any("fpcalc" in e for e in errors)

    def test_nonexistent_folder(self):
        args = FingerprintArgs(folder_path="/nonexistent/path")
        errors = validate_args(args)
        assert any("does not exist" in e for e in errors)

    def test_folder_is_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        args = FingerprintArgs(folder_path=str(f))
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)


class TestFingerprintArgs:
    def test_to_params(self):
        args = FingerprintArgs(
            lookup_enabled=False,
            write_tags=True,
            live_mode=True,
            threshold=0.7,
            max_length=300,
            fpcalc_path="/path/to/fpcalc",
        )
        params = args.to_params()
        assert params.lookup_enabled is False
        assert params.write_tags is True
        assert params.is_dry_run is False
        assert params.threshold == 0.7
        assert params.max_length == 300
        assert params.fpcalc_path == "/path/to/fpcalc"

    def test_to_params_defaults_mbid_writes_off(self):
        params = FingerprintArgs().to_params()
        assert params.write_mbids is False
        assert params.mbid_region == ""

    def test_to_params_threads_mbid_preferences(self):
        args = FingerprintArgs(
            write_tags=True,
            live_mode=True,
            write_mbids=True,
            mbid_region="GB",
        )
        params = args.to_params()
        assert params.write_mbids is True
        assert params.mbid_region == "GB"
