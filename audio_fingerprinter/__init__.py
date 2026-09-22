"""Audio Fingerprinter — fingerprint audio files and identify tracks via AcoustID.

Generates Chromaprint fingerprints with the external ``fpcalc`` binary and
queries the AcoustID web service to identify unknown tracks.  Optionally
writes the ``Acoustid Fingerprint`` and ``Acoustid Id`` tags when a match is
found.
"""

__version__ = "0.1.0"
