"""Locks for plugin slots, chain validation and saved state (F-M1 order #1).

A chain is what a preset stores and what a render will apply, so the locks here
are about failure being *early* and *readable*: a plugin that is no longer
installed, or state saved before a plugin update, must fail validation — before
the worker exists — and the message must name the plugin, never the folder it
used to live in.  A chain summary travels into a run report, so a path in it
would publish the user's disk layout.

The state round-trip is proven twice: in-process through the preset document,
and again in a fresh interpreter, because "reloads in a fresh process" is the
acceptance the plan asks for and a same-process decode cannot show it.

The bit-transparency half of the bypass acceptance lands with the worker
(F-M1 order #2): order #1 proves the chain excludes bypassed slots from the
render list, and there is no renderer here to measure.

Changed in 3.0.0: new file — the slot, chain, validation and state locks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from audio_suite_shared.plugin_host.chain import (
    CHAIN_PRESET_VERSION,
    ChainPresetError,
    ChainValidationError,
    PluginChain,
    PluginSlot,
)
from audio_suite_shared.plugin_host.scan import (
    PluginMetadata,
    PluginParameter,
    ScanResult,
    ScanRoot,
    scan,
)
from audio_suite_shared.plugin_host.state import (
    STATE_FORMAT_VERSION,
    PluginStateBlob,
    PluginStateError,
    PluginStateMismatch,
    capture_state,
    require_compatible,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundle(root: Path, name: str) -> Path:
    """Create a VST3 bundle tree holding one dummy binary.

    Parameters
    ----------
    root : Path
        Folder the bundle lives in.
    name : str
        Bundle name, without the suffix.

    Returns
    -------
    Path
        The bundle directory.
    """
    bundle = root / f"{name}.vst3"
    binary = bundle / "Contents" / "x86_64-win" / f"{name}.vst3"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"\x00VST3" + name.encode("ascii"))
    return bundle


def _loader(version: str = "1.0.0") -> Callable[[Path], PluginMetadata]:
    """Return a metadata loader that reports one stable plugin identity.

    Parameters
    ----------
    version : str
        Version every bundle reports.

    Returns
    -------
    Callable[[Path], PluginMetadata]
        The loader, usable as ``scan(..., loader=...)``.
    """

    def load(bundle: Path) -> PluginMetadata:
        return PluginMetadata(
            name=f"{bundle.stem} Pro",
            vendor="Fixture Audio",
            category="Fx",
            version=version,
            parameters=(PluginParameter(name="Mix", value=0.5),),
        )

    return load


@pytest.fixture
def scanned(tmp_path: Path) -> tuple[Path, ScanResult]:
    """Return a plugin folder and the scan of it.

    Returns
    -------
    tuple[Path, ScanResult]
        The folder and its records.
    """
    root = tmp_path / "plugins"
    _bundle(root, "Alpha")
    _bundle(root, "Beta")
    return root, scan(
        [ScanRoot(str(root))],
        loader=_loader(),
        cache_path=tmp_path / "cache.json",
    )


class TestPluginSlot:
    """A slot refuses data that could not identify a plugin."""

    def test_defaults_are_a_plain_active_slot(self, tmp_path: Path) -> None:
        slot = PluginSlot(str(tmp_path / "Alpha.vst3"))

        assert slot.state is None
        assert slot.bypass is False
        assert dict(slot.parameter_overrides) == {}
        assert slot.plugin_name == "Alpha"

    def test_an_empty_path_is_refused(self) -> None:
        with pytest.raises(ValueError, match="path of a scanned plugin"):
            PluginSlot("   ")

    def test_a_non_blob_state_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError, match="PluginStateBlob"):
            PluginSlot(str(tmp_path / "Alpha.vst3"), state=b"raw")  # type: ignore[arg-type]

    def test_a_non_boolean_bypass_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(TypeError, match="True or False"):
            PluginSlot(str(tmp_path / "Alpha.vst3"), bypass="yes")  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), "loud"])
    def test_an_override_that_is_not_finite_is_refused(
        self, tmp_path: Path, value: object
    ) -> None:
        with pytest.raises(ValueError, match="parameter override"):
            PluginSlot(
                str(tmp_path / "Alpha.vst3"),
                parameter_overrides={"Mix": value},  # type: ignore[dict-item]
            )

    def test_an_override_without_a_name_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="needs a parameter name"):
            PluginSlot(str(tmp_path / "Alpha.vst3"), parameter_overrides={" ": 1.0})

    def test_overrides_are_stored_as_floats_and_cannot_be_edited_in_place(
        self, tmp_path: Path
    ) -> None:
        slot = PluginSlot(str(tmp_path / "Alpha.vst3"), parameter_overrides={"Mix": 1})

        assert slot.parameter_overrides["Mix"] == 1.0
        with pytest.raises(TypeError):
            slot.parameter_overrides["Mix"] = 2.0  # type: ignore[index]


class TestBypass:
    """A bypassed slot is not in the render list."""

    def test_active_slots_leave_bypassed_ones_out(self, tmp_path: Path) -> None:
        active = PluginSlot(str(tmp_path / "Alpha.vst3"))
        bypassed = PluginSlot(str(tmp_path / "Beta.vst3"), bypass=True)
        chain = PluginChain((active, bypassed))

        assert chain.active_slots() == (active,)
        assert chain.all_bypassed() is False
        assert chain.describe() == "Alpha (active), Beta (bypassed)"

    def test_a_fully_bypassed_chain_has_nothing_to_render(self, tmp_path: Path) -> None:
        chain = PluginChain(
            (
                PluginSlot(str(tmp_path / "Alpha.vst3"), bypass=True),
                PluginSlot(str(tmp_path / "Beta.vst3"), bypass=True),
            )
        )

        assert chain.active_slots() == ()
        assert chain.all_bypassed() is True

    def test_an_empty_chain_is_not_bypassed_and_has_no_plugins(self) -> None:
        chain = PluginChain()

        assert chain.all_bypassed() is False
        assert chain.active_slots() == ()
        assert chain.describe() == "no plugins"


class TestValidation:
    """Every slot resolves against a scan, before anything renders."""

    def test_a_scanned_chain_is_valid(self, scanned: tuple[Path, ScanResult]) -> None:
        root, result = scanned
        chain = PluginChain(
            (
                PluginSlot(str(root / "Alpha.vst3")),
                PluginSlot(str(root / "Beta.vst3"), bypass=True),
            )
        )

        validation = chain.validate(result)

        assert validation.ok is True
        assert validation.problems == ()
        assert validation.describe() == "plugin chain: no problems"
        validation.raise_if_invalid()

    def test_a_removed_plugin_is_reported_by_validation(
        self, scanned: tuple[Path, ScanResult], tmp_path: Path
    ) -> None:
        root, _result = scanned
        chain = PluginChain((PluginSlot(str(root / "Beta.vst3")),))
        for directory in (
            root / "Beta.vst3" / "Contents" / "x86_64-win",
            root / "Beta.vst3" / "Contents",
            root / "Beta.vst3",
        ):
            for file in directory.iterdir():
                file.unlink()
            directory.rmdir()
        rescanned = scan([ScanRoot(str(root))], cache_path=tmp_path / "fresh.json")

        validation = chain.validate(rescanned)

        assert validation.ok is False
        assert validation.problems[0].plugin == "Beta"
        assert "not installed" in validation.problems[0].reason
        assert str(root) not in validation.describe()

    def test_a_missing_plugin_raises_one_error_naming_every_problem(
        self, tmp_path: Path
    ) -> None:
        chain = PluginChain(
            (
                PluginSlot(str(tmp_path / "Gone.vst3")),
                PluginSlot(str(tmp_path / "AlsoGone.vst3")),
            )
        )

        with pytest.raises(ChainValidationError) as raised:
            chain.validate(ScanResult((), "key", False)).raise_if_invalid()

        assert len(raised.value.problems) == 2
        assert "Gone" in str(raised.value)
        assert str(tmp_path) not in str(raised.value)

    def test_an_unreadable_metadata_record_refuses_the_slot(
        self, tmp_path: Path
    ) -> None:
        root = tmp_path / "plugins"
        _bundle(root, "Alpha")

        def refusing(_bundle_path: Path) -> PluginMetadata:
            raise RuntimeError("nope")

        result = scan(
            [ScanRoot(str(root))],
            loader=refusing,
            cache_path=tmp_path / "cache.json",
        )
        chain = PluginChain((PluginSlot(str(root / "Alpha.vst3")),))

        validation = chain.validate(result)

        assert validation.ok is False
        assert validation.problems[0].plugin == "Alpha"
        assert "metadata could not be read: RuntimeError" in validation.describe()


class TestStateIsVersioned:
    """A saved state is refused when the plugin or its version changed."""

    def test_a_state_round_trips_with_its_payload(
        self, scanned: tuple[Path, ScanResult]
    ) -> None:
        _root, result = scanned
        record = result.records[0]
        blob = capture_state(record, b"\x00state\xff")

        decoded = PluginStateBlob.decode(blob.encode())

        assert decoded == blob
        assert decoded.payload == b"\x00state\xff"
        assert decoded.format_version == STATE_FORMAT_VERSION
        assert self._text_is_ascii(blob.encode())

    def test_the_state_compares_the_path_independent_identity(
        self, scanned: tuple[Path, ScanResult]
    ) -> None:
        root, result = scanned
        record = result.record_for(root / "Alpha.vst3")
        assert record is not None

        require_compatible(capture_state(record, b""), record)

        with pytest.raises(PluginStateMismatch) as raised:
            require_compatible(
                PluginStateBlob(
                    plugin="Someone Else/Beta Pro", version="", payload=b""
                ),
                record,
            )

        assert "Someone Else/Beta Pro" in str(raised.value)
        assert "Alpha Pro" in str(raised.value)

    def test_a_version_change_is_reported_at_validation(
        self, scanned: tuple[Path, ScanResult], tmp_path: Path
    ) -> None:
        root, result = scanned
        record = result.record_for(root / "Alpha.vst3")
        assert record is not None
        chain = PluginChain(
            (PluginSlot(str(root / "Alpha.vst3"), state=capture_state(record, b"x")),)
        )
        updated = scan(
            [ScanRoot(str(root))],
            loader=_loader("2.0.0"),
            cache_path=tmp_path / "updated.json",
        )

        validation = chain.validate(updated)

        assert validation.ok is False
        assert "saved at version 1.0.0" in validation.describe()
        assert "version 2.0.0 is installed" in validation.describe()

    def test_the_state_document_refuses_another_format(self) -> None:
        text = json.dumps({"format": 99, "plugin": "A/B", "state": "", "version": "1"})

        with pytest.raises(PluginStateError, match="format 99"):
            PluginStateBlob.decode(text)

    def test_the_state_document_refuses_non_base64_payload(self) -> None:
        text = json.dumps(
            {"format": 1, "plugin": "A/B", "state": "not base64!", "version": "1"}
        )

        with pytest.raises(PluginStateError, match="not base64"):
            PluginStateBlob.decode(text)

    @pytest.mark.parametrize(
        "text",
        [
            "{not json",
            "[]",
            json.dumps({"format": 1, "state": "", "version": "1"}),
            json.dumps({"format": 1, "plugin": "A/B", "state": ""}),
        ],
    )
    def test_the_state_document_refuses_an_incomplete_document(self, text: str) -> None:
        with pytest.raises(PluginStateError):
            PluginStateBlob.decode(text)

    @staticmethod
    def _text_is_ascii(text: str) -> bool:
        """Return whether *text* is pure ASCII, as a preset field must be."""
        return text.isascii()


class TestPresetRoundTrip:
    """The preset keeps the chain, its state and its overrides exactly."""

    def test_a_chain_survives_json_unchanged(
        self, scanned: tuple[Path, ScanResult]
    ) -> None:
        root, result = scanned
        record = result.record_for(root / "Alpha.vst3")
        assert record is not None
        chain = PluginChain(
            (
                PluginSlot(
                    str(root / "Alpha.vst3"),
                    state=capture_state(record, b"plugin-state"),
                    parameter_overrides={"Mix": 0.75},
                ),
                PluginSlot(str(root / "Beta.vst3"), bypass=True),
            )
        )

        restored = PluginChain.from_preset(json.loads(json.dumps(chain.to_preset())))

        assert restored == chain
        assert restored.slots[0].state is not None
        assert restored.slots[0].state.payload == b"plugin-state"
        assert restored.slots[0].parameter_overrides["Mix"] == 0.75
        assert restored.slots[1].bypass is True

    def test_a_fresh_process_reads_the_saved_state(
        self, scanned: tuple[Path, ScanResult]
    ) -> None:
        root, result = scanned
        record = result.record_for(root / "Alpha.vst3")
        assert record is not None
        preset = PluginChain(
            (
                PluginSlot(
                    str(root / "Alpha.vst3"),
                    state=capture_state(record, b"fresh-process-state"),
                ),
            )
        ).to_preset()
        source = (
            "import json\n"
            "from audio_suite_shared.plugin_host import PluginChain\n"
            f"preset = json.loads({json.dumps(preset)!r})\n"
            "chain = PluginChain.from_preset(preset)\n"
            "slot = chain.slots[0]\n"
            "assert slot.state is not None\n"
            "print(slot.state.payload.hex())\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)

        completed = subprocess.run(  # noqa: S603
            [sys.executable, "-B", "-c", source],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == b"fresh-process-state".hex()

    def test_an_empty_chain_is_an_empty_preset(self) -> None:
        preset = PluginChain().to_preset()

        assert preset == {"version": CHAIN_PRESET_VERSION, "slots": []}
        assert PluginChain.from_preset(preset) == PluginChain()


class TestPresetRefusals:
    """A preset the suite did not write is refused with a reason."""

    @pytest.mark.parametrize(
        ("preset", "message"),
        [
            ([], "must be an object"),
            ({"version": 99, "slots": []}, "uses version 99"),
            ({"version": CHAIN_PRESET_VERSION, "slots": None}, "list of slots"),
            ({"version": CHAIN_PRESET_VERSION, "slots": [1]}, "is not an object"),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "colour": "red"}],
                },
                "unknown key",
            ),
            (
                {"version": CHAIN_PRESET_VERSION, "slots": [{"plugin": "  "}]},
                "names no plugin",
            ),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "bypass": "yes"}],
                },
                "bypass",
            ),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "parameters": [1]}],
                },
                "parameters that are not an object",
            ),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "parameters": {"Mix": "loud"}}],
                },
                "not a number",
            ),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "state": 1}],
                },
                "state that is not text",
            ),
            (
                {
                    "version": CHAIN_PRESET_VERSION,
                    "slots": [{"plugin": "A", "state": "{not json"}],
                },
                "unreadable state",
            ),
        ],
    )
    def test_a_malformed_preset_is_refused(self, preset: object, message: str) -> None:
        with pytest.raises(ChainPresetError, match=message):
            PluginChain.from_preset(preset)  # type: ignore[arg-type]
