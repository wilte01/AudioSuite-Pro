# Changelog

All notable changes to AudioSuite-Pro are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Versions of the tools are released together with the suite (the single
`version` in `pyproject.toml` covers the whole distribution).

## [Unreleased]

## [1.0.0] - 2026-09-26

First recorded baseline. Package metadata, releases, and this changelog start
here; earlier history is in the repository's `PLAN_*.md` audit records.

### Added

- Initial distribution baseline: 27 registered tools across the Enrich /
  Utility / Refinery categories, the Master Driver control panel, the
  shared `audiosuite` CLI, and the `audio_suite_shared` foundation layer.
- Baseline commit audited on 2026-09-26: 6,978 tests passing / 5 skipped,
  coverage 78.26%, `ruff` clean, `mypy --strict` clean, bandit 0 High /
  0 Medium. That audit is recorded in `PLAN_iteration5_remediation.md`, and
  its findings are remediated across that plan's staged, evidence-recorded
  work (starting with this changelog's next entries).
