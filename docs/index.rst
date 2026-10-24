AudioSuite-Pro API reference
============================

AudioSuite-Pro is a suite of audio tools driven through one Click CLI and one
Master Driver GUI. This reference documents ``audio_suite_shared``, the package
every tool imports: the JSON output contract, the shared CLI options, the
configuration store, and the install/analysis helpers.

Tool packages (``bpm_analyzer``, ``audio_refinery``, …) are documented by their
own user guides, which describe behaviour rather than imports. The CLI contract
they all publish is described here, and ``audiosuite --json-schema`` prints the
machine-readable version.

.. toctree::
   :maxdepth: 2

   api
   plugins
