"""window.py — the window behind ``Example_Plugin.pyw``.

The launcher is a ``.pyw`` file, which Python will not import as a module, so
anything worth testing has to live here: the window class, the one write path
for its folder entry, and :func:`main`, which reads the Master Driver's
arguments and applies them before the window is shown.

The driver launches a plugin tool with
``[directory, --live|--dry, --start|--no-start, --end|--no-end]``.  The folder
and the run mode are pre-filled; ``--start`` runs the report as soon as the
window opens; ``--end`` closes the window when that run finishes, which is what
lets the Master Driver launch this example as a batch step.  The walk and the
tag reads happen on a worker thread, which puts its result on a queue that the
window polls with ``root.after`` — so a slow drive does not freeze the window,
and every Tk call stays on the thread that owns the interpreter.

Changed in 2.1.0: new module — moved out of the launcher so the argv pre-fill
can be tested without a display, and so the driver's folder and mode reach the
window instead of being ignored.
Changed in 2.1.0: honours ``--start``/``--end``; the report runs off the Tk
thread and a run that was asked to close does so.  A failed run keeps the
window open so its message is readable rather than dying with the process.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from collections.abc import Sequence
from tkinter import filedialog, ttk

from example_plugin.tool import LaunchOptions, parse_launch_args, summarise

#: How long the window waits between looks at the worker's queue, in
#: milliseconds.  Short enough to feel immediate, long enough to cost nothing.
_POLL_INTERVAL_MS = 50


class ExamplePluginApp:
    """A minimal window over the plugin's report."""

    def __init__(self, root: tk.Tk, options: LaunchOptions | None = None) -> None:
        """Build the window and pre-fill it from *options*.

        Args:
            root: The Tk root the launcher created.
            options: What the driver asked for; defaults to a bare launch.
        """
        self.root = root
        self.dry_run = False
        self.close_when_done = False
        self._running = False
        self._results: queue.SimpleQueue[tuple[list[str] | None, str | None]] = (
            queue.SimpleQueue()
        )
        root.title("Example Plugin")
        root.geometry("640x420")

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)

        self.folder = tk.StringVar(root)
        self.mode = tk.StringVar(root)

        row = ttk.Frame(frame)
        row.pack(fill="x")
        ttk.Label(row, text="Folder:").pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=self.folder).pack(
            side=tk.LEFT, fill="x", expand=True, padx=6
        )
        ttk.Button(row, text="Browse", command=self._browse).pack(side=tk.LEFT)
        self.run_button = ttk.Button(row, text="Run", command=self.start_run)
        self.run_button.pack(side=tk.LEFT, padx=6)
        ttk.Label(row, textvariable=self.mode).pack(side=tk.LEFT, padx=(6, 0))

        self.output = tk.Text(frame, height=16, wrap="word")
        self.output.pack(fill="both", expand=True, pady=(10, 0))

        self.apply_options(LaunchOptions() if options is None else options)

    def set_folder(self, value: str) -> None:
        """Put *value* in the folder entry.

        Every write to the entry goes through here — the argv pre-fill and the
        Browse button alike — so the two routes cannot drift apart.

        Args:
            value: The folder to show.
        """
        self.folder.set(value)

    def set_mode(self, dry_run: bool) -> None:
        """Show the run mode and remember it for the report header.

        Args:
            dry_run: True for the driver's ``--dry`` mode.
        """
        self.dry_run = dry_run
        self.mode.set("Dry Run" if dry_run else "Live Update")

    def apply_options(self, options: LaunchOptions) -> None:
        """Pre-fill the window from the driver's arguments.

        ``--start`` schedules the run instead of calling it, so the window is
        drawn before the worker starts and a launcher that closes on ``--end``
        never shows an empty frame.

        Args:
            options: The parsed launch arguments.
        """
        self.set_folder(options.directory)
        self.set_mode(options.dry_run)
        self.close_when_done = options.end
        if options.start:
            self.root.after(0, self.start_run)

    def start_run(self) -> None:
        """Start the report for the folder in the entry.

        The folder walk and the tag reads run on a worker thread so the window
        stays responsive; the widget writes happen only on the Tk thread, in
        :meth:`_finish`.  A click while a run is in flight is ignored, and an
        empty folder is reported instead of run.
        """
        if self._running:
            return
        folder = self.folder.get().strip()
        if not folder:
            self._write("Choose a folder first.\n")
            return
        self._running = True
        self.run_button.config(state="disabled")
        mode = "dry run" if self.dry_run else "live"
        self.output.delete("1.0", tk.END)
        self._write(f"Example Tool ({mode}) — {folder}\n")
        threading.Thread(target=self._collect, args=(folder,), daemon=True).start()
        self.root.after(_POLL_INTERVAL_MS, self._poll)

    def _collect(self, folder: str) -> None:
        """Build the report on a worker thread and post the outcome.

        No widget and no Tk call happens here — not even ``root.after``, which
        raises ``RuntimeError: main thread is not in main loop`` when a worker
        calls it.  The result goes on the queue that :meth:`_poll` reads.

        Args:
            folder: The folder to summarise.
        """
        try:
            lines = summarise(folder)
        except Exception as exc:  # a plugin must not die on one bad folder
            self._results.put((None, f"{type(exc).__name__}: {exc}"))
        else:
            self._results.put((lines, None))

    def _poll(self) -> None:
        """Deliver a finished run on the Tk thread, or look again shortly."""
        try:
            lines, error = self._results.get_nowait()
        except queue.Empty:
            self.root.after(_POLL_INTERVAL_MS, self._poll)
            return
        self._finish(lines, error)

    def _finish(self, lines: list[str] | None, error: str | None) -> None:
        """Render a finished run and close the window if it was asked to.

        ``--end`` closes a run that produced a report.  A failed run keeps the
        window open: closing would hide the one line saying what went wrong,
        and the driver's process would exit with no output at all.

        Args:
            lines: The report lines, or None when the run failed.
            error: A one-line failure description, or None on success.
        """
        self._running = False
        self.run_button.config(state="normal")
        if error is not None:
            self._write(f"Error: {error}\n")
            return
        for line in lines or []:
            self._write(f"  {line}\n")
        if self.close_when_done:
            self.root.destroy()

    def _write(self, text: str) -> None:
        """Append *text* to the output pane.

        Args:
            text: The text to append.
        """
        self.output.insert(tk.END, text)

    def _browse(self) -> None:
        """Ask for a folder and put it in the entry."""
        chosen = filedialog.askdirectory(parent=self.root)
        if chosen:
            self.set_folder(chosen)


def main(argv: Sequence[str] | None = None) -> None:
    """Open the window with the driver's arguments applied.

    Args:
        argv: The arguments after the script name; defaults to ``sys.argv[1:]``.
    """
    options = parse_launch_args(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    ExamplePluginApp(root, options)
    root.mainloop()
