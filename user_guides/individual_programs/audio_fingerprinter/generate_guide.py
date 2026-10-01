"""Generate a fresh Audio Fingerprinter guide from the current implementation."""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUTPUT = (
    "D:\\Users\\wilte\\Desktop\\AudioSuite-Pro\\user_guides\\individual_programs\\"
    "audio_fingerprinter\\Audio_Fingerprinter_User_Guide.docx"
)


def bullet(doc: Document, title: str, text: str) -> None:
    paragraph = doc.add_paragraph(style="List Bullet")
    paragraph.add_run(title).bold = True
    paragraph.add_run(text)


doc = Document()
title = doc.add_heading("Audio Fingerprinter - User Guide", level=0)
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
subtitle = doc.add_paragraph("Based on the current Audio Fingerprinter implementation")
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER

doc.add_heading("Overview", level=1)
doc.add_paragraph(
    "Audio Fingerprinter generates Chromaprint "
    "fingerprints with the external fpcalc utility "
    "and can identify tracks through AcoustID. It "
    "can run as a fingerprint-only analysis, identify "
    "likely recordings, or write AcoustID metadata "
    "to matched files. The selected directory is "
    "scanned recursively for supported audio files "
    "using four worker slots."
)

doc.add_heading("Prerequisites", level=1)
bullet(
    doc,
    "fpcalc: ",
    "Install Chromaprint fpcalc, add it to PATH, "
    "set FPCALC, or choose its executable in Setup.",
)
bullet(
    doc,
    "AcoustID application key: ",
    "Required when lookup is enabled. It can be "
    "stored encrypted in suite configuration or "
    "supplied through ACOUSTID_API_KEY or a one-run "
    "CLI option.",
)
bullet(
    doc,
    "Network access: ",
    "Lookup mode contacts AcoustID with a default "
    "30-second timeout and a one-request-per-second "
    "rate limit.",
)

doc.add_heading("Quick Start", level=1)
for step in (
    "Open Audio_Fingerprinter.pyw.",
    "Select the directory containing audio files.",
    "Confirm that fpcalc is found and configure an "
    "AcoustID application key if lookup is enabled.",
    "Leave Dry Run selected and use the default minimum score of 0.5.",
    "Keep Write AcoustID tags disabled for the first pass.",
    "Click START FINGERPRINTING and review the Results tab and log.",
    "Use Live Update with tag writing enabled only after reviewing matches.",
):
    doc.add_paragraph(step, style="List Number")

doc.add_heading("GUI Setup", level=1)
doc.add_paragraph(
    "Setup contains the directory picker, fpcalc path, "
    "API key controls, lookup and tag-writing "
    "switches, score threshold, analysis length, and "
    "shared run controls. The last-used directory is "
    "restored from suite configuration."
)
bullet(
    doc,
    "fpcalc Binary: ",
    "Leave blank for FPCALC/PATH resolution or browse "
    "to an executable. The status line reports the "
    "resolved path.",
)
bullet(
    doc,
    "AcoustID API Key: ",
    "Enter a key and Save Key to encrypt it into "
    "suite configuration, or Clear to remove the "
    "stored key.",
)
bullet(
    doc,
    "Look up tracks: ",
    "Queries AcoustID after fingerprint generation; "
    "enabled by default and requires a key.",
)
bullet(
    doc,
    "Write AcoustID tags: ",
    "Writes match metadata only for a match in Live Update mode; disabled by default.",
)
bullet(
    doc,
    "Write MusicBrainz identifiers: ",
    "Adds MUSICBRAINZ_TRACKID, MUSICBRAINZ_ARTISTID "
    "and (when one release is unambiguous) "
    "MUSICBRAINZ_ALBUMID to the AcoustID tags. Needs "
    "the option above and Live Update; disabled by "
    "default. The album id is never guessed - a "
    "recording is typically released many times, and "
    "the id is written only when exactly one release "
    "survives the selection criteria below.",
)
bullet(
    doc,
    "MBID Region: ",
    "Optional two-letter country code (ISO 3166-1 "
    "alpha-2, e.g. GB) stored in suite configuration. "
    "It only breaks ties between otherwise identical "
    "releases (same track and disc counts, same "
    "release group); it can never select a release "
    "on its own.",
)
bullet(
    doc,
    "Album Match: ",
    "Clusters each folder's lookups by MusicBrainz release "
    "group and tags only when the album is decided. A "
    "release group forms a cluster when at least three "
    "files (the --album-min default) carry candidates in "
    "it; the cluster is decided when its score (files "
    "voting times average confidence) leads the runner-up "
    "by 25 percent. Well-known albums often tie exactly "
    "(one test album produced eight clusters at the same "
    "score, because a recording appears on every release "
    "group containing it); when the files share one album "
    "tag and it matches exactly one tied cluster, that "
    "cluster is decided - the user's own tag is the "
    "evidence, and a match against several clusters still "
    "refuses to guess. Ambiguous albums are left untagged "
    "with the whole tied set named in the log. Files no "
    "decided cluster claims fall back to per-file matching. "
    "Disabled by default.",
)
bullet(
    doc,
    "Min Score: ",
    "Accepts candidates from 0.0 to 1.0; default 0.5. Higher values are stricter.",
)
bullet(
    doc,
    "Max Length: ",
    "Maximum seconds sent to fpcalc, from 1 to 600; "
    "default 120. fpcalc still reports full file "
    "duration for lookup checks.",
)
bullet(
    doc,
    "Dry Run / Live Update: ",
    "Dry Run prevents tag writes. Live Update is required for tag writing.",
)

doc.add_heading("Processing and Results", level=1)
doc.add_paragraph(
    "Processing shows total and processed counts, "
    "errors, per-file status lines, and four "
    "worker-slot labels. Each file is fingerprinted, "
    "optionally looked up, and optionally tagged. "
    "Results reports identified matches, no matches, "
    "tags written, lookup skips, errors, and "
    "elapsed time."
)
doc.add_paragraph(
    "The GUI writes fingerprint_dry_run_log.txt or "
    "fingerprint_live_log.txt in the input directory. "
    "Results are sorted by file path when displayed."
)
doc.add_paragraph(
    "In Album Match mode the log starts with one "
    "[ALBUM] line per folder summarising the cluster "
    "decision, files decided by an album carry an "
    "'album consensus' note in their message, and the "
    "summary adds an Album Ambiguous count when any "
    "folder tied."
)

doc.add_heading("Fingerprinting Pipeline", level=1)
for step in (
    "Discover supported audio files recursively below the selected directory.",
    "Resolve fpcalc using the explicit path, FPCALC, or PATH.",
    "Run fpcalc with the selected maximum length and parse DURATION and FINGERPRINT.",
    "Skip lookup when disabled or when no key is available.",
    "Send the fingerprint and duration to AcoustID when lookup is enabled.",
    "Filter candidates by score and duration "
    "consistency, then choose the best recording.",
    "Optionally write Acoustid Fingerprint and Acoustid Id in Live Update mode.",
):
    doc.add_paragraph(step, style="List Number")
doc.add_paragraph(
    "Album Match mode runs the same pipeline in two "
    "phases: every file is fingerprinted first (the live "
    "log shows ANALYSED lines), then all lookups run "
    "through the rate-limited batch client, each folder "
    "is clustered by MusicBrainz release group, and only "
    "decided albums are tagged."
)

doc.add_heading("AcoustID Matching", level=1)
bullet(
    doc,
    "Score threshold: ",
    "Candidates below the selected score are discarded; scores range from 0.0 to 1.0.",
)
bullet(
    doc,
    "Duration guard: ",
    "Candidates must have a duration consistent with "
    "the file using the service's seven-second "
    "threshold plus a five-percent allowance for "
    "long tracks.",
)
bullet(
    doc,
    "Candidate limit: ",
    "Up to ten distinct recording candidates are retained per lookup.",
)
bullet(
    doc,
    "Near ties: ",
    "When top scores are within 0.10, existing artist "
    "and title tags resolve the tie when they agree; "
    "otherwise the ambiguity and runner-up are "
    "reported.",
)
bullet(
    doc,
    "No match: ",
    "A file receives NO MATCH when no candidate "
    "remains above the score and duration guardrails.",
)
bullet(
    doc,
    "Album clustering: ",
    "In Album Match mode each folder's candidates are "
    "grouped by MusicBrainz release group. A group with "
    "at least the album-minimum of voting files forms a "
    "cluster scored as (files voting) times (average "
    "confidence). A cluster is decided only when it "
    "leads the runner-up by 25 percent; otherwise the "
    "album is reported ambiguous and its files are left "
    "untagged with both clusters named. A decided "
    "cluster pulls each voting file to its best "
    "candidate inside the winning release group, which "
    "resolves remix-versus-original near ties that "
    "per-file scores cannot. Files outside the decided "
    "cluster keep the per-file matching described "
    "above, including the tag-aware near-tie break.",
)

doc.add_heading("Tags and Key Storage", level=1)
doc.add_paragraph(
    "When a match is found and tag writing is enabled "
    "in Live Update mode, the shared writer records "
    "the Chromaprint as Acoustid Fingerprint and the "
    "selected service identifier as Acoustid Id. Tag "
    "changes participate in the suite batch undo "
    "system."
)
doc.add_paragraph(
    "When Write MusicBrainz identifiers is also "
    "enabled, the run writes the matched recording as "
    "MUSICBRAINZ_TRACKID, the credited artist as "
    "MUSICBRAINZ_ARTISTID, and - only when exactly one "
    "release survives - the release as "
    "MUSICBRAINZ_ALBUMID. The identifiers are stored "
    "in each format's native convention: TXXX frames "
    "for MP3/WAV/AIFF, Vorbis comments for "
    "FLAC/OGG/Opus, and iTunes freeform atoms for "
    "M4A/MP4."
)
doc.add_paragraph(
    "The album id uses the releases already reported "
    "by AcoustID - no separate MusicBrainz lookup is "
    "made. Candidates are narrowed in order by an "
    "existing MUSICBRAINZ_ALBUMID on the file, the "
    "album title, the folder's track count and disc "
    "count (Album Match folders provide these), the "
    "release-group type, and finally the MBID Region "
    "preference. A criterion that would eliminate "
    "every candidate is ignored, and if more than one "
    "release still survives the field is simply not "
    "written. In per-file runs the track and disc "
    "counts are usually unknown, so the album id "
    "resolves less often than the track and artist "
    "ids."
)
doc.add_paragraph(
    "The effective API key is resolved from "
    "ACOUSTID_API_KEY first, then the encrypted "
    "acoustid_api_key value in shared suite "
    "configuration. A CLI --api-key value is used "
    "for that run. Do not place keys in scripts or "
    "logs."
)

doc.add_heading("Command Line", level=1)
doc.add_paragraph("The registered command is fingerprint. Examples:")
doc.add_paragraph(
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --no-lookup\n"
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --threshold 0.7 --max-length 120\n"
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --write-tags --live --api-key <key>\n"
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --album-mode --album-min 3 --write-tags --live\n"
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --write-tags --write-mbids --mbid-region GB --live\n"
    "python -m audio_suite_shared.cli_app fingerprint "
    "<folder> --fpcalc <path> --json"
)
doc.add_paragraph(
    "Options include --lookup/--no-lookup, "
    "--write-tags/--no-write-tags, "
    "--write-mbids/--no-write-mbids (needs "
    "--write-tags), --mbid-region (two-letter release "
    "country tie-break), --threshold, "
    "--max-length, --fpcalc, --api-key, "
    "--album-mode/--no-album-mode (cluster each folder "
    "by release group; tag only decided albums), "
    "--album-min (minimum voting files per release "
    "group, default 3, at least 1), --dry, "
    "and --json. Lookup requires an API key. Text "
    "output reports files, identified matches, tagged "
    "files, errors, and elapsed time."
)

doc.add_heading("Master Driver Use", level=1)
doc.add_paragraph(
    "From the Master Driver, open ENRICH and select "
    "Audio Fingerprinter. The driver passes the "
    "directory, mode, start/end behavior, and "
    "fingerprint options through the launch handshake. "
    "A driven launch can auto-start and displays "
    "inherited controls."
)

doc.add_heading("Troubleshooting", level=1)
bullet(
    doc,
    "fpcalc required: ",
    "Install Chromaprint, set FPCALC, add fpcalc to PATH, or browse to the executable.",
)
bullet(
    doc,
    "API key required: ",
    "Configure encrypted storage, set "
    "ACOUSTID_API_KEY, or provide --api-key when "
    "lookup is enabled.",
)
bullet(
    doc,
    "No matches: ",
    "Check the threshold, increase analysis length "
    "when appropriate, and confirm the recording "
    "is represented by AcoustID.",
)
bullet(
    doc,
    "Wrong match: ",
    "Review score and existing artist/title tags. "
    "Near ties are tag-resolved when possible and "
    "otherwise marked ambiguous.",
)
bullet(
    doc,
    "Tags not written: ",
    "Confirm Live Update and Write AcoustID tags are "
    "enabled, and that files are writable. Dry Run "
    "never writes tags.",
)
bullet(
    doc,
    "MusicBrainz album id missing: ",
    "The matched recording spans several "
    "indistinguishable releases, so the run omits "
    "MUSICBRAINZ_ALBUMID rather than guess. Set an "
    "MBID Region, use Album Match so the folder's "
    "track and disc counts can narrow the candidates, "
    "or accept that only the track and artist ids "
    "were written.",
)
bullet(
    doc,
    "Album files left untagged (ALBUM AMBIGUOUS): ",
    "The folder's release-group clusters tied inside "
    "the decision margin, so album mode refuses to "
    "guess; the log names every tied cluster and its "
    "scores, and the files' shared album tag already "
    "decides the tie when it matches exactly one of "
    "them. Otherwise lower --album-min, fix the "
    "album tag, or resolve the ambiguity manually; "
    "a run without Album Match still applies per-file "
    "matching.",
)
bullet(
    doc,
    "A file errors: ",
    "Check codec support, fpcalc output, permissions, "
    "network access, and the per-file log message.",
)

doc.add_heading("Safety and Recovery", level=1)
doc.add_paragraph(
    "Start with Dry Run and tag writing disabled. "
    "Fingerprinting does not alter audio files, but "
    "Live Update modifies metadata in place. Keep "
    "backups and use the suite's Undo Tag Edits "
    "workflow for available tag snapshots."
)

doc.save(OUTPUT)
print(f"Saved to {OUTPUT}")
