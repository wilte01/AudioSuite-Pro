# BPM regression corpus — provenance, licences and calibration

The `.ogg` files in this directory are short excerpts of real recordings used
to regress the BPM Analyzer's onset-periodicity gate
(`bpm_analyzer/core/bpm_detector.py`) against actual music rather than only
synthetic clicks. They are test fixtures, not a music distribution: each file
is the single excerpt needed for the regression.

Every source was verified through the Wikimedia Commons API
(`prop=imageinfo&iiprop=url|size|mime|extmetadata`) — the seven original clips on
**2026-10-20**, the five added by S5-5 on **2026-10-21**, and the one added by
backlog P5 later the same day. All thirteen are
dedicated to the public domain under **CC0 1.0 Universal**
(<https://creativecommons.org/publicdomain/zero/1.0/>), which permits
redistribution and derivative works without conditions. Attribution is
recorded here because the provenance of a binary fixture should be reviewable,
not because the licence requires it.

## The `## Clips` table is the source of truth

`TestRealMusicCorpus` parses the table below, so it is not documentation about
the corpus — it **is** the corpus's declaration. A `.ogg` file with no row here
fails the suite, and a row with no file fails it too. That is deliberate
(S5-5, D99): the expectations used to live in a `_CORPUS_TEMPOS` dict in the
test module, which let a clip be deleted from the directory while its
annotation stayed behind, and gave a recording the gate refuses no honest
place to go.

A row whose **Annotated pulse** is `refused` declares a recording the gate
must *not* report: the test asserts `NoTempoDetectedError` and that the
recorded score (or its absence, `-`) agrees with that refusal. A refused row
is a decision recorded, never a broken clip to be silently dropped, and never
a reason to lower `MIN_ONSET_PERIODICITY`.

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

`Annotated pulse` is the musical tempo, or `refused` when the recording must
not yield one. `Measured score` is the harmonic-comb score at the tempo the
tracker estimates, and `Detected BPM` what `detect_bpm` actually returns —
both re-measured on the committed files. `-` means the estimate was
non-positive, so no periodicity was computed at all.

| Clip | Annotated pulse | Offset | Length | Source | Author | Licence | Measured score | Detected BPM |
|------|-----------------|--------|--------|--------|--------|---------|----------------|--------------|
| `ambient_beatless.ogg` | refused | 11.20 s | 20 s | <https://commons.wikimedia.org/wiki/File:John_Bartmann_-_back-to-bali-master.ogg> | John Bartmann | CC0 1.0 | - | refused (no beat) |
| `ambient_pulse_60.ogg` | 60 BPM | 40.00 s | 20 s | <https://commons.wikimedia.org/wiki/File:John_Bartmann_-_dark-highway-master.ogg> | John Bartmann | CC0 1.0 | 0.746 | 120 |
| `ambient_pulse_92.ogg` | 92 BPM | 11.20 s | 20 s | <https://commons.wikimedia.org/wiki/File:John_Bartmann_-_enigmatic-needle-master.ogg> | John Bartmann | CC0 1.0 | 0.297 | 92 |
| `blues_shuffle_152.ogg` | 152 BPM | 25.09 s | 20 s | <https://commons.wikimedia.org/wiki/File:US_Army_Blues_-_09_-_Barbara.ogg> | U.S. Army Blues | CC0 1.0 | 0.252 | 152 |
| `brazilian_funk_130.ogg` | 130 BPM | 0.00 s | 3.7 s | <https://commons.wikimedia.org/wiki/File:Brazilian-funk-metallic-hits_130bpm_B_minor.wav> | Musiclover242 | CC0 1.0 | 0.328 | 129 |
| `chopin_rubato_74.ogg` | 74 BPM | 168.00 s | 20 s | <https://commons.wikimedia.org/wiki/File:Chopin_-_Nocturne_Op._15_no._2_in_F_sharp_major.ogg> | Frédéric Chopin | CC0 1.0 | 0.124 | 148 |
| `freejazz_freetime.ogg` | refused | 58.63 s | 20 s | <https://commons.wikimedia.org/wiki/File:Breuss_Arrizabalaga_Quintet_-_01_-_The_Dark_Side_Of_Frigiliana.ogg> | Breuss Arrizabalaga Quintet | CC0 1.0 | 0.061 | refused (score) |
| `hiphop_86.ogg` | 86 BPM | 177.50 s | 20 s | <https://commons.wikimedia.org/wiki/File:Friendly_Evil_Gangsta_Synth_Hip_Hop.ogg> | Mesostic | CC0 1.0 | 0.366 | 86 |
| `krautrock_152.ogg` | 152 BPM | 0.00 s | 14 s | <https://commons.wikimedia.org/wiki/File:Marco_Kalnenek_-_122_-_ElectricShockingKrautRockingMinimalMachine.ogg> | Marco Kalnenek | CC0 1.0 | 0.349 | 152 |
| `lick_swing_120.ogg` | 120 BPM | 0.00 s | 16.6 s | <https://commons.wikimedia.org/wiki/File:TheLickSwing.wav> | Roost | CC0 1.0 | 0.188 | 118 |
| `live_jazz_103.ogg` | 103 BPM | 92.86 s | 20 s | <https://commons.wikimedia.org/wiki/File:Jazz_at_the_park.ogg> | Manwithmetalpig | CC0 1.0 | 0.154 | 103 |
| `samba_103.ogg` | 103 BPM | 78.36 s | 20 s | <https://commons.wikimedia.org/wiki/File:Malaventura_-_08_-_Sambaal.ogg> | Malaventura | CC0 1.0 | 0.579 | 103 |
| `swing_152.ogg` | 152 BPM | 312.02 s | 20 s | <https://commons.wikimedia.org/wiki/File:Lloyd_Rodgers_-_14_-_the_swing_-_lloyd_rodgers.ogg> | Lloyd Rodgers | CC0 1.0 | 0.595 | 152 |

The annotated pulse is the musical tempo, not necessarily the exact value the
tracker returns: metrical level is ambiguous (a hip-hop beat at 86 BPM and its
eighth-note grid at 172 BPM are the same music), so the regression accepts the
annotated tempo or its double/half within +/-4 BPM. `chopin_rubato_74.ogg`
returns 148 for that reason: 148 is the nocturne's eighth-note level. The
files that state a tempo in their own title or source description are the
130 BPM funk loop and the 120 BPM MuseScore swing exercise; the rest were
annotated from the recording's pulse.

`ambient_pulse_60.ogg` is the one row whose annotation and detection differ by
the tool's *range policy* rather than by metrical level: its raw estimate is
**60.09 BPM**, below `detect_bpm`'s 75 BPM floor, so the tool doubles it and
reports **120**. That is the documented below-range correction working, and it
makes this the only clip in the corpus that exercises it. The pulse level is
evidence, not an assumption: on the committed file the harmonic-comb score is
**0.746 at 60 BPM** and **0.423 at 120 BPM**, so the once-per-second pulse is
the musical one — a double-time grid would have to score higher at 120.

## What the added feels are (S5-5)

| Feel | Clip | Outcome |
|------|------|---------|
| Free-time jazz | `freejazz_freetime.ogg` | **Refused.** An avant-garde quintet passage with no sustained pulse: the tracker estimates 107.67 BPM and the comb score is 0.061, so the gate correctly declines. Probed windows at 6.5/19.5/39.1/58.6/78.2/97.7/117.3 s scored 0.145/0.122/0.180/0.061/0.071/0.062/0.064 — the head has a pulse, the free section does not, and the free section is the excerpt worth locking. |
| Ambient, no pulse | `ambient_beatless.ogg` | **Refused.** No positive estimate at all (tempo 0 on every probed window), so this is the zero-tempo branch: the message carries no score because none was computed. |
| Ambient with a slow pulse | `ambient_pulse_92.ogg` | **Accepted** at 92 BPM, score 0.297. The slowest sustained pulse among the CC0 ambient candidates S5-5 verified; `calabi-yau-master` (123 BPM) and `dusty-sopranos-master` (152 BPM) are faster. **Superseded as the slow row by P5:** `ambient_pulse_60.ogg` is a literal 60 BPM drone, so this row is now the mid-tempo ambient evidence rather than the closest available substitute. |
| Rubato classical | `chopin_rubato_74.ogg` | **Accepted** at the eighth-note level (148), score 0.124 — the weakest accepted clip and the binding case for the 1.2x margin. Windows probed at 11.2/33.6/67.2/100.8/134.4/168.0/201.6 s scored 0.084/0.095/0.112/0.093/0.123/0.124/0.052: rubato playing straddles the floor, which is the tightest real-music evidence in the corpus. |
| Shuffle/compound | `blues_shuffle_152.ogg` | **Accepted** at 152 BPM, score 0.252, a 12/8 blues shuffle — the compound feel the corpus's straight-eighth swing clips did not cover. |

## Calibration (2026-10-21)

Measured through `detect_bpm`'s pipeline at HEAD, with the harmonic-comb score
and `MIN_ONSET_PERIODICITY = 0.10`; the figures are the `Measured score` column
above and are asserted against the committed files within +/-0.05.

The weakest accepted recording is **`chopin_rubato_74.ogg` at 0.124**, 1.24x
the floor (previously `live_jazz_103.ogg` at 0.154, 1.54x). Seeded white, pink
and brown noise (600 windows of 30 s, 22 050 Hz) never exceeded **0.080**,
1.25x below the floor; the shorter 20 s windows the suite measures peak at
0.090. Synthetic click trains score 0.21-0.32 with 10% timing jitter and
0.84-0.97 clean, so the floor sits above every noise sample and below every
musical and degraded-beat sample measured.

Adding rubato playing moved the binding real-music margin from 1.54x to 1.24x:
the promise the suite locks is unchanged (music >= 1.2x the floor, noise < the
floor), but its headroom is now 0.04 rather than 0.54, and the rubato clip is
the one that decides it.

Backlog P5 added the corpus's slowest accepted recording, and its strongest
score: `ambient_pulse_60.ogg` measures **0.746**, 7.5x the floor, on a steady
60 BPM pulse. The margin the suite promises is unaffected - it is decided by
the weakest clip, not the strongest - so the binding case stays the rubato
nocturne at 0.124.

Re-run the corpus checks with:

```text
pytest bpm_analyzer/tests/test_bpm_detector.py -k RealMusicCorpus
```

`TestRealMusicCorpus` asserts the calibration margins (music >= 1.2x the
floor, seeded noise < the floor) and that each row's recorded score still
describes the file, rather than pinning an exact value, so a librosa upgrade
may move values slightly without failing the corpus; a change that lets noise
through or drags real music under the floor does fail it.
