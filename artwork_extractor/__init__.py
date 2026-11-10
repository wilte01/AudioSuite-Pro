"""artwork_extractor — the Artwork Extractor window (2.6.0 batch step).

The window writes each file's embedded cover beside it as a sidecar, through
the same :mod:`audio_suite_shared.tag_helper_art` reader the CLI's
``audiosuite artwork extract`` uses.

Changed in 2.6.0: new package — the extraction job's Master Driver batch step.
"""
