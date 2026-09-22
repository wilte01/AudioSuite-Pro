"""
audio_suite_shared — Shared utilities for the Audio Suite.

Modules
-------
app_bootstrap    — Standardised app initialisation and BaseSuiteApp base class.
audio_formats    — Supported audio extension constants and helpers.
batch_undo       — Centralised SQLite-backed undo / revert log for batch
                   tag edits and file reorganizations.
cli_dataclasses  — Typed dataclasses for CLI argument objects.
cli_helpers      — Standardised CLI argument handlers.
constants        — Shared named constants (worker counts, timeouts, quality).
dsp_models       — DSP parameter models and presets.
error_logger     — Backward-compatible ErrorLogger wrapper.
error_recovery   — Retry/backoff/recovery-action logic.
exceptions       — AudioSuiteError hierarchy and error-mapping utilities.
platform_utils   — Cross-platform file/folder/help openers.
resource_manager — Thread and temp-file resource tracking.
secure_subprocess— Secure subprocess execution with allowlisting.
styles           — Colour palettes, theme modes, and ttk style application.
suite_config     — JSON config persistence (last-directory, window geometry).
tag_helper       — Format-aware audio tag read/write (re-export facade).
tag_helper_art   — Album art embedding.
tag_helper_base  — Base tag handler ABC and format-specific handlers.
tag_helper_reader— Tag read functions (BPM, key, genre, etc.).
tag_helper_writer— Tag write functions.
ui_common        — Shared Results, Processing, and input-row tab builders.
ui_helpers       — UIHelperMixin with folder/help/log dialog helpers.
"""

from __future__ import annotations
