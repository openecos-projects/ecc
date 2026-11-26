"""Tests for publishing retained optimization candidates as managed Workspaces."""

import json
from pathlib import Path
from uuid import uuid4

from agent.delivery import publish_retained_candidate
from chipcompiler.data.handshake import (
    load_request,
    load_response,
    write_request,
    write_response,
)
from chipcompiler.data.handshake.messages import (
    DesignFiles,
    ResponseStatus,
    StepInputs,
    StepRequest,
    StepResponse,
)
from chipcompiler.data.workspace.config_manifest import modified_derived_configs
from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.project.runtime_processes import default_log_path, require_unused_run_id
from test.conftest import create_minimal_ics55_pdk


def _workspace_spec_fixture(tmp_path: Path):
    fixture = Path(__file__).parents[2] / "test" / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = payload["workspaceBindings"]
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(create_minimal_ics55_pdk(tmp_path / "pdk"))
    return payload["workspaceSpec"], bindings


def test_retained_candidate_starts_with_its_own_run_history(tmp_path):
    spec, bindings = _workspace_spec_fixture(tmp_path)
    source = tmp_path / "source"
    create_workspace_from_spec(source, spec, bindings)
    run_id, interrupted_id = str(uuid4()), str(uuid4())
    history = [
        Path(default_log_path(run_id)),
        Path("log") / f"{run_id}.run.json",
        Path(default_log_path(interrupted_id)),
    ]
    for path in history:
        (source / path).write_text("source run", encoding="utf-8")

    target = tmp_path / "retained"
    publish_retained_candidate(source, target, retained_candidate_sha256="sha256:" + "a" * 64)

    assert all((source / path).is_file() for path in history)
    assert not any((target / path).exists() for path in history)
    require_unused_run_id(target, run_id)
    require_unused_run_id(target, interrupted_id)


def test_retained_workspace_rebases_inherited_paths(tmp_path):
    spec, bindings = _workspace_spec_fixture(tmp_path)
    parent = tmp_path / "baseline"
    group = parent / ".agent" / "candidates"
    earlier = group / "earlier"
    candidate = group / "current"
    create_workspace_from_spec(candidate, spec, bindings)
    step = candidate / "01_synthesis_yosys"
    step.mkdir(exist_ok=True)
    netlist = step / "result.v"
    netlist.write_text("module gcd; endmodule\n")
    old_netlist = netlist.relative_to(candidate)
    request_path = write_request(
        StepRequest(
            workspace_directory=earlier,
            step="synthesis",
            tool="yosys",
            step_directory=step.name,
            attempt_id="step-attempt-derived",
            inputs=StepInputs(
                design=DesignFiles(verilog=parent / old_netlist),
                spef=(tmp_path / "baseline-other" / "external.spef",),
            ),
            design_source=None,
            upstream={},
            final_step=False,
            layout_image=False,
        )
    )
    request_path.rename(step / request_path.name)
    write_response(
        step,
        StepResponse(
            step="synthesis",
            tool="yosys",
            attempt_id="step-attempt-derived",
            status=ResponseStatus.SUCCESS,
            design=DesignFiles(verilog=earlier / old_netlist),
            design_states=frozenset(),
            outputs={},
            design_source=None,
            upstream={},
            warnings=frozenset(),
        ),
    )

    target = tmp_path / "retained"
    publish_retained_candidate(
        candidate,
        target,
        parent_workspace_directory=parent,
        retained_candidate_sha256="sha256:" + "a" * 64,
    )
    parent.rename(tmp_path / "moved-baseline")

    request = load_request(target / step.name)
    response = load_response(target / step.name)
    assert request.workspace_directory == target
    assert request.inputs.design.verilog == target / old_netlist
    assert request.inputs.spef == (tmp_path / "baseline-other" / "external.spef",)
    assert response is not None
    verilog = response.design.verilog
    assert verilog is not None
    assert verilog == target / old_netlist
    assert verilog.read_bytes() == b"module gcd; endmodule\n"


def test_retained_candidate_updates_relocated_config_baselines_and_tcl_paths(tmp_path):
    spec, bindings = _workspace_spec_fixture(tmp_path)
    parent = tmp_path / "baseline"
    group = parent / ".agent" / "candidates"
    earlier = group / "earlier"
    candidate = group / "current"
    create_workspace_from_spec(candidate, spec, bindings)
    assert modified_derived_configs(candidate) == []

    script_dir = candidate / "01_synthesis_yosys" / "script"
    script_dir.mkdir(parents=True, exist_ok=True)
    global_var = script_dir / "global_var.tcl"
    external_keep = tmp_path / "baseline-other" / "keep.tcl"
    global_var.write_text(
        "\n".join(
            [
                f"set WORKSPACE {candidate}",
                f"set EARLIER_OUT {earlier}/01_synthesis_yosys/result.v",
                f"set PARENT_OUT {parent}/01_synthesis_yosys/parent.v",
                f"set EXTERNAL {external_keep}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    evidence_rel = Path("01_synthesis_yosys") / "script" / "evidence.tcl"
    evidence_bytes = f"set EVIDENCE {candidate}/01_synthesis_yosys/result.v\n".encode()
    (candidate / evidence_rel).write_bytes(evidence_bytes)

    target = tmp_path / "retained"
    publish_retained_candidate(
        candidate,
        target,
        parent_workspace_directory=parent,
        original_evidence=frozenset({evidence_rel}),
        retained_candidate_sha256="sha256:" + "a" * 64,
    )

    assert modified_derived_configs(target) == []
    db_text = (target / "config" / "db_ecc.json").read_text(encoding="utf-8")
    assert str(candidate) not in db_text
    assert str(target) in db_text

    relocated_tcl = (target / "01_synthesis_yosys" / "script" / "global_var.tcl").read_text(
        encoding="utf-8"
    )
    assert f"set WORKSPACE {target}" in relocated_tcl
    assert f"set EARLIER_OUT {target}/01_synthesis_yosys/result.v" in relocated_tcl
    assert f"set PARENT_OUT {target}/01_synthesis_yosys/parent.v" in relocated_tcl
    assert f"set EXTERNAL {external_keep}" in relocated_tcl
    assert str(candidate) not in relocated_tcl
    assert (target / evidence_rel).read_bytes() == evidence_bytes


def test_retained_candidate_preserves_hand_edited_config_status(tmp_path):
    spec, bindings = _workspace_spec_fixture(tmp_path)
    candidate = tmp_path / "baseline" / ".agent" / "candidates" / "edited"
    create_workspace_from_spec(candidate, spec, bindings)
    assert modified_derived_configs(candidate) == []

    floorplan = candidate / "config" / "floorplan_ecc.json"
    floorplan.write_text(floorplan.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    assert modified_derived_configs(candidate) == ["floorplan_ecc.json"]

    target = tmp_path / "retained-edited"
    publish_retained_candidate(
        candidate,
        target,
        retained_candidate_sha256="sha256:" + "b" * 64,
    )

    assert modified_derived_configs(target) == ["floorplan_ecc.json"]
