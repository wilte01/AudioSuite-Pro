# BPM regression corpus — provenance, licences and calibration

The `.ogg` files in this directory are short excerpts of real recordings used
to regress the BPM Analyzer's onset-periodicity gate
(`bpm_analyzer/core/bpm_detector.py`) against actual music rather than only
synthetic clicks. They are test fixtures, not a music distribution: each file
is the single excerpt needed for the regression.

Every source was verified on **2026-10-20** through the Wikimedia Commons API
(`prop=imageinfo&iiprop=url|size|mime|extmetadata`). All seven are dedicated to
the public domain under **CC0 1.0 Universal**
(<https://creativecommons.org/publicdomain/zero/1.0/>), which permits
redistribution and derivative works without conditions. Attribution is
recorded here because the provenance of a binary fixture should be reviewable,
not because the licence requires it.

## Transformation

Each committed file is a derivative excerpt:

- the 20-second window centred on the source (the whole file when it is
  shorter), except where a start offset is listed below;
- downmixed to mono, resampled to 22 050 Hz;
- encoded as Ogg Vorbis, quality 4 (`-c:a libvorbis -q:a 4`);
- kept under 200 kB by `bpm_analyzer/tests/test_bpm_detector.py`.

Reproduction command (offsets and durations are in the table):

```text
ffmpeg -y -ss <offset> -t <seconds> -i <source-url> \
  -ac 1 -ar 22050 -c:a libvorbis -q:a 4 <clip>.ogg
```

## Clips

| Clip | Annotated pulse | Offset | Length | Source | Author |
|------|-----------------|--------|--------|--------|--------|
| `brazilian_funk_130.ogg` | 130 BPM | 0.00 s | 3.7 s | <https://commons.wikimedia.org/wiki/File:Brazilian-funk-metallic-hits_130bpm_B_minor.wav> | Musiclover242 |
| `hiphop_86.ogg` | 86 BPM | 177.50 s | 20 s | <https://commons.wikimedia.org/wiki/File:Friendly_Evil_Gangsta_Synth_Hip_Hop.ogg> | Mesostic |
| `krautrock_152.ogg` | 152 BPM | 0.00 s | 14 s | <https://commons.wikimedia.org/wiki/File:Marco_Kalnenek_-_122_-_ElectricShockingKrautRockingMinimalMachine.ogg> | Marco Kalnenek |
| `lick_swing_120.ogg` | 120 BPM | 0.00 s | 16.6 s | <https://commons.wikimedia.org/wiki/File:TheLickSwing.wav> | Roost |
| `live_jazz_103.ogg` | 103 BPM | 92.86 s | 20 s | <https://commons.wikimedia.org/wiki/File:Jazz_at_the_park.ogg> | Manwithmetalpig |
| `samba_103.ogg` | 103 BPM | 78.36 s | 20 s | <https://commons.wikimedia.org/wiki/File:Malaventura_-_08_-_Sambaal.ogg> | Malaventura |
| `swing_152.ogg` | 152 BPM | 312.02 s | 20 s | <https://commons.wikimedia.org/wiki/File:Lloyd_Rodgers_-_14_-_the_swing_-_lloyd_rodgers.ogg> | Lloyd Rodgers |

The annotated pulse is the musical tempo, not necessarily the exact value the
tracker returns: metrical level is ambiguous (a hip-hop beat at 86 BPM and its
eighth-note grid at 172 BPM are the same music), so the regression accepts the
annotated tempo or its double/half within +/-4 BPM. The two files that state a
tempo in their own title/source description are the 130 BPM funk loop and the
120 BPM MuseScore swing exercise; the rest were annotated from the recording's
pulse.

## Calibration (2026-10-20)

Measured through `detect_bpm`'s pipeline at HEAD, with the harmonic-comb score
and `MIN_ONSET_PERIODICITY = 0.10`:

| Clip | Measured score | Detected BPM |
|------|----------------|--------------|
| `brazilian_funk_130.ogg` | 0.328 | 129 |
| `hiphop_86.ogg` | 0.366 | 86 |
| `krautrock_152.ogg` | 0.349 | 152 |
| `lick_swing_120.ogg` | 0.188 | 118 |
| `live_jazz_103.ogg` | 0.154 | 103 |
| `samba_103.ogg` | 0.579 | 103 |
| `swing_152.ogg` | 0.595 | 152 |

The weakest recording scores 1.54x the floor. Seeded white, pink and brown
noise (600 windows of 30 s, 22 050 Hz) never exceeded **0.080**, 1.25x below
the floor. Synthetic click trains score 0.21-0.32 with 10% timing jitter and
0.84-0.97 clean, so the floor sits above every noise sample and below every
musical and degraded-beat sample measured.

Re-run the corpus checks with:

```text
pytest bpm_analyzer/tests/test_bpm_detector.py -k RealMusicCorpus
```

`TestRealMusicCorpus` asserts the calibration margins (music >= 1.2x the
floor, seeded noise < the floor) rather than the exact per-file scores, so a
librosa upgrade may move values slightly without failing the corpus; a change
that lets noise through or drags real music under the floor does fail it.
