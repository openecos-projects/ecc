import json
import os
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.data.candidate_materialization import materialize_candidate_config
from agent.engine import AgentEngineFlow
from agent.floorplan_mode import prepare_floorplan_mode
from agent.requests import CandidateRerunRequest
from chipcompiler.data import StateEnum, Workspace
from chipcompiler.data.parameter import Parameters, save_parameter
from chipcompiler.data.workspace import Flow
from chipcompiler.data.workspace.step_handshake import write_request
from chipcompiler.engine.step_request import build_step_request
from chipcompiler.engine.step_subprocess import run_step_worker


def _new_flow(workspace, names):
    flow = AgentEngineFlow(workspace)
    workspace.flow.data = {
        "steps": [flow.init_flow_step(name, "ecc", StateEnum.Unstart) for name in names]
    }
    assert flow.save()
    return flow


def _write_parameters(root):
    parameters = Parameters(
        path=root / "home" / "params.toml",
        data={"design": "example", "top_module": "example", "pdk": "ics55", "clock": "clk"},
    )
    assert save_parameter(parameters)
    return parameters


def _flow_path(workspace):
    path = workspace.flow.path
    assert path is not None
    return path


def _write_request(flow, step_name: str, attempt_id: str) -> dict:
    """Write the step's req.json as the parent does; return the worker payload."""
    step = flow.get_workspace_step(step_name)
    assert step is not None
    request = build_step_request(
        Path(flow.workspace.directory),
        flow.workspace.flow.steps(),
        step,
        attempt_id=attempt_id,
        layout_image=False,
    )
    write_request(request)
    return {"step_directory": str(request.directory), "attempt_id": attempt_id}


def test_agent_worker_runs_the_persisted_drc_step_from_its_request(monkeypatch, tmp_path):
    root = tmp_path / ".agent" / "candidates" / "candidate-1"
    (root / "home").mkdir(parents=True)
    workspace = Workspace(directory=root, flow=Flow(path=root / "home" / "flow.json"))
    workspace.parameters = _write_parameters(root)
    parent_flow = _new_flow(workspace, ("filler", "drc"))
    parent_flow.create_step_workspaces(initialize_config=False)
    payload = _write_request(parent_flow, "drc", "attempt-drc")
    drc = parent_flow.get_workspace_step("drc")
    assert drc is not None
    before = _flow_path(workspace).read_bytes()
    created = []

    def flow_factory(workspace):
        flow = AgentEngineFlow(workspace)
        created.append(flow)
        return flow

    def initialize_db(flow, step):
        flow.engine_db = SimpleNamespace(engine=None, initialization_error=None)

    monkeypatch.setattr(AgentEngineFlow, "init_db_engine_for_step", initialize_db)
    monkeypatch.setattr(
        "chipcompiler.utility.log.capture_stdio_to_file", lambda _path: nullcontext()
    )
    executed = []

    def tool_runner(workspace, step, ecc_module=None):
        executed.append((step.name, step.input.def_))
        return True

    assert run_step_worker(
        payload,
        {"events": []},
        lambda: None,
        flow_factory=flow_factory,
        tool_runner=tool_runner,
    )

    # The worker builds only the requested step, wired to filler's output.
    assert executed == [("drc", drc.input.def_)]
    assert created[0].workspace.flow.read_only is True
    assert _flow_path(workspace).read_bytes() == before


def _rerun_request():
    return CandidateRerunRequest(
        workspace_id="workspace-1",
        candidate_id="candidate-1",
        target_step="Floorplan",
        end_step="Harden",
        execution_scope="full_flow",
        idempotency_key="worker-mode-1",
        context_sha256="sha256:" + "a" * 64,
        parameter_card_sha256="sha256:" + "b" * 64,
        seed=17,
        patch=[],
        floorplan_mode="die_util",
    )


def _candidate_workspace(root):
    (root / "home").mkdir(parents=True)
    workspace = Workspace(directory=root, flow=Flow(path=root / "home" / "flow.json"))
    workspace.design.name = "example"
    workspace.design.top_module = "example"
    workspace.parameters = _write_parameters(root)
    config_path = root / "config" / "floorplan_ecc.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "die_builder": {
                    "mode": "die_size",
                    "die_size": {"width_micron": 100, "height_micron": 200},
                    "die_util": {"utilization": 0.5, "aspect_ratio": 1.0},
                }
            }
        ),
        encoding="utf-8",
    )
    workspace.config = {"Floorplan": config_path}
    flow = _new_flow(workspace, ("Floorplan",))
    prepare_floorplan_mode(workspace, _rerun_request())
    materialize_candidate_config(
        workspace,
        "Floorplan",
        [{"knob_id": "floorplan.aspect_ratio", "value": 2.0}],
        candidate_id="candidate-1",
    )
    flow.create_step_workspaces(initialize_config=False)
    return workspace, flow


def _sitecustomize_source():
    return """
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from agent import tools as agent_tools
from agent.data import floorplan_parameter_observer as floorplan_observer
from agent.data.floorplan_parameter_observer import step_path
from chipcompiler.engine.flow import EngineFlow

boundary = {"init_fp_call_count": 0, "run_fp_call_count": 0, "run_fp_completed": False}

@contextmanager
def capture(_patch):
    yield boundary

floorplan_observer.capture_floorplan = capture

def initialize_db(flow, step):
    flow.engine_db = SimpleNamespace(engine=None, initialization_error=None)
    return True

EngineFlow.init_db_engine_for_step = initialize_db

def build_step_config(workspace, step):
    parameters = workspace.parameters.data
    aspect_ratio = parameters.get("core", {}).get("aspect_ratio", 1.0)
    config = {
        "die_builder": {
            "mode": "die_size",
            "die_size": {"width_micron": 100, "height_micron": 200},
            "die_util": {"utilization": 0.5, "aspect_ratio": aspect_ratio},
        }
    }
    Path(workspace.config["Floorplan"]).write_text(json.dumps(config), encoding="utf-8")

def run_step(workspace, step, ecc_module=None):
    config_path = Path(workspace.config["Floorplan"])
    config = json.loads(config_path.read_text(encoding="utf-8"))
    boundary.update(
        init_fp_call_count=1,
        run_fp_call_count=1,
        run_fp_completed=True,
        config_path=str(config_path),
    )
    feature_path = step_path(step, "feature", "db")
    feature_path.parent.mkdir(parents=True, exist_ok=True)
    feature_path.write_text(
        json.dumps(
            {
                "Design Layout": {
                    "core_bounding_width": 40.0,
                    "core_bounding_height": 20.0,
                }
            }
        ),
        encoding="utf-8",
    )
    observed = Path(workspace.directory) / "analysis" / "worker-observed.json"
    observed.parent.mkdir(parents=True, exist_ok=True)
    observed.write_text(json.dumps({"config": config, "pid": os.getpid()}), encoding="utf-8")
    return True

agent_tools.load_eda_module = lambda *_args, **_kwargs: SimpleNamespace(
    build_step_config=build_step_config,
    run_step=run_step,
)
agent_tools.log_workspace_step = lambda *_args, **_kwargs: None
"""


@pytest.mark.real_step_worker
def test_real_agent_worker_applies_receipts_and_writes_parameter_report(tmp_path):
    root = tmp_path / ".agent" / "candidates" / "candidate-1"
    workspace, flow = _candidate_workspace(root)
    before = _flow_path(workspace).read_bytes()
    result_path = root / "worker-result.json"
    site_dir = tmp_path / "worker-startup"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(_sitecustomize_source(), encoding="utf-8")
    repository = Path(__file__).parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(site_dir), str(repository), env.get("PYTHONPATH", "")])
    payload = {
        "schema_version": 2,
        **_write_request(flow, "Floorplan", "agent-worker-test"),
        "result_path": str(result_path),
        "parent_pid": os.getpid(),
    }

    completed = subprocess.run(
        [sys.executable, "-m", "agent.step_worker"],
        input=json.dumps(payload),
        cwd=repository,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )

    evidence = result_path.read_text(encoding="utf-8") if result_path.exists() else "no result"
    assert completed.returncode == 0, completed.stdout + completed.stderr + evidence
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["done"] is True
    assert result["ok"] is True
    assert result["attempt_id"] == "agent-worker-test"
    observed = json.loads((root / "analysis" / "worker-observed.json").read_text())
    assert observed["pid"] != os.getpid()
    assert observed["config"]["die_builder"]["mode"] == "die_util"
    assert observed["config"]["die_builder"]["die_util"]["aspect_ratio"] == 2.0
    report = json.loads((root / "analysis" / "parameter_runtime_report.v2.json").read_text())
    assert report["status"] == "effective"
    assert report["actual_value"] == 2.0
    assert report["observation"] == {
        "mode": "die_util",
        "configured_value": 2.0,
        "init_fp_call_count": 1,
        "run_fp_call_count": 1,
        "geometry_constructed": True,
    }
    assert _flow_path(workspace).read_bytes() == before
