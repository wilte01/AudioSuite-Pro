API reference
=============

One section per shared module a tool author is expected to import. Modules not
listed here are internal wiring (log handlers, Tk helpers); they are still
documented in their own docstrings, and this page can grow as they stabilise.

Output contract
---------------

.. automodule:: audio_suite_shared.cli_schema
   :members:
   :undoc-members:

CLI plumbing
------------

.. automodule:: audio_suite_shared.cli_base
   :members: RunFailure, finish_run

.. automodule:: audio_suite_shared.cli_app
   :members:

Configuration and theme
-----------------------

.. automodule:: audio_suite_shared.suite_config
   :members:

.. automodule:: audio_suite_shared.styles
   :members:

Install and runtime
-------------------

.. automodule:: audio_suite_shared.install_map
   :members:

.. automodule:: audio_suite_shared.runtime_check
   :members:

.. automodule:: audio_suite_shared.platform_support
   :members:

Analysis
--------

.. automodule:: audio_suite_shared.analysis_loader
   :members:

.. automodule:: audio_suite_shared.exceptions
   :members:

Tool registration
-----------------

.. automodule:: audio_suite_shared.tool_plugin
   :members:
