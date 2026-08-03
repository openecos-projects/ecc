import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data.candidate_input_binding import (
    CandidateInputBindingError,
    bind_candidate_input,
    reapply_candidate_input_binding,
)
from chipcompiler.data.workspace.layout import EccOutput, EccStep, StepInput


def _sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


class _Flow:
    def __init__(self, *steps):
        self._steps = {step.name: step for step in steps}

    def get_workspace_step(self, name):
        return self._steps.get(name)


def _step(tmp_path: Path, name: str):
    output_dir = tmp_path / f"{name}_ecc" / "output"
    output_dir.mkdir(parents=True)
    def_path = output_dir / f"gcd_{name}.def.gz"
    verilog_path = output_dir / f"gcd_{name}.v.gz"
    db_path = output_dir / f"gcd_{name}_db"
    def_path.write_text(f"DEF {name}\n", encoding="utf-8")
    verilog_path.write_text(f"VERILOG {name}\n", encoding="utf-8")
    db_path.mkdir()
    (db_path / "manifest").write_text(f"DB {name}\n", encoding="utf-8")
    return SimpleNamespace(
        name=name,
        input={"def": None, "verilog": None, "db": None},
        output={"def": def_path, "verilog": verilog_path, "db": db_path},
    )


def test_bind_and_reapply_cts_from_legalization_uses_checkpoint_outputs(tmp_path):
    cts = _step(tmp_path, "CTS")
    legalization = _step(tmp_path, "legalization")
    flow = _Flow(cts, legalization)
    workspace = SimpleNamespace(directory=str(tmp_path), design=SimpleNamespace())

    receipt = bind_candidate_input(
        workspace,
        flow,
        "CTS",
        "legalization",
        candidate_id="cts-rerun-001",
    )

    receipt_path = tmp_path / "analysis" / "candidate_input_binding.v1.json"
    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt == persisted
    assert receipt["schema"] == "ecc.workspace.candidate_input_binding.v1"
    assert receipt["schema_version"] == 1
    assert receipt["candidate_id"] == "cts-rerun-001"
    assert receipt["target_step"] == "CTS"
    assert receipt["target"] == {"step": "CTS"}
    assert receipt["source"] == {"step": "legalization"}
    assert receipt["inputs"]["def"] == {
        "ref": "legalization_ecc/output/gcd_legalization.def.gz",
        "sha256": _sha256(legalization.output["def"]),
    }

    cts.input = {"def": Path("stale.def"), "verilog": Path("stale.v"), "db": Path("stale_db")}
    assert reapply_candidate_input_binding(workspace, flow, "route") is None
    assert cts.input["def"] == Path("stale.def")

    applied = reapply_candidate_input_binding(workspace, flow, "CTS")

    assert applied["inputs"]["def"]["sha256"] == _sha256(legalization.output["def"])
    assert cts.input == legalization.output


def test_bind_candidate_input_reads_typed_ecc_output_paths(tmp_path):
    cts = EccStep(name="CTS", input=StepInput())
    legalization_output = _step(tmp_path, "legalization").output
    legalization = EccStep(
        name="legalization",
        output=EccOutput(
            dir=legalization_output["db"],
            def_=legalization_output["def"],
            verilog=legalization_output["verilog"],
            db=legalization_output["db"],
        ),
    )
    workspace = SimpleNamespace(directory=str(tmp_path), design=SimpleNamespace())

    bind_candidate_input(
        workspace,
        _Flow(cts, legalization),
        "CTS",
        "legalization",
        candidate_id="cts-rerun-typed-output",
    )

    assert cts.input.def_ == legalization_output["def"]
    assert cts.input.verilog == legalization_output["verilog"]
    assert cts.input.db == legalization_output["db"]


@pytest.mark.parametrize(
    "target_step,source_step",
    [
        ("Floorplan", "initial"),
        ("fixFanout", "Floorplan"),
        ("place", "fixFanout"),
        ("CTS", "place"),
        ("legalization", "CTS"),
        ("route", "legalization"),
        ("place", "CTS"),
        ("legalization", "place"),
        ("CTS", "legalization"),
    ],
)
def test_canonical_candidate_input_edges_are_declared(tmp_path, target_step, source_step):
    source = _step(tmp_path, source_step) if source_step != "initial" else None
    target = _step(tmp_path, target_step)
    origin_def = tmp_path / "origin.def"
    origin_verilog = tmp_path / "origin.v"
    origin_def.write_text("DEF initial\n", encoding="utf-8")
    origin_verilog.write_text("VERILOG initial\n", encoding="utf-8")
    workspace = SimpleNamespace(
        directory=str(tmp_path),
        design=SimpleNamespace(origin_def=origin_def, origin_verilog=origin_verilog),
    )
    flow = _Flow(target, *([] if source is None else [source]))

    receipt = bind_candidate_input(
        workspace,
        flow,
        target_step,
        source_step,
        candidate_id=f"{target_step}-candidate",
    )

    assert receipt["target"] == {"step": target_step}
    assert receipt["source"] == {"step": source_step}


def test_noncanonical_candidate_edge_is_rejected(tmp_path):
    cts = _step(tmp_path, "CTS")
    route = _step(tmp_path, "route")
    workspace = SimpleNamespace(directory=str(tmp_path), design=SimpleNamespace())

    with pytest.raises(CandidateInputBindingError):
        bind_candidate_input(
            workspace,
            _Flow(cts, route),
            "CTS",
            "route",
            candidate_id="invalid-edge",
        )


def test_filler_candidate_binding_is_rejected(tmp_path):
    filler = _step(tmp_path, "filler")
    drc = _step(tmp_path, "drc")
    workspace = SimpleNamespace(directory=str(tmp_path), design=SimpleNamespace())

    with pytest.raises(CandidateInputBindingError):
        bind_candidate_input(
            workspace,
            _Flow(filler, drc),
            "filler",
            "drc",
            candidate_id="filler-candidate",
        )


@pytest.mark.parametrize("candidate_id", ["", "bad id", "../candidate"])
def test_binding_rejects_invalid_candidate_id(tmp_path, candidate_id):
    cts = _step(tmp_path, "CTS")
    legalization = _step(tmp_path, "legalization")
    workspace = SimpleNamespace(directory=str(tmp_path), design=SimpleNamespace())

    with pytest.raises(CandidateInputBindingError):
        bind_candidate_input(
            workspace,
            _Flow(cts, legalization),
            "CTS",
            "legalization",
            candidate_id=candidate_id,
        )
