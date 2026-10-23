API reference
=============

One section per module in ``audio_suite_shared``: the package every tool
imports, and the only package whose surface a tool author is expected to use.
The list is exhaustive on purpose — ``tests/test_api_reference.py`` fails when a
module exists that this page does not render, so a new shared module cannot ship
undocumented — and ``tests/test_docs_build.py`` builds this page with Sphinx and
fails on any parser warning, so a malformed docstring cannot ship either.

Output contracts
----------------

.. automodule:: audio_suite_shared.cli_schema
   :members:

.. automodule:: audio_suite_shared.cli_dataclasses
   :members:

.. automodule:: audio_suite_shared.run_outcome
   :members:

CLI plumbing
------------

.. automodule:: audio_suite_shared.cli_app
   :members:

.. automodule:: audio_suite_shared.cli_base
   :members:

.. automodule:: audio_suite_shared.cli_helpers
   :members:

.. automodule:: audio_suite_shared.doctor_cli
   :members:

.. automodule:: audio_suite_shared.cue_cli
   :members:

Cue sheets
----------

.. automodule:: audio_suite_shared.cue_generator
   :members:

.. automodule:: audio_suite_shared.cue_parser
   :members:

.. automodule:: audio_suite_shared.cue_split
   :members:

Configuration, theme and release notes
--------------------------------------

.. automodule:: audio_suite_shared.suite_config
   :members:

.. automodule:: audio_suite_shared.styles
   :members:

.. automodule:: audio_suite_shared.whats_new
   :members:

Install, startup and host capabilities
--------------------------------------

.. automodule:: audio_suite_shared.install_map
   :members:

.. automodule:: audio_suite_shared.runtime_check
   :members:

.. automodule:: audio_suite_shared.platform_support
   :members:

.. automodule:: audio_suite_shared.platform_utils
   :members:

.. automodule:: audio_suite_shared.system_requirements
   :members:

.. automodule:: audio_suite_shared.app_bootstrap
   :members:

.. automodule:: audio_suite_shared.logging_setup
   :members:

.. automodule:: audio_suite_shared.launcher
   :members:

.. automodule:: audio_suite_shared.preflight
   :members:

.. automodule:: audio_suite_shared.venv_bootstrap
   :members:

.. automodule:: audio_suite_shared.project_version
   :members:

Processes, threads and resources
--------------------------------

.. automodule:: audio_suite_shared.resource_manager
   :members:

.. automodule:: audio_suite_shared.secure_subprocess
   :members:

.. automodule:: audio_suite_shared.subprocess_utils
   :members:

.. automodule:: audio_suite_shared.optional_deps
   :members:

.. automodule:: audio_suite_shared.constants
   :members:

Analysis
--------

.. automodule:: audio_suite_shared.analysis_loader
   :members:

.. automodule:: audio_suite_shared.exceptions
   :members:

.. automodule:: audio_suite_shared.gpu_utils
   :members:

Audio formats and DSP
---------------------

.. automodule:: audio_suite_shared.audio_formats
   :members:

.. automodule:: audio_suite_shared.audio_conversion
   :members:

.. automodule:: audio_suite_shared.audio_playback
   :members:

.. automodule:: audio_suite_shared.dsp_chain
   :members:

.. automodule:: audio_suite_shared.dsp_models
   :members:

.. automodule:: audio_suite_shared.lossless_gain
   :members:

Tag reading and writing
-----------------------

.. automodule:: audio_suite_shared.tag_helper
   :members:
   :exclude-members: AudioTagError

.. automodule:: audio_suite_shared.tag_helper_base
   :members:

.. automodule:: audio_suite_shared.tag_helper_reader
   :members:

.. automodule:: audio_suite_shared.tag_helper_writer
   :members:

.. automodule:: audio_suite_shared.tag_helper_mp3
   :members:

.. automodule:: audio_suite_shared.tag_helper_mp4
   :members:

.. automodule:: audio_suite_shared.tag_helper_vorbis
   :members:

.. automodule:: audio_suite_shared.tag_helper_apev2
   :members:

.. automodule:: audio_suite_shared.tag_helper_iffid3
   :members:

.. automodule:: audio_suite_shared.tag_helper_dsf
   :members:

.. automodule:: audio_suite_shared.tag_helper_art
   :members:

.. automodule:: audio_suite_shared.lrc_handler
   :members:

Batch processing and undo
-------------------------

.. automodule:: audio_suite_shared.file_processor_base
   :members:

.. automodule:: audio_suite_shared.batch_undo
   :members:

.. automodule:: audio_suite_shared.error_recovery
   :members:

.. automodule:: audio_suite_shared.error_logger
   :members:

Tool and tab scaffolding
------------------------

.. automodule:: audio_suite_shared.tool_plugin
   :members:

.. automodule:: audio_suite_shared.tool_app_base
   :members:

.. automodule:: audio_suite_shared.analysis_app_base
   :members:

Tk helpers
----------

.. automodule:: audio_suite_shared.ui_common
   :members:

.. automodule:: audio_suite_shared.ui_helpers
   :members:

.. automodule:: audio_suite_shared.ui_audition
   :members:

.. automodule:: audio_suite_shared.ui_driver_controls
   :members:

.. automodule:: audio_suite_shared.undo_gui
   :members:

.. automodule:: audio_suite_shared.thread_safe_slot_var
   :members:
