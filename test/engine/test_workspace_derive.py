import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from chipcompiler.engine import create_workspace_from_spec
from chipcompiler.engine.workspace.derive import derive_workspace
from chipcompiler.engine.workspace.lifecycle import WorkspaceLifecycleError
from chipcompiler.project.runtime_processes import default_log_path, require_unused_run_id


def test_derive_rejects_existing_target(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path)

    assert excinfo.value.code == "workspace_exists"


def test_derive_rejects_source_without_engineering_snapshot(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, tmp_path / "target")

    assert excinfo.value.code == "workspace_invalid"


def test_derive_rejects_target_inside_source(tmp_path):
    source = tmp_path / "source"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")

    with pytest.raises(WorkspaceLifecycleError) as excinfo:
        derive_workspace(source, source / "nested" / "target")

    assert excinfo.value.code == "workspace_invalid"
    assert not (source / "nested").exists()


def test_derive_no_wait_leaves_no_target_lock_when_source_busy(tmp_path):
    fcntl = pytest.importorskip("fcntl")
    # "child" sorts before "probe", so a sorted acquisition would create the
    # target lock file before discovering the busy source lock.
    source = tmp_path / "probe"
    (source / "home").mkdir(parents=True)
    (source / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "child"

    with (tmp_path / "probe.lock").open("a") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX)
        with pytest.raises(BlockingIOError):
            derive_workspace(source, target, blocking=False)

    assert not (tmp_path / "child.lock").exists()
    assert not target.exists()


def test_derive_sweeps_stale_staging_siblings(tmp_path, minimal_ics55_pdk_factory):
    fixture = Path(__file__).parents[1] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = deepcopy(payload["workspaceBindings"])
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    source = tmp_path / "source"
    create_workspace_from_spec(source, payload["workspaceSpec"], bindings)
    stale = tmp_path / ".branch.staging-crashed"
    (stale / "home").mkdir(parents=True)
    (stale / "home" / "engineering-snapshot.json").write_text("{}", encoding="utf-8")
    Path(f"{stale}.lock").write_text("", encoding="utf-8")
    target = tmp_path / "branch"

    derived = derive_workspace(source, target)

    assert derived is not None
    assert target.is_dir()
    assert not stale.exists()
    assert not Path(f"{stale}.lock").exists()


@pytest.mark.parametrize("retained_digest", ["", "sha256:" + "a" * 64])
def test_derived_workspace_starts_with_its_own_run_history(
    tmp_path, minimal_ics55_pdk_factory, retained_digest
):
    fixture = Path(__file__).parents[1] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = payload["workspaceBindings"]
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    source = tmp_path / "source"
    create_workspace_from_spec(source, payload["workspaceSpec"], bindings)
    run_id, interrupted_id = str(uuid4()), str(uuid4())
    history = [
        Path(default_log_path(run_id)),
        Path("log") / f"{run_id}.run.json",
        Path(default_log_path(interrupted_id)),
    ]
    for path in history:
        (source / path).write_text("source run", encoding="utf-8")

    target = tmp_path / "derived"
    derive_workspace(source, target, retained_candidate_sha256=retained_digest)

    assert all((source / path).is_file() for path in history)
    assert not any((target / path).exists() for path in history)
    require_unused_run_id(target, run_id)
    require_unused_run_id(target, interrupted_id)


def test_retained_workspace_rebases_inherited_paths(tmp_path, minimal_ics55_pdk_factory):
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

    fixture = Path(__file__).parents[1] / "fixtures" / "workspace_spec" / "valid.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    bindings = payload["workspaceBindings"]
    bindings["inputs"] = {
        key: str(fixture.parent / value) for key, value in bindings["inputs"].items()
    }
    bindings["pdk"]["root"] = str(minimal_ics55_pdk_factory(tmp_path / "pdk"))
    parent = tmp_path / "baseline"
    group = parent / ".agent" / "candidates"
    earlier = group / "earlier"
    candidate = group / "current"
    create_workspace_from_spec(candidate, payload["workspaceSpec"], bindings)
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
    derive_workspace(
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
