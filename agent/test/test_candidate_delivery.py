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
