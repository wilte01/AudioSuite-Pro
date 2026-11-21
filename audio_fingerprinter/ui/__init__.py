"""UI package for the Audio Fingerprinter tool.

Changed in 2.9.0: the Processing and Results tabs are the shell's, so this
package exports the Setup tab alone (C1 stage 2).
"""

from . import setup_tab

__all__ = ["setup_tab"]
