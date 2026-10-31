"""restoration — reconstruct audio that a converter, limiter or master damaged.

The suite already repairs noise (``noise_reduction``) and clicks
(``pop_click_remover``); this package holds the repairs that reconstruct
*content* rather than attenuating it.  Sub-items ship separately
(``PLAN_functional_backlog.md`` F-08):

* **F-08a — declip** (this package today): find flat-topped runs at full scale
  and interpolate the peak they lost back.
* **F-08b — de-reverb**: deliberately not started; the plan's §7 question — is a
  music-grade result achievable — is re-evaluated against declip's measurements,
  and its acceptance needs a synthetic room impulse response the suite does not
  build yet.
* **F-08c — spectral repair**: needs an interactive time/frequency selection
  surface, and the plan gates it behind a and b having a measured baseline.

Changed in 2.2.3: initial package with the declip engine (item F-08a).

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

__all__ = ["__version__"]

#: Informational only; the suite version is ``audio_suite_shared.project_version``.
__version__ = "1.0.0"
