import json
from pathlib import Path
from types import SimpleNamespace

from agent import tools
from agent.floorplan_mode import FLOORPLAN_MODE_REF, read_floorplan_mode
from agent.requests import CandidateResumeRequest
from agent.test.test_floorplan_mode import _request
from agent.test.test_workspace_api import _EccApi, _Flow, _wait_for_terminal
from agent.workspace_api import FlowAgentRuntimeApi
from chipcompiler.data import StateEnum


def _api(tmp_path, monkeypatch, *, fail_once=False):
    home = tmp_path / "home"
    home.mkdir()
    flow_path = home / "flow.json"
    data = {
        "steps": [
            {"name": "Synthesis", "tool": "yosys", "state": "Success"},
            {"name": "Floorplan", "tool": "ecc", "state": "Success"},
            {"name": "Harden", "tool": "ecc", "state": "Success"},
        ]
    }
    flow_path.write_text(json.dumps(data))
    config = tmp_path / "config"
    config.mkdir()
    (config / "dreamplace.json").write_text('{"random_seed": 0}')
    (config / "floorplan_ecc.json").write_text(
        json.dumps(
            {
                "die_builder": {
                    "mode": "die_size",
                    "die_size": {"width_micron": 100, "height_micron": 200},
                    "die_util": {"utilization": 0.5, "aspect_ratio": 1},
                }
            }
        )
    )
    netlist = tmp_path / "Synthesis_yosys/output/synth.v"
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module gcd(); endmodule\n")
    workspace = SimpleNamespace(directory=tmp_path, flow=SimpleNamespace(data=data, path=flow_path))
    consumed = []

    class Api(_EccApi):
        def _load_workspace(self, directory):
            candidate = super()._load_workspace(directory)
            candidate.config["Floorplan"] = Path(directory) / "config/floorplan_ecc.json"
            candidate.logger = SimpleNamespace()
            return candidate

    class Flow(_Flow):
        def get_workspace_step(self, name):
            return next(step for step in self.workspace_steps if step.name == name)

        def run_step(self, step, *, rerun, observer=None):
            if step.name == "Floorplan":
                success = tools.run_step(self.workspace, step)
                state = StateEnum.Success if success else StateEnum.Incomplete
                self.get_step(step.name, step.tool)["state"] = state.value
                self.save()
                return state
            result = super().run_step(step, rerun=rerun, observer=observer)
            self.get_step(step.name, step.tool)["state"] = "Success"
            self.save()
            return result

    def build_flow(candidate, **_kwargs):
        root = Path(candidate.directory)
        return Flow(
            candidate,
            (
                SimpleNamespace(
                    name="Synthesis",
                    tool="yosys",
                    output={"verilog": root / "Synthesis_yosys/output/synth.v"},
                ),
                SimpleNamespace(
                    name="Floorplan",
                    tool="ecc",
                    input=SimpleNamespace(),
                    output={"dir": root / "Floorplan_ecc/output"},
                ),
                SimpleNamespace(
                    name="Harden",
                    tool="ecc",
                    output=SimpleNamespace(
                        dir=root / "Harden_ecc/output",
                        gds=root / "Harden_ecc/output/gcd_Harden.gds",
                        lef=root / "Harden_ecc/output/gcd_Harden.lef",
                        lib=root / "Harden_ecc/output/gcd_Harden.lib",
                    ),
                ),
            ),
        )

    def rebuild(candidate, _step):
        path = candidate.config["Floorplan"]
        config = json.loads(path.read_text())
        config["die_builder"]["mode"] = "die_size"
        path.write_text(json.dumps(config))

    def native(*, workspace, **_kwargs):
        consumed.append(
            json.loads(workspace.config["Floorplan"].read_text())["die_builder"]["mode"]
        )
        return not (fail_once and len(consumed) == 1)

    api = FlowAgentRuntimeApi(Api(workspace))
    monkeypatch.setattr(api, "_build_flow", build_flow)
    monkeypatch.setattr(
        "agent.workspace_api._init_db_engine_for_workspace_step", lambda *_args: None
    )
    monkeypatch.setattr(
        tools,
        "load_eda_module",
        lambda *_args, **_kwargs: SimpleNamespace(build_step_config=rebuild, run_step=native),
    )
    monkeypatch.setattr(tools, "log_workspace_step", lambda *_args: None)
    return api, consumed


def test_mode_only_baseline_clones_switches_and_preserves_source(tmp_path, monkeypatch):
    api, consumed = _api(tmp_path, monkeypatch)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    operation = api.candidate_rerun(_request())
    terminal = _wait_for_terminal(api.ecc_api.operations, operation["operationId"])
    assert consumed == ["die_util"]
    result = terminal["result"]
    assert "parameterApplicationReceipt" not in result
    first = tmp_path / result["candidateRootRef"]
    manifest = json.loads((first / "analysis/candidate_workspace.v1.json").read_text())
    assert manifest["artifacts"]["floorplan_mode"]["ref"] == FLOORPLAN_MODE_REF
    assert "candidate_materialization" not in manifest["artifacts"]
    assert before == {ref: (tmp_path / ref).read_bytes() for ref in before}
    operation = api.candidate_rerun(
        _request(
            candidate_id="candidate-2",
            idempotency_key="mode-2",
            floorplan_mode="die_size",
            parent_candidate_root_ref=result["candidateRootRef"],
        )
    )
    _wait_for_terminal(api.ecc_api.operations, operation["operationId"])
    assert consumed == ["die_util", "die_size"]
    assert read_floorplan_mode(api.ecc_api._load_workspace(first))["mode"] == "die_util"


def test_failed_mode_baseline_resumes_without_changing_mode(tmp_path, monkeypatch):
    api, consumed = _api(tmp_path, monkeypatch, fail_once=True)
    request = _request()
    started = api.candidate_rerun(request)
    _wait_for_terminal(api.ecc_api.operations, started["operationId"], expected_state="failed")
    resumed = api.candidate_resume(
        CandidateResumeRequest(
            workspace_id=request.workspace_id,
            candidate_id=request.candidate_id,
            idempotency_key="resume-1",
            context_sha256=request.context_sha256,
            parameter_card_sha256=request.parameter_card_sha256,
            seed=request.seed,
        )
    )
    terminal = _wait_for_terminal(api.ecc_api.operations, resumed["operationId"])
    assert terminal["result"]["resumeStep"] == "Floorplan"
    assert consumed == ["die_util", "die_util"]


def test_resume_rejects_mode_receipt_tampering_before_running(tmp_path, monkeypatch):
    api, consumed = _api(tmp_path, monkeypatch, fail_once=True)
    request = _request()
    started = api.candidate_rerun(request)
    _wait_for_terminal(api.ecc_api.operations, started["operationId"], expected_state="failed")
    receipt = tmp_path / ".agent/candidates/candidate-1" / FLOORPLAN_MODE_REF
    payload = json.loads(receipt.read_text())
    payload["mode"] = "die_size"
    receipt.write_text(json.dumps(payload))
    resumed = api.candidate_resume(
        CandidateResumeRequest(
            workspace_id=request.workspace_id,
            candidate_id=request.candidate_id,
            idempotency_key="resume-tampered",
            context_sha256=request.context_sha256,
            parameter_card_sha256=request.parameter_card_sha256,
            seed=request.seed,
        )
    )
    _wait_for_terminal(api.ecc_api.operations, resumed["operationId"], expected_state="failed")
    assert consumed == ["die_util"]
