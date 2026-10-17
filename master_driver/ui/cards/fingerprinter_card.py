"""Audio Fingerprinter card for Master Driver UI.

Changed in 1.2.0: adds the MusicBrainz enrichment and ISRC tag-write
toggles.
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Generates Chromaprint fingerprints with the fpcalc binary and\n"
            "identifies tracks via the AcoustID web service.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        r0 = tk.Frame(body, bg=styles.BG_WHITE)
        r0.pack(fill="x", pady=1)
        tk.Checkbutton(
            r0,
            text="Lookup matches via AcoustID",
            variable=state.fingerprinter_lookup,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Checkbutton(
            r1,
            text="Write fingerprint tags to files",
            variable=state.fingerprinter_write_tags,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)

        r1b = tk.Frame(body, bg=styles.BG_WHITE)
        r1b.pack(fill="x", pady=1)
        tk.Checkbutton(
            r1b,
            text="Enrich matches from MusicBrainz (ISRCs, release facts)",
            variable=state.fingerprinter_musicbrainz,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)

        r1c = tk.Frame(body, bg=styles.BG_WHITE)
        r1c.pack(fill="x", pady=1)
        tk.Checkbutton(
            r1c,
            text="Write ISRC tags (needs MusicBrainz + tags + Live)",
            variable=state.fingerprinter_write_isrc,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)

        r2 = tk.Frame(body, bg=styles.BG_WHITE)
        r2.pack(fill="x", pady=1)
        tk.Label(
            r2,
            text="Score Threshold:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r2,
            textvariable=state.fingerprinter_threshold,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r3 = tk.Frame(body, bg=styles.BG_WHITE)
        r3.pack(fill="x", pady=1)
        tk.Label(
            r3,
            text="Max Analysis Length (s):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r3,
            textvariable=state.fingerprinter_max_length,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r4 = tk.Frame(body, bg=styles.BG_WHITE)
        r4.pack(fill="x", pady=1)
        tk.Label(
            r4,
            text="fpcalc Path (optional):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r4,
            textvariable=state.fingerprinter_fpcalc,
            width=20,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r5 = tk.Frame(body, bg=styles.BG_WHITE)
        r5.pack(fill="x", pady=1)
        tk.Label(
            r5,
            text="AcoustID API Key:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r5,
            textvariable=state.fingerprinter_api_key,
            width=20,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

    build_card_shell(
        parent,
        title="Audio Fingerprinter",
        toggle_var=state.module_toggles["fingerprinter"],
        body_builder=_body,
    )
