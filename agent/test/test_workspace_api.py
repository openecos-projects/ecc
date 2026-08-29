import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.data.candidate_artifacts import sha256_path
from agent.data.candidate_materialization import materialize_candidate_config
from agent.requests import CandidateRerunRequest
from agent.workspace_api import (
    FlowAgentRuntimeApi,
    _candidate_rerun_steps,
    _candidate_step_artifact_dirs,
    _materialize_candidate_rerun,
    _reject_workspace_symlinks,
    build_agent_flow_for_workspace,
)
from chipcompiler.data import StateEnum
from chipcompiler.data.workspace.layout import EccOutput
from chipcompiler.runtime.operations import RuntimeOperationManager
from chipcompiler.runtime.workspace_api import RuntimeApiError

CONTEXT_SHA256 = "sha256:" + "a" * 64


def test_candidate_artifact_dirs_support_typed_step_outputs(tmp_path):
    output_dir = tmp_path / "place_dreamplace" / "output"
    analysis_dir = tmp_path / "place_dreamplace" / "analysis"
    step = SimpleNamespace(
        output=EccOutput(dir=output_dir),
        analysis={"dir": analysis_dir},
    )

    assert _candidate_step_artifact_dirs(step) == (Path(output_dir), Path(analysis_dir))


@pytest.mark.parametrize(
    "target_step,expected_first",
    [
        ("Floorplan", "Floorplan"),
        ("fixFanout", "fixFanout"),
        ("place", "place"),
    ],
)
def test_candidate_rerun_slice_starts_at_the_modified_stage(
    target_step: str, expected_first: str
) -> None:
    names = ("Synthesis", "Floorplan", "fixFanout", "place", "CTS", "Harden")
    flow = SimpleNamespace(workspace_steps=tuple(SimpleNamespace(name=name) for name in names))

    steps = _candidate_rerun_steps(flow, target_step, "Harden", "full_flow")

    assert steps[0].name == expected_first
    assert steps[-1].name == "Harden"


def test_agent_flow_defaults_to_harden_flow(monkeypatch):
    class RecordingFlow:
        def __init__(self, workspace):
            self.workspace = workspace
            self.added_steps = []

        def has_init(self):
            return False

        def add_step(self, step, tool, state):
            self.added_steps.append((step, tool, state))

        def create_step_workspaces(self):
            return None

    monkeypatch.setattr("agent.workspace_api.AgentEngineFlow", RecordingFlow)
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_rtl2gds_flow",
        lambda: [("rtl2gds", "ecc", "Unstart")],
    )
    monkeypatch.setattr(
        "chipcompiler.rtl2gds.build_harden_flow",
        lambda: [("Harden", "ecc", "Unstart")],
    )

    flow = build_agent_flow_for_workspace(SimpleNamespace())

    assert flow.added_steps == [("Harden", "ecc", "Unstart")]


def test_candidate_rerun_starts_a_full_flow_operation_and_replays_its_receipts(
    monkeypatch, tmp_path
):
    flow_data = {
        "steps": [
            {"name": "Floorplan", "tool": "ecc", "state": "Success"},
            {"name": "place", "tool": "dreamplace", "state": "Success"},
            {"name": "CTS", "tool": "ecc", "state": "Success"},
            {"name": "Harden", "tool": "ecc", "state": "Success"},
        ]
    }
    flow_path = tmp_path / "home" / "flow.json"
    flow_path.parent.mkdir()
    flow_path.write_text(json.dumps(flow_data), encoding="utf-8")
    parent_flow_bytes = flow_path.read_bytes()
    config_path = tmp_path / "config" / "dreamplace.json"
    config_path.parent.mkdir()
    config_path.write_text('{"target_density": 0.5}\n', encoding="utf-8")
    workspace = SimpleNamespace(
        directory=tmp_path,
        flow=SimpleNamespace(data=flow_data, path=flow_path),
    )
    for directory in (
        tmp_path / "place_dreamplace" / "output",
        tmp_path / "place_dreamplace" / "analysis",
        tmp_path / "CTS_ecc" / "output",
        tmp_path / "Harden_ecc" / "output",
    ):
        directory.mkdir(parents=True)
        (directory / "stale").write_text("stale", encoding="utf-8")
    api = FlowAgentRuntimeApi(_EccApi(workspace))
    calls = []
    flows = []

    def build_flow(candidate_workspace, *, create_step_workspaces=True):
        assert create_step_workspaces is False
        root = Path(candidate_workspace.directory)
        flow = _Flow(
            candidate_workspace,
            (
                SimpleNamespace(name="Floorplan", tool="ecc", output={}),
                SimpleNamespace(
                    name="place",
                    tool="dreamplace",
                    output=EccOutput(dir=root / "place_dreamplace" / "output"),
                    analysis={"dir": root / "place_dreamplace" / "analysis"},
                ),
                SimpleNamespace(
                    name="CTS",
                    tool="ecc",
                    output={"dir": root / "CTS_ecc" / "output"},
                ),
                SimpleNamespace(
                    name="Harden",
                    tool="ecc",
                    output={"dir": root / "Harden_ecc" / "output"},
                ),
            ),
        )
        flows.append(flow)
        return flow

    monkeypatch.setattr("agent.workspace_api.build_agent_flow_for_workspace", build_flow)
    monkeypatch.setattr(
        "agent.workspace_api.bind_candidate_input",
        lambda _ws, _flow, target, source, candidate: (
            calls.append(("bind", target, source, candidate))
            if flows[-1].created
            else pytest.fail("candidate steps must exist before input binding")
        ),
    )

    def materialize(candidate_workspace, target, patch, candidate):
        assert flows[-1].created
        assert flows[-1].initialize_config is False
        path = Path(candidate_workspace.directory) / "config" / "dreamplace.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        config[patch[0]["knob_id"].removeprefix("place.")] = patch[0]["value"]
        path.write_text(json.dumps(config, sort_keys=True) + "\n", encoding="utf-8")
        calls.append(("materialize", target, patch, candidate))

    monkeypatch.setattr("agent.workspace_api.materialize_candidate_config", materialize)
    monkeypatch.setattr(
        "agent.workspace_api.validate_candidate_step_contract",
        lambda _ws, _target: "candidate-1",
    )
    monkeypatch.setattr(
        "agent.workspace_api.reapply_candidate_input_binding",
        lambda _ws, _flow, target: calls.append(("reapply", target)),
    )
    monkeypatch.setattr(
        "agent.workspace_api._init_db_engine_for_workspace_step",
        lambda _flow, step: calls.append(("init", step.name)),
    )

    result = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )

    assert result["operationId"].startswith("operation-")
    assert result["kind"] == "candidate_rerun"
    assert result["origin"] == "agent"
    assert result["rerun"] is True
    assert result["step"] == "place"
    duplicate = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )
    assert duplicate["operationId"] == result["operationId"]
    assert duplicate["deduplicated"] is True
    terminal = _wait_for_terminal(api.ecc_api.operations, result["operationId"])
    assert calls == [
        ("bind", "place", "Floorplan", "candidate-1"),
        (
            "materialize",
            "place",
            [{"knob_id": "place.target_density", "value": 0.6}],
            "candidate-1",
        ),
        ("reapply", "place"),
        ("init", "place"),
        ("init", "CTS"),
        ("init", "Harden"),
    ]
    candidate_root = tmp_path / ".agent" / "candidates" / "candidate-1"
    candidate_root_ref = ".agent/candidates/candidate-1"
    candidate_manifest_ref = f"{candidate_root_ref}/analysis/candidate_workspace.v1.json"
    assert flows[0].run_calls == [("place", True), ("CTS", True), ("Harden", True)]
    assert flows[0].created is True
    assert flows[0].initialize_config is False
    assert flow_path.read_bytes() == parent_flow_bytes
    assert config_path.read_text(encoding="utf-8") == '{"target_density": 0.5}\n'
    assert (tmp_path / "place_dreamplace" / "output" / "stale").is_file()
    assert (tmp_path / "place_dreamplace" / "analysis" / "stale").is_file()
    assert (tmp_path / "CTS_ecc" / "output" / "stale").is_file()
    assert (tmp_path / "Harden_ecc" / "output" / "stale").is_file()
    assert (candidate_root / "config" / "dreamplace.json").read_text(encoding="utf-8") == (
        '{"target_density": 0.6}\n'
    )
    assert not list((candidate_root / "place_dreamplace" / "output").iterdir())
    assert not list((candidate_root / "place_dreamplace" / "analysis").iterdir())
    assert not list((candidate_root / "CTS_ecc" / "output").iterdir())
    assert not list((candidate_root / "Harden_ecc" / "output").iterdir())
    candidate_manifest = candidate_root / "analysis" / "candidate_workspace.v1.json"
    result = terminal["result"]
    assert {key: value for key, value in result.items() if key != "candidateManifestSha256"} == {
        "candidateId": "candidate-1",
        "candidateManifestRef": candidate_manifest_ref,
        "candidateRootRef": candidate_root_ref,
        "endStep": "Harden",
        "executionScope": "full_flow",
        "targetStep": "place",
    }
    assert candidate_manifest.is_file()
    assert result["candidateManifestSha256"] == sha256_path(candidate_manifest)
    first_manifest = json.loads(candidate_manifest.read_text(encoding="utf-8"))
    assert first_manifest["candidate_id"] == "candidate-1"
    assert first_manifest["terminal_state"] == "succeeded"
    assert first_manifest["candidate_state_sha256"].startswith("sha256:")
    assert "candidate_execution_receipt" not in first_manifest["artifacts"]
    execution_receipt = json.loads(
        (candidate_root / "analysis" / "candidate_execution_receipt.v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert execution_receipt["candidate_manifest_sha256"] == result["candidateManifestSha256"]

    second = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-2",
            patch=[{"knob_id": "place.routability_opt", "value": True}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-2",
            context_sha256=CONTEXT_SHA256,
            seed=17,
            parent_candidate_root_ref=candidate_root_ref,
        )
    )
    _wait_for_terminal(api.ecc_api.operations, second["operationId"])
    second_config = json.loads(
        (
            tmp_path / ".agent" / "candidates" / "candidate-2" / "config" / "dreamplace.json"
        ).read_text(encoding="utf-8")
    )
    assert second_config == {"routability_opt": True, "target_density": 0.6}
    second_manifest = json.loads(
        (
            tmp_path
            / ".agent"
            / "candidates"
            / "candidate-2"
            / "analysis"
            / "candidate_workspace.v1.json"
        ).read_text(encoding="utf-8")
    )
    assert second_manifest["parent_candidate_root_ref"] == candidate_root_ref
    assert second_manifest["parent_manifest_ref"] == candidate_manifest_ref
    assert second_manifest["parent_manifest_sha256"] == sha256_path(candidate_manifest)
    assert second_manifest["parent_state_sha256"] == first_manifest["candidate_state_sha256"]

    first_manifest["terminal_state"] = "failed"
    candidate_manifest.write_text(json.dumps(first_manifest), encoding="utf-8")
    rejected = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-3",
            patch=[{"knob_id": "place.target_density", "value": 0.7}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-3",
            context_sha256=CONTEXT_SHA256,
            seed=17,
            parent_candidate_root_ref=candidate_root_ref,
        )
    )
    terminal = _wait_for_terminal(api.ecc_api.operations, rejected["operationId"], "failed")
    assert "verified successful Harden candidate" in terminal["error"]["message"]
    assert not (tmp_path / ".agent" / "candidates" / "candidate-3").exists()


def test_failed_candidate_returns_materialization_application_and_manifest_evidence(
    monkeypatch,
    tmp_path,
) -> None:
    candidate = tmp_path / ".agent" / "candidates" / "candidate-failed"
    flow_path = candidate / "home" / "flow.json"
    flow_path.parent.mkdir(parents=True)
    flow_path.write_text(
        json.dumps(
            {
                "steps": [
                    {"name": "place", "tool": "dreamplace", "state": "Success"},
                    {"name": "Harden", "tool": "ecc", "state": "Success"},
                ]
            }
        ),
        encoding="utf-8",
    )
    config = candidate / "config" / "dreamplace.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"target_density": 0.5}', encoding="utf-8")
    candidate_workspace = SimpleNamespace(
        directory=candidate,
        config={"dreamplace": config},
        flow=SimpleNamespace(data=json.loads(flow_path.read_text()), path=flow_path),
    )
    parent = {
        "root": tmp_path,
        "root_ref": None,
        "flow_sha256": "sha256:" + "1" * 64,
        "state_sha256": "sha256:" + "2" * 64,
        "manifest_ref": None,
        "manifest_sha256": None,
    }
    steps = tuple(
        SimpleNamespace(name=name, tool=tool, output={})
        for name, tool in (("place", "dreamplace"), ("Harden", "ecc"))
    )
    flow = SimpleNamespace(
        workspace_steps=steps,
        create_step_workspaces=lambda **_kwargs: None,
    )
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)
    monkeypatch.setattr(
        "agent.workspace_api._create_candidate_workspace",
        lambda *_args: (candidate_workspace, ".agent/candidates/candidate-failed", parent),
    )
    monkeypatch.setattr(api, "_build_flow", lambda *_args, **_kwargs: flow)
    monkeypatch.setattr(
        "agent.workspace_api._materialize_candidate_rerun",
        lambda workspace, _flow, request: materialize_candidate_config(
            workspace, request.target_step, request.patch, request.candidate_id
        ),
    )
    monkeypatch.setattr("agent.workspace_api._prepare_candidate_rerun", lambda *_args: None)
    monkeypatch.setattr("agent.workspace_api._reapply_candidate_input", lambda *_args: None)
    tool = {
        "name": "DREAMPlace",
        "revision": "ecc.dreamplace.parameter_runtime_report.v2",
        "source_sha256": "sha256:" + "3" * 64,
    }

    def run_candidate_step(_flow, step, **_kwargs):
        if step.name == "place":
            report = {
                "knob_id": "place.target_density",
                "requested_value": 0.6,
                "tool": tool,
                "application_status": "applied",
                "effective_initial": {"value": 0.6, "unit": "ratio"},
                "effective_final": {"value": 0.6, "unit": "ratio"},
                "activation": {
                    "status": "used",
                    "consumers": [
                        {
                            "consumer_id": "dreamplace.density_objective",
                            "outcome": "entered",
                            "evidence_ref": "analysis/parameter_runtime_report.v1.json",
                            "evidence_sha256": "sha256:" + "4" * 64,
                        }
                    ],
                },
                "consumer_observation": {
                    "requested_target_density": 0.6,
                    "effective_target_density": 0.6,
                    "density_tensor_value": 0.6,
                    "placement_iteration_count": 3,
                    "evidence_complete": True,
                },
                "transitions": [],
            }
            (candidate / "analysis" / "parameter_runtime_report.v1.json").write_text(
                json.dumps(report), encoding="utf-8"
            )
            return
        raise RuntimeError("Harden failed")

    monkeypatch.setattr("agent.workspace_api._run_candidate_step", run_candidate_step)
    monkeypatch.setattr(
        "agent.workspace_api._parameter_receipt_context",
        lambda *_args: {"site_width_dbu": 200},
    )

    started = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-failed",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.failed",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )

    terminal = _wait_for_terminal(ecc_api.operations, started["operationId"], "failed")
    assert terminal["result"].get("evidenceError") is None, terminal["result"].get("evidenceError")
    assert "parameterApplicationReceipt" in terminal["result"], terminal
    application = terminal["result"]["parameterApplicationReceipt"]
    assert application["application_status"] == "applied"
    assert application["tool"] == tool
    assert application["context"]["tool_revision"] == tool["revision"]
    assert application["context"]["context_sha256"] == CONTEXT_SHA256
    manifest = json.loads(
        (candidate / "analysis" / "candidate_workspace.v1.json").read_text(encoding="utf-8")
    )
    assert manifest["terminal_state"] == "failed"
    assert set(manifest["artifacts"]) >= {
        "candidate_materialization",
        "parameter_runtime_report",
        "parameter_application_receipt",
    }
    assert "candidate_execution_receipt" not in manifest["artifacts"]
    assert terminal["result"]["candidateManifestSha256"] == sha256_path(
        candidate / "analysis" / "candidate_workspace.v1.json"
    )
    execution_receipt = json.loads(
        (candidate / "analysis" / "candidate_execution_receipt.v1.json").read_text(encoding="utf-8")
    )
    assert (
        execution_receipt["candidate_manifest_sha256"]
        == terminal["result"]["candidateManifestSha256"]
    )
    assert terminal["result"]["parameterApplicationReceiptRef"] == (
        ".agent/candidates/candidate-failed/analysis/parameter_application_receipt.v1.json"
    )
    assert terminal["result"]["parameterApplicationReceiptSha256"] == sha256_path(
        candidate / "analysis" / "parameter_application_receipt.v1.json"
    )


def test_candidate_rerun_removes_stale_top_level_parameter_receipts(monkeypatch, tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    for name in ("parameter_runtime_report.v1.json", "parameter_application_receipt.v1.json"):
        (analysis / name).write_text('{"stale": true}', encoding="utf-8")
    flow = SimpleNamespace(
        workspace=SimpleNamespace(
            flow=SimpleNamespace(data={"steps": [{"name": "fixFanout"}, {"name": "place"}]})
        )
    )
    request = CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="place",
        end_step="Harden",
        candidate_id="candidate-1",
        patch=[{"knob_id": "place.target_density", "value": 0.6}],
        execution_scope="full_flow",
        idempotency_key="episode-1.intervention-1",
        context_sha256=CONTEXT_SHA256,
        seed=17,
    )
    monkeypatch.setattr("agent.workspace_api.bind_candidate_input", lambda *_args: None)
    monkeypatch.setattr("agent.workspace_api.materialize_candidate_config", lambda *_args: None)

    _materialize_candidate_rerun(SimpleNamespace(directory=tmp_path), flow, request)

    assert not (analysis / "parameter_runtime_report.v1.json").exists()
    assert not (analysis / "parameter_application_receipt.v1.json").exists()


def test_candidate_rerun_rejects_multi_knob_patch_before_starting_an_operation(tmp_path):
    workspace = SimpleNamespace(directory=tmp_path)
    ecc_api = _EccApi(workspace)
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="exactly one patch item"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="Harden",
                candidate_id="candidate-1",
                patch=[
                    {"knob_id": "place.target_density", "value": 0.6},
                    {"knob_id": "place.routability_opt", "value": True},
                ],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
                context_sha256=CONTEXT_SHA256,
                seed=17,
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


def test_candidate_rerun_rejects_invalid_context_hash_before_starting_an_operation(tmp_path):
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="context_sha256"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="Harden",
                candidate_id="candidate-1",
                patch=[{"knob_id": "place.target_density", "value": 0.6}],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
                context_sha256="sha256:invalid",
                seed=17,
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


def test_candidate_rerun_rejects_non_harden_end_step_before_starting_an_operation(tmp_path):
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="end step must be Harden"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="CTS",
                candidate_id="candidate-1",
                patch=[{"knob_id": "place.target_density", "value": 0.6}],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
                context_sha256=CONTEXT_SHA256,
                seed=17,
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


def test_candidate_rerun_rejects_unsafe_candidate_id_before_starting_an_operation(tmp_path):
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="candidate_id"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="Harden",
                candidate_id="../escape",
                patch=[{"knob_id": "place.target_density", "value": 0.6}],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
                context_sha256=CONTEXT_SHA256,
                seed=17,
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


def test_candidate_rerun_rejects_unsafe_parent_candidate_ref_before_starting_an_operation(
    tmp_path,
):
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    with pytest.raises(RuntimeApiError, match="parent_candidate_root_ref"):
        api.candidate_rerun(
            CandidateRerunRequest(
                workspace_id="workspace-1",
                target_step="place",
                end_step="Harden",
                candidate_id="candidate-1",
                patch=[{"knob_id": "place.target_density", "value": 0.6}],
                execution_scope="full_flow",
                idempotency_key="episode-1.intervention-1",
                context_sha256=CONTEXT_SHA256,
                seed=17,
                parent_candidate_root_ref="../outside",
            )
        )

    assert ecc_api.operations.workspace_snapshot("workspace-1")["operations"] == []


def test_candidate_rerun_rejects_parent_workspace_symlinks(tmp_path):
    target = tmp_path / "outside"
    target.mkdir()
    (tmp_path / "unsafe-link").symlink_to(target, target_is_directory=True)
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    operation = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )

    terminal = _wait_for_terminal(api.ecc_api.operations, operation["operationId"], "failed")
    assert "symbolic link" in terminal["error"]["message"]
    assert not (tmp_path / ".agent").exists()


def test_candidate_snapshot_ignores_prior_candidate_symlinks(tmp_path):
    candidate_dir = tmp_path / ".agent" / "candidates" / "old-candidate"
    candidate_dir.mkdir(parents=True)
    (candidate_dir / "tool-link").symlink_to(tmp_path, target_is_directory=True)

    _reject_workspace_symlinks(tmp_path)


def test_candidate_rerun_removes_partial_clone_on_copy_failure(monkeypatch, tmp_path):
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / "flow.json").write_text('{"steps": []}', encoding="utf-8")
    ecc_api = _EccApi(SimpleNamespace(directory=tmp_path))
    api = FlowAgentRuntimeApi(ecc_api)

    def fail_copy(*_args, **_kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr("agent.workspace_api.shutil.copytree", fail_copy)

    operation = api.candidate_rerun(
        CandidateRerunRequest(
            workspace_id="workspace-1",
            target_step="place",
            end_step="Harden",
            candidate_id="candidate-1",
            patch=[{"knob_id": "place.target_density", "value": 0.6}],
            execution_scope="full_flow",
            idempotency_key="episode-1.intervention-1",
            context_sha256=CONTEXT_SHA256,
            seed=17,
        )
    )

    terminal = _wait_for_terminal(api.ecc_api.operations, operation["operationId"], "failed")
    assert "candidate workspace clone failed" in terminal["error"]["message"]
    assert not (tmp_path / ".agent" / "candidates" / "candidate-1").exists()


class _EccApi:
    def __init__(self, workspace):
        self.session = SimpleNamespace(workspace=workspace, db_handle=None)
        self.events = []
        self.operations = RuntimeOperationManager(self.events.append)

    def _get_session(self, workspace_id):
        assert workspace_id == "workspace-1"
        return self.session

    def _load_workspace(self, directory):
        root = Path(directory)
        flow_path = root / "home" / "flow.json"
        return SimpleNamespace(
            directory=root,
            flow=SimpleNamespace(
                data=json.loads(flow_path.read_text(encoding="utf-8")), path=flow_path
            ),
        )

    def _with_session_mutation_lock(self, workspace_id, operation):
        assert workspace_id == "workspace-1"
        return operation(self.session)

    def _should_capture_session_db(self, _session):
        return False

    def _close_transient_flow_db(self, _flow):
        return None


class _Flow:
    def __init__(self, workspace, workspace_steps):
        self.workspace = workspace
        self._workspace_steps = workspace_steps
        self.workspace_steps = ()
        self.created = False
        self.initialize_config = None
        self.run_calls = []

    def create_step_workspaces(self, *, initialize_config=True):
        self.workspace_steps = self._workspace_steps
        self.created = True
        self.initialize_config = initialize_config

    def get_step(self, name, tool):
        return next(
            (
                step
                for step in self.workspace.flow.data["steps"]
                if step["name"] == name and step["tool"] == tool
            ),
            None,
        )

    def save(self):
        self.workspace.flow.path.write_text(json.dumps(self.workspace.flow.data), encoding="utf-8")
        return True

    def run_step(self, step, *, rerun, observer=None):
        self.run_calls.append((step.name, rerun))
        if observer is not None:
            observer.on_step_started(step)
            observer.on_step_completed(step, StateEnum.Success)
        return StateEnum.Success


def _wait_for_terminal(operations, operation_id, expected_state="succeeded"):
    deadline = threading.Event()
    for _ in range(100):
        status = operations.operation_status(operation_id)
        if status["state"] in {"succeeded", "failed", "cancelled"}:
            assert status["state"] == expected_state
            return status
        deadline.wait(0.01)
    raise AssertionError("candidate operation did not reach a terminal state")
