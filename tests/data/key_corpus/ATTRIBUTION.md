# Key regression corpus — provenance, licences and calibration

The `.ogg` files in this directory are 20-second excerpts of the openings of
preludes and fugues from Book 1 of Bach's *Well-Tempered Clavier*, performed by Kimiko
Ishizaka for the Open Well-Tempered Clavier project and dedicated **CC0 1.0**.
They are test fixtures, not a music distribution: each file is the single
excerpt needed to measure key detection on real music.

Four further clips are dense electronic masters by Johnathon M. Horner (Beat
Mekanik), also CC0 1.0, in the `## Dense clips` table below. Every rule in this
file applies to them equally: their key is the source's, and their rows are the
declaration the suite parses.

## Why the corpus exists

Before this corpus the key suite held only synthetic triads, progressions and
noise. It could prove that the estimator follows a key template, but not what
the detector scores on real recordings, and it could say nothing about whether
`CLARITY_FLOOR` (0.035) or `DEFAULT_LOW_CONFIDENCE_THRESHOLD` (0.25) were placed
correctly. The BPM suite's corpus answers the same question for its gate (D79,
D99); this one follows that design, including the rule that the `## Clips` table
below **is** the corpus's declaration (D147).

## Annotation is the source's key, never the detector's answer

`Annotated key` is the key named by the catalogue and by the file's own title on
Wikimedia Commons ("Prelude No. 5 in D major, BWV 850", "Fugue No. 5 in D major, BWV
850"). No row's key was chosen
by agreeing with `detect_key`: a corpus labelled by the thing it tests cannot
measure it.

## Transformation

Each committed file is a derivative excerpt:

- 20 seconds from the start of the performance (`-ss 0 -t 20`);
- downmixed to mono and resampled to 22 050 Hz;
- encoded as Ogg Vorbis, quality 6.

Quality 6 rather than the BPM corpus's quality 4 is deliberate. At quality 4 one
clip's verdict moved: `B-flat major` read as `Dm` on the encoded copy while the
same excerpt of the source read `Bb`. That clip still moves at quality 6
(`Bb` on the source excerpt, `Dm` on the encode), so it is excluded from the
34 committed clips; every other clip was measured on both the source excerpt
and the committed encode and the two agree. A fixture whose answer changes under an
ordinary lossy encode is measuring the codec, so every committed clip was checked
to reproduce its source excerpt's verdict, and the one that could not be made to
(that B-flat prelude) was dropped rather than shipped as a knife-edge case. The
same reasoning as D137's "write the fixture from a single decode".

Reproduction command (offsets and durations are in the table):

```text
ffmpeg -y -ss 0 -t 20 -i <source-url> \
  -ac 1 -ar 22050 -c:a libvorbis -q:a 6 <clip>.ogg
```

## Clips

`Measured ...` columns are what `analyze_key` reports for the committed file,
decoded at 22 050 Hz. `Outcome` records whether that is the annotated key; a
`wrong (...)` row is a recorded defect, not a clip to be deleted.

| Clip | Annotated key | Offset | Length | Source | Author | Licence | Measured key | Measured clarity | Measured margin | Measured confidence | Outcome |
|------|---------------|--------|--------|--------|--------|---------|--------------|------------------|-----------------|---------------------|---------|
| `bach_wtc1_prelude_01_c_major.ogg` | C | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_01_Prelude_No._1_in_C_major,_BWV_846.ogg> | Kimiko Ishizaka | CC0 1.0 | C | 0.142 | 0.0278 | 0.35 | matched |
| `bach_wtc1_prelude_02_c_minor.ogg` | Cm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_03_Prelude_No._2_in_C_minor,_BWV_847.ogg> | Kimiko Ishizaka | CC0 1.0 | Cm | 0.056 | 0.0088 | 0.11 | matched |
| `bach_wtc1_prelude_03_cs_major.ogg` | C# | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_05_Prelude_No._3_in_C-sharp_major,_BWV_848.ogg> | Kimiko Ishizaka | CC0 1.0 | C# | 0.072 | 0.0016 | 0.02 | matched |
| `bach_wtc1_prelude_04_cs_minor.ogg` | C#m | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_07_Prelude_No._4_in_C-sharp_minor,_BWV_849.ogg> | Kimiko Ishizaka | CC0 1.0 | C#m | 0.105 | 0.0316 | 0.39 | matched |
| `bach_wtc1_prelude_05_d_major.ogg` | D | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_09_Prelude_No._5_in_D_major,_BWV_850.ogg> | Kimiko Ishizaka | CC0 1.0 | F#m | 0.075 | 0.0140 | 0.17 | wrong (mediant) |
| `bach_wtc1_prelude_06_d_minor.ogg` | Dm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_11_Prelude_No._6_in_D_minor,_BWV_851.ogg> | Kimiko Ishizaka | CC0 1.0 | Dm | 0.086 | 0.0069 | 0.09 | matched |
| `bach_wtc1_prelude_07_eb_major.ogg` | Eb | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_13_Prelude_No._7_in_E-flat_major,_BWV_852.ogg> | Kimiko Ishizaka | CC0 1.0 | Eb | 0.083 | 0.0063 | 0.08 | matched |
| `bach_wtc1_prelude_08_eb_minor.ogg` | Ebm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_15_Prelude_No._8_in_E-flat_minor,_BWV_853.ogg> | Kimiko Ishizaka | CC0 1.0 | Ebm | 0.077 | 0.0261 | 0.33 | matched |
| `bach_wtc1_prelude_09_e_major.ogg` | E | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_17_Prelude_No._9_in_E_major,_BWV_854.ogg> | Kimiko Ishizaka | CC0 1.0 | E | 0.085 | 0.0030 | 0.04 | matched |
| `bach_wtc1_prelude_10_e_minor.ogg` | Em | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_19_Prelude_No._10_in_E_minor,_BWV_855.ogg> | Kimiko Ishizaka | CC0 1.0 | Em | 0.078 | 0.0150 | 0.19 | matched |
| `bach_wtc1_prelude_11_f_major.ogg` | F | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_21_Prelude_No._11_in_F_major,_BWV_856.ogg> | Kimiko Ishizaka | CC0 1.0 | Dm | 0.066 | 0.0027 | 0.03 | wrong (relative minor) |
| `bach_wtc1_prelude_12_f_minor.ogg` | Fm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_23_Prelude_No._12_in_F_minor,_BWV_857.ogg> | Kimiko Ishizaka | CC0 1.0 | Fm | 0.082 | 0.0316 | 0.40 | matched |
| `bach_wtc1_prelude_13_fs_major.ogg` | F# | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_25_Prelude_No._13_in_F-sharp_major,_BWV_858.ogg> | Kimiko Ishizaka | CC0 1.0 | C# | 0.095 | 0.0103 | 0.13 | wrong (enharmonic twin) |
| `bach_wtc1_prelude_14_fs_minor.ogg` | F#m | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_27_Prelude_No._14_in_F-sharp_minor,_BWV_859.ogg> | Kimiko Ishizaka | CC0 1.0 | F#m | 0.075 | 0.0050 | 0.06 | matched |
| `bach_wtc1_prelude_15_g_major.ogg` | G | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_29_Prelude_No._15_in_G_major,_BWV_860.ogg> | Kimiko Ishizaka | CC0 1.0 | D | 0.066 | 0.0054 | 0.07 | wrong (dominant) |
| `bach_wtc1_prelude_16_g_minor.ogg` | Gm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_31_Prelude_No._16_in_G_minor,_BWV_861.ogg> | Kimiko Ishizaka | CC0 1.0 | Gm | 0.115 | 0.0369 | 0.46 | matched |
| `bach_wtc1_prelude_17_ab_major.ogg` | Ab | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_33_Prelude_No._17_in_A-flat_major,_BWV_862.ogg> | Kimiko Ishizaka | CC0 1.0 | Eb | 0.081 | 0.0068 | 0.08 | wrong (dominant) |
| `bach_wtc1_prelude_18_gs_minor.ogg` | G#m | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_35_Prelude_No._18_in_G-sharp_minor,_BWV_863.ogg> | Kimiko Ishizaka | CC0 1.0 | B | 0.090 | 0.0109 | 0.14 | wrong (relative major) |
| `bach_wtc1_prelude_19_a_major.ogg` | A | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_37_Prelude_No._19_in_A_major,_BWV_864.ogg> | Kimiko Ishizaka | CC0 1.0 | A | 0.079 | 0.0021 | 0.03 | matched |
| `bach_wtc1_prelude_20_a_minor.ogg` | Am | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_39_Prelude_No._20_in_A_minor,_BWV_865.ogg> | Kimiko Ishizaka | CC0 1.0 | Am | 0.101 | 0.0214 | 0.27 | matched |
| `bach_wtc1_prelude_22_bb_minor.ogg` | Bbm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_43_Prelude_No._22_in_B-flat_minor,_BWV_867.ogg> | Kimiko Ishizaka | CC0 1.0 | Bbm | 0.132 | 0.0583 | 0.73 | matched |
| `bach_wtc1_prelude_23_b_major.ogg` | B | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_45_Prelude_No._23_in_B_major,_BWV_868.ogg> | Kimiko Ishizaka | CC0 1.0 | Ebm | 0.067 | 0.0034 | 0.04 | wrong (tritone) |
| `bach_wtc1_prelude_24_b_minor.ogg` | Bm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_47_Prelude_No._24_in_B_minor,_BWV_869.ogg> | Kimiko Ishizaka | CC0 1.0 | F#m | 0.079 | 0.0104 | 0.13 | wrong (dominant) |
| `bach_wtc1_fugue_01_c_major.ogg` | C | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_02_Fugue_No._1_in_C_major,_BWV_846.ogg> | Kimiko Ishizaka | CC0 1.0 | C | 0.092 | 0.0007 | 0.01 | matched |
| `bach_wtc1_fugue_02_c_minor.ogg` | Cm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_04_Fugue_No._2_in_C_minor,_BWV_847.ogg> | Kimiko Ishizaka | CC0 1.0 | Cm | 0.066 | 0.0147 | 0.18 | matched |
| `bach_wtc1_fugue_03_cs_major.ogg` | C# | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_06_Fugue_No._3_in_C-sharp_major,_BWV_848.ogg> | Kimiko Ishizaka | CC0 1.0 | C# | 0.084 | 0.0118 | 0.15 | matched |
| `bach_wtc1_fugue_04_cs_minor.ogg` | C#m | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_08_Fugue_No._4_in_C-sharp_minor,_BWV_849.ogg> | Kimiko Ishizaka | CC0 1.0 | C#m | 0.091 | 0.0335 | 0.42 | matched |
| `bach_wtc1_fugue_05_d_major.ogg` | D | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_10_Fugue_No._5_in_D_major,_BWV_850.ogg> | Kimiko Ishizaka | CC0 1.0 | A | 0.105 | 0.0034 | 0.04 | wrong (dominant) |
| `bach_wtc1_fugue_06_d_minor.ogg` | Dm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_12_Fugue_No._6_in_D_minor,_BWV_851.ogg> | Kimiko Ishizaka | CC0 1.0 | Dm | 0.069 | 0.0049 | 0.06 | matched |
| `bach_wtc1_fugue_07_eb_major.ogg` | Eb | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_14_Fugue_No._7_in_E-flat_major,_BWV_852.ogg> | Kimiko Ishizaka | CC0 1.0 | Cm | 0.064 | 0.0012 | 0.02 | wrong (relative minor) |
| `bach_wtc1_fugue_09_e_major.ogg` | E | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_18_Fugue_No._9_in_E_major,_BWV_854.ogg> | Kimiko Ishizaka | CC0 1.0 | B | 0.089 | 0.0097 | 0.12 | wrong (dominant) |
| `bach_wtc1_fugue_10_e_minor.ogg` | Em | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_20_Fugue_No._10_in_E_minor,_BWV_855.ogg> | Kimiko Ishizaka | CC0 1.0 | Bm | 0.055 | 0.0163 | 0.20 | wrong (dominant) |
| `bach_wtc1_fugue_11_f_major.ogg` | F | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_22_Fugue_No._11_in_F_major,_BWV_856.ogg> | Kimiko Ishizaka | CC0 1.0 | C | 0.074 | 0.0025 | 0.03 | wrong (dominant) |
| `bach_wtc1_fugue_12_f_minor.ogg` | Fm | 0.00 s | 20.0 s | <https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_24_Fugue_No._12_in_F_minor,_BWV_857.ogg> | Kimiko Ishizaka | CC0 1.0 | C | 0.063 | 0.0049 | 0.06 | wrong (dominant) |

## Dense clips

(D152.) The 34 Bach clips above are solo keyboard, and **every one of them is
named on the first pass** (clarity 0.055-0.142), so they can say nothing about
the dense, drum-led material the percussion-removed second pass exists for
(D151). The clips
in this table are that material: four 20-second sections of two electronic works
whose key the **source states**, so the retry's accuracy can be scored on real
music instead of only its yield.

Both works are by Johnathon M. Horner (Beat Mekanik), released **CC0 1.0** on Free
Music Archive. The licence was read on the track page itself ("licensed under a CC0
1.0 Universal License", linking to `creativecommons.org/publicdomain/zero/1.0/`).
`Annotated key` is the key in the artist's own cue-info block on that page ("Key: G
Sharp Minor", "Key: F Major"); as above, no row's key was chosen by agreeing with
`detect_key`. The audio is the page's own `fileUrl`, cut with the same 20 s / mono /
22 050 Hz / Vorbis q6 transform as the Bach clips. Two sections per work (0 s and
90 s) rather than one, so a single section cannot carry a verdict.

The `Harmonic ...` columns are `_harmonic_pass` on the same decode: the second pass
the engine runs only behind a refusal, measured for every row so the table records
what that pass *would* say. `Pass` is the pass that answered in production.

| Clip | Annotated key | Offset | Length | Source | Author | Licence | Measured key | Measured clarity | Measured margin | Measured confidence | Harmonic key | Harmonic clarity | Pass | Outcome |
|------|---------------|--------|--------|--------|--------|---------|--------------|------------------|-----------------|---------------------|--------------|------------------|------|---------|
| `beatmekanik_electron_gsharp_minor_000.ogg` | G#m | 0.00 s | 20.0 s | <https://freemusicarchive.org/music/beat-mekanik/single/electron-free-stems> | Johnathon M. Horner (Beat Mekanik) | CC0 1.0 | G#m | 0.132 | 0.0460 | 0.58 | G#m | 0.196 | chroma | matched |
| `beatmekanik_electron_gsharp_minor_090.ogg` | G#m | 90.00 s | 20.0 s | <https://freemusicarchive.org/music/beat-mekanik/single/electron-free-stems> | Johnathon M. Horner (Beat Mekanik) | CC0 1.0 | G#m | 0.166 | 0.0208 | 0.26 | G#m | 0.193 | chroma | matched |
| `beatmekanik_dreams_f_major_000.ogg` | F | 0.00 s | 20.0 s | <https://freemusicarchive.org/music/beat-mekanik/single/dreams-free-stems> | Johnathon M. Horner (Beat Mekanik) | CC0 1.0 | Dm | 0.111 | 0.0236 | 0.29 | Dm | 0.143 | chroma | wrong (relative minor) |
| `beatmekanik_dreams_f_major_090.ogg` | F | 90.00 s | 20.0 s | <https://freemusicarchive.org/music/beat-mekanik/single/dreams-free-stems> | Johnathon M. Horner (Beat Mekanik) | CC0 1.0 | Dm | 0.060 | 0.0261 | 0.33 | Dm | 0.097 | chroma | wrong (relative minor) |

**1 of the 2 works is named correctly** (2 of 4 clips). Electron in G sharp minor
is named on both sections; Dreams in F major reads `Dm` on both - the relative
minor, which shares all seven pitch classes with F major, the same miss the Bach
table records for F major. Percussion removal does not repair it: the harmonic pass
returns `Dm` as well (0.143 / 0.097), so the error is in the pitch-class content,
not in drum masking - the hypothesis the retry was built on.

**No clip reaches the retry in production.** All four are named on the first pass at
clarity 0.060-0.166, far above `CLARITY_FLOOR` (0.035), and the harmonic pass agrees
with the first pass on 4 of 4. A dense master is therefore not what the second pass
serves; its population is the quiet tail D151 measured (13 % of the library, four
rescues in 150 tracks). What this table adds is the other half of the picture: on
material that is dense but clear, the retry neither adds a key nor repairs one, and
the relative-minor defect survives it. The honest gap that remains is material the
engine *refuses* and whose key is documented - two CC0 tracks with a stated key is
the whole set available, and neither is refused.

```text
pytest key_detector/tests/test_key_engine.py -k DenseElectronic
```

## Split

The corpus carries a tonic-disjoint split so an algorithm variant can be fitted
on one half and reported on the other instead of on both. **Train** is every clip
whose annotated tonic is a white key (C, D, E, F, G, A, B): 22 clips, named
correctly 12 times by the shipped engine. **Test** is every clip whose annotated
tonic is a black key (C#, Eb, F#, Ab, Bb): 12 clips, named correctly 8 times.
The split is by the tonic's name, not by pitch class, so a whole key family sits
in one half and a variant cannot be credited on material it was fitted to. The
dense electronic clips are in neither half: they are a different material class
and are scored in their own table.

## Calibration (2026-11-13)

**20 of the 34 clips are named correctly** (59 %): 15 of the 23 preludes and 5 of
the 11 fugues. Every clip is *named* - the lowest clarity in the corpus is 0.055,
well above `CLARITY_FLOOR` (0.035) - so the corpus measures which key wins, not
whether a key is reported.

The fourteen misses are all functional neighbours of the tonic, and one class
dominates:

- **dominant, 8 of 14**: D -> `A` (fugue), E -> `B`, Em -> `Bm`, F -> `C` (fugue),
  Fm -> `C`, G -> `D`, Ab -> `Eb`, Bm -> `F#m`;
- **relative minor, 2**: F -> `Dm`, Eb -> `Cm`;
- **relative major, 1**: G#m -> `B`;
- **mediant, 1**: D -> `F#m` (the prelude, not the fugue);
- **enharmonic twin, 1**: F# -> `C#`, two major keys with identical pitch-class
  sets, so no pitch-class method can separate them;
- **tritone, 1**: B -> `Ebm`.

The fugues are markedly harder than the preludes (5 of 11 against 15 of 23), and
five of their six misses are a fifth relation - a fugue states its answer on the
dominant, which lifts the dominant's weight in a pitch-class average. That is a
property of the material, not of the gate.

**No gate threshold can move this.** All 34 clips sit above the clarity floor, so
re-running the engine's own gate at 0.040, 0.047 or 0.055 names the same 34 and
scores the same 20; the margin threshold is inert too (0.05 to 0.60 all give 20),
because real margins are 0.0007-0.0583 and confidence is `margin / 0.08`. At a
0.070 floor 25 clips are named and 17 are correct: the stricter floor refuses
nine clips, loses three correct answers and repairs nothing, because a floor
changes which clips are *named*, never which key wins.

D147 recorded 7 of 11 on the eleven-prelude corpus; adding the remaining twelve
preludes and eleven fugues moves the figure to 20 of 34 and shows that the
dominant, not the relative minor, is the primary defect. Neither the profiles nor
either threshold were touched to produce this table: it is the shipped engine's
answer, recorded.

## Re-running the checks

```text
pytest key_detector/tests/test_key_engine.py -k RealMusicKeyCorpus
```

`TestRealMusicKeyCorpus` parses the table above, asserts the directory and the
rows agree, re-measures every clip against its recorded values, and locks both
the accuracy count and the fact that the two thresholds cannot move it.
