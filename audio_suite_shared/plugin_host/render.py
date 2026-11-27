"""render.py — apply a chain's slots to a decoded buffer, in order.

This is the half of rendering that needs no plugin: given a chain, a
``(channels, frames)`` float32 buffer and a way to turn a slot into an effect,
it applies the active slots in order and returns the result.  The worker
supplies the effect loader that loads a bundle; the tests supply a fake one.

Two properties are deliberate:

* **A chain with no active slot returns the caller's own array.**  Not a copy —
  the array itself.  That is what makes a fully bypassed chain bit-transparent:
  there is no conversion, no gain and no buffer in between that could round a
  sample.  A bypassed slot is skipped before its plugin is even loaded, so a
  broken plugin that is switched off cannot break the render.
* **An effect failure names the slot and the plugin, never the path.**  The
  error travels into a report, and a report must describe the plugin a user
  chose, not the folder layout of the machine that rendered it.

Changed in 3.0.0: new module — the ordered, bypass-aware render layer (F-M1
order-of-work #2).
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import numpy.typing as npt

from audio_suite_shared.plugin_host.chain import PluginChain, PluginSlot

#: One slot's effect: a float32 ``(channels, frames)`` buffer and the sample
#: rate, returning the processed buffer.
SlotEffect = Callable[[npt.NDArray[np.float32], float], npt.NDArray[np.float32]]

#: Turns one slot into its effect.  The worker's loader loads the bundle; a
#: test passes a fake.
EffectLoader = Callable[[PluginSlot], SlotEffect]


class PluginLoadError(ValueError):
    """A slot's plugin could not be prepared, for a reason safe to report.

    A loader raises this when the failure is ours to describe — a parameter the
    plugin does not have, a slot that names something other than a bundle.
    Anything else the loader or the plugin raises is reported by its exception
    type only, because a third-party message may carry the bundle's path.
    """

    def __init__(self, reason: str) -> None:
        """Build the error from its path-free reason.

        Parameters
        ----------
        reason : str
            One clause naming what is wrong, with no filesystem path in it.
        """
        super().__init__(reason)
        self.reason = reason


class PluginRenderError(RuntimeError):
    """One slot could not be applied.

    Attributes
    ----------
    slot_index : int
        Zero-based position in the chain, so a user can point at the row.
    plugin : str
        The plugin's display name — never its path.
    reason : str
        One clause naming the failure, with no filesystem path in it.
    """

    def __init__(self, slot_index: int, plugin: str, reason: str) -> None:
        """Build the error from the slot it belongs to.

        Parameters
        ----------
        slot_index : int
            Zero-based position in the chain.
        plugin : str
            The plugin's display name.
        reason : str
            One clause naming the failure.
        """
        super().__init__(f"slot {slot_index} ({plugin}) could not be applied: {reason}")
        self.slot_index = slot_index
        self.plugin = plugin
        self.reason = reason


def render_buffer(
    chain: PluginChain,
    audio: npt.NDArray[np.float32],
    sample_rate: float,
    load: EffectLoader,
) -> npt.NDArray[np.float32]:
    """Apply *chain* to *audio* and return the processed buffer.

    Parameters
    ----------
    chain : PluginChain
        The chain, in render order.  Bypassed slots are skipped without their
        plugin being loaded.
    audio : npt.NDArray[np.float32]
        The decoded ``(channels, frames)`` buffer.  It is never modified.
    sample_rate : float
        The buffer's sample rate, passed to every effect.
    load : EffectLoader
        Resolves one slot to its effect.  Called once per active slot, in
        order.

    Returns
    -------
    npt.NDArray[np.float32]
        The processed buffer, or *audio* itself when no slot is active.

    Raises
    ------
    PluginRenderError
        A slot's effect could not be loaded or applied.  The message names the
        slot and the plugin, never the path.
    """
    output = audio
    for index, slot in enumerate(chain.slots):
        if slot.bypass:
            continue
        try:
            effect = load(slot)
            output = np.asarray(effect(output, float(sample_rate)), dtype=np.float32)
        except PluginRenderError:
            raise
        except Exception as exc:  # noqa: BLE001 - one slot must not abort the render
            # A plugin is third-party code: anything it raises is this slot's
            # failure.  Only our own reason survives; a foreign message may
            # carry the bundle path, so it is replaced by its type (F-M1 D-11).
            reason = (
                exc.reason if isinstance(exc, PluginLoadError) else type(exc).__name__
            )
            raise PluginRenderError(index, slot.plugin_name, reason) from exc
    return output
