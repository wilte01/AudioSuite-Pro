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
    "<folder> --fpcalc <path> --json"
)
doc.add_paragraph(
    "Options include --lookup/--no-lookup, "
    "--write-tags/--no-write-tags, --threshold, "
    "--max-length, --fpcalc, --api-key, --dry, "
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
