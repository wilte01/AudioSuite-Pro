"""app.py — Spectral Viewer GUI.

Shows one FFT spectrogram at a time for a folder's audio files, with matplotlib
embedded in Tk. Zoom and pan are the matplotlib navigation toolbar's (the same
box-zoom, pan, home and save controls every matplotlib figure has) rather than
bespoke mouse handling: the toolbar is battle-tested and adds no state of ours.

Rendering is synchronous. A spectrogram of a normal track takes well under a
second, so a worker thread would only buy the Tk cross-thread hazard
(``root.after`` from a non-main thread) that the library-stats suite had to
work around; a long file is bounded by the shared 600 s analysis cap.

No global matplotlib backend is selected: ``FigureCanvasTkAgg`` is used
directly and ``pyplot`` is never imported, so this tool cannot change another
tool's backend in the same process.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1 / D42).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import Any

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.ui_helpers import UIHelperMixin, show_error_from_exception
from spectral_viewer.core.spectrogram import (
    DEFAULT_CMAP,
    DEFAULT_DB_RANGE,
    DEFAULT_N_FFT,
    build_figure,
    compute_spectrogram,
    export_image,
    iter_audio_files,
    output_path_for,
)
from spectral_viewer.ui.controls import ViewerControls, build_controls
from spectral_viewer.utils import cli_args


class SpectralViewerApp(UIHelperMixin):
    """Spectral Viewer window."""

    HELP_GUIDE = "Spectral_Viewer_User_Guide.docx"

    def __init__(
        self,
        root: tk.Tk,
        *,
        path: str = "",
        output_dir: str = "",
        n_fft: int = DEFAULT_N_FFT,
        db_range: float = DEFAULT_DB_RANGE,
    ) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Spectral Viewer",
            "spectral_viewer_window",
            "spectral_viewer",
            width=1200,
            height=800,
        )

        self._output_dir = output_dir
        self._files: list[str] = []
        self._selected: str | None = None
        self._figure: Any = None
        self._canvas: FigureCanvasTkAgg | None = None
        self._toolbar: NavigationToolbar2Tk | None = None

        self.path_var = tk.StringVar(value=path or suite_config.load_last_directory())
        self.start_var = tk.StringVar(value="0")
        self.end_var = tk.StringVar(value="0")
        self.max_freq_var = tk.StringVar(value="0")
        self.db_range_var = tk.StringVar(value=f"{db_range:g}")
        self.n_fft_var = tk.StringVar(value=str(n_fft))
        self.cmap_var = tk.StringVar(value=DEFAULT_CMAP)
        self.status_var = tk.StringVar(
            value="Select an audio file or folder, then Render."
        )

        self._controls: ViewerControls
        self._canvas_frame: tk.Frame
        self._build_ui()

        if self.path_var.get().strip():
            self._scan_path()

    # ── Construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Lay out the control panel, the figure area and the status bar."""
        self.root.title("Spectral Viewer")

        outer = tk.Frame(self.root, bg=styles.BG_APP, padx=12, pady=10)
        outer.pack(fill="both", expand=True)
        body = tk.Frame(outer, bg=styles.BG_WHITE)
        body.pack(fill="both", expand=True)

        self._controls = build_controls(
            body,
            path_var=self.path_var,
            start_var=self.start_var,
            end_var=self.end_var,
            max_freq_var=self.max_freq_var,
            db_range_var=self.db_range_var,
            n_fft_var=self.n_fft_var,
            cmap_var=self.cmap_var,
            on_browse=self._browse,
            on_scan=self._scan_path,
            on_select=self._on_select,
            on_render=self._render_selected,
            on_export=self._export,
        )

        self._canvas_frame = tk.Frame(body, bg=styles.BG_WHITE)
        self._canvas_frame.pack(side=tk.LEFT, fill="both", expand=True)

        tk.Button(
            body,
            text="Help",
            command=lambda: self._open_help_standard(self.HELP_GUIDE),
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            relief="flat",
            padx=8,
        ).place(relx=1.0, rely=1.0, anchor="se")

        tk.Label(
            self.root,
            textvariable=self.status_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_SUB,
            anchor="w",
            padx=12,
            pady=4,
        ).pack(fill="x")

    # ── Actions ───────────────────────────────────────────────────────────

    def _browse(self) -> None:
        """Ask for a folder and load its audio files."""
        folder = filedialog.askdirectory(initialdir=self.path_var.get() or "")
        if not folder:
            return
        self.path_var.set(folder)
        suite_config.save_last_directory(folder)
        self._scan_path()

    def _scan_path(self) -> None:
        """Load the audio files at the path entry into the list box."""
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("No Path", "Choose an audio file or folder first.")
            return
        try:
            files = iter_audio_files(path)
        except OSError as exc:
            show_error_from_exception(exc, title="Path Error")
            return

        self._files = files
        self._controls.file_list.delete(0, tk.END)
        for source in files:
            self._controls.file_list.insert(tk.END, os.path.basename(source))

        if not files:
            self._selected = None
            self.status_var.set("No supported audio files found.")
            return

        self.status_var.set(f"{len(files)} audio file(s) found.")
        # A programmatic selection does not fire <<ListboxSelect>>, so the
        # render is routed through the same update the event handler uses.
        self._controls.file_list.selection_clear(0, tk.END)
        self._controls.file_list.selection_set(0)
        self._select_index(0)

    def _on_select(self, _event: object) -> None:
        """Render the file the user picked in the list box."""
        selection = self._controls.file_list.curselection()
        if not selection:
            return
        self._select_index(int(selection[0]))

    def _select_index(self, index: int) -> None:
        """Render the file at *index* of the loaded list.

        Args:
            index: Position in the file list.
        """
        if not 0 <= index < len(self._files):
            return
        self._selected = self._files[index]
        self._render(self._files[index])

    def _render_selected(self) -> None:
        """Re-render the current file after a settings change."""
        if self._selected is None:
            messagebox.showwarning(
                "No File", "Choose a folder and render a file first."
            )
            return
        self._render(self._selected)

    def _render(self, source: str) -> None:
        """Compute and display the spectrogram of *source*.

        Args:
            source: Audio file to render.
        """
        try:
            start = self._number(self.start_var, "Start")
            end = self._number(self.end_var, "End")
            max_freq = self._number(self.max_freq_var, "Max frequency")
            db_range = self._number(self.db_range_var, "Colour range")
            n_fft = int(self._number(self.n_fft_var, "FFT size"))
        except ValueError as exc:
            messagebox.showwarning("Invalid Setting", str(exc))
            return

        try:
            data = compute_spectrogram(
                source,
                start=start,
                end=end,
                n_fft=n_fft,
                max_freq=max_freq,
            )
        except (AudioSuiteError, OSError, ValueError) as exc:
            self.status_var.set(f"Could not render {os.path.basename(source)}.")
            show_error_from_exception(exc, title="Spectrogram Error")
            return

        figure = build_figure(
            data,
            title=os.path.basename(source),
            dynamic_range_db=db_range,
            cmap=self.cmap_var.get() or DEFAULT_CMAP,
        )
        self._show_figure(figure)
        self._controls.export_button.config(state="normal")
        self.status_var.set(
            f"{os.path.basename(source)}: {data.shape[0]} bins x "
            f"{data.shape[1]} frames, {data.duration_secs:.1f}s @ "
            f"{data.sample_rate} Hz, peak {data.peak_db:.1f} dBFS"
        )

    def _show_figure(self, figure: Any) -> None:
        """Embed *figure* in the canvas area with the navigation toolbar.

        Args:
            figure: A figure returned by ``build_figure``.
        """
        for widget in self._canvas_frame.winfo_children():
            widget.destroy()

        canvas = FigureCanvasTkAgg(figure, master=self._canvas_frame)
        canvas.draw()
        toolbar = NavigationToolbar2Tk(canvas, self._canvas_frame, pack_toolbar=False)
        toolbar.update()
        toolbar.pack(side=tk.BOTTOM, fill="x")
        canvas.get_tk_widget().pack(side=tk.TOP, fill="both", expand=True)

        self._figure = figure
        self._canvas = canvas
        self._toolbar = toolbar

    def _export(self) -> None:
        """Write the displayed figure as a PNG."""
        if self._figure is None or self._selected is None:
            messagebox.showwarning(
                "No Spectrogram", "Render a spectrogram before exporting it."
            )
            return

        suggested = output_path_for(self._selected, self._output_dir or None)
        destination = filedialog.asksaveasfilename(
            initialdir=str(suggested.parent),
            initialfile=suggested.name,
            title="Export Spectrogram",
            defaultextension=".png",
            filetypes=[("PNG image", "*.png")],
        )
        if not destination:
            return

        try:
            export_image(self._figure, destination)
        except OSError as exc:
            show_error_from_exception(exc, title="Export Error")
            return
        self.status_var.set(f"Exported {os.path.basename(destination)}")

    @staticmethod
    def _number(variable: tk.StringVar, label: str) -> float:
        """Return *variable* as a float, or raise a user-facing ``ValueError``.

        Args:
            variable: The entry's variable.
            label: Field name used in the error message.

        Raises:
            ValueError: If the entry is not a number.
        """
        raw = variable.get().strip()
        try:
            return float(raw)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number, got {raw!r}.") from exc


def main() -> None:
    """Parses the launcher argv, pre-fills the window and enters the mainloop."""
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    SpectralViewerApp(
        root,
        path=args.folder_path,
        output_dir=args.output_dir,
        n_fft=args.n_fft,
        db_range=args.db_range,
    )
    root.mainloop()
