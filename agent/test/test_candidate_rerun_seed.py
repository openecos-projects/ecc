"""A candidate rerun stores its DreamPlace seed as the placement step's value."""

from pathlib import Path
from types import SimpleNamespace

from agent.requests import CandidateRerunRequest
from agent.test.test_workspace_api import CONTEXT_SHA256, _stored_step_values
from agent.workspace_api import _materialize_candidate_rerun
from chipcompiler.data.parameter import load_parameter
from chipcompiler.data.workspace_config import save_workspace_config


def _seed_target_workspace(tmp_path: Path) -> tuple[SimpleNamespace, Path]:
    dreamplace = tmp_path / "config" / "dreamplace.json"
    dreamplace.parent.mkdir()
    dreamplace.write_text('{"random_seed": 3000}', encoding="utf-8")
    assert save_workspace_config(tmp_path, {"core": {"utilitization": 0.5}})
    workspace = SimpleNamespace(
        directory=tmp_path,
        config={"dreamplace": dreamplace},
        parameters=load_parameter(tmp_path / "home" / "params.toml"),
        flow=SimpleNamespace(
            data={
                "steps": [
                    {"name": name, "tool": tool}
                    for name, tool in (("placement", "dreamplace"), ("cts", "ecc"))
                ]
            }
        ),
    )
    return workspace, dreamplace


def test_candidate_rerun_removes_stale_top_level_parameter_receipts(monkeypatch, tmp_path):
    analysis = tmp_path / "analysis"
    analysis.mkdir()
    workspace, dreamplace = _seed_target_workspace(tmp_path)
    for name in ("parameter_runtime_report.v2.json", "parameter_application_receipt.v2.json"):
        (analysis / name).write_text('{"stale": true}', encoding="utf-8")
    flow = SimpleNamespace(
        workspace=SimpleNamespace(
            flow=SimpleNamespace(
                data={"schema_version": 3, "steps": [{"name": "floorplan"}, {"name": "placement"}]}
            )
        )
    )
    request = CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="placement",
        end_step="harden",
        candidate_id="candidate-1",
        patch=[{"knob_id": "place.target_density", "value": 0.6}],
        execution_scope="full_flow",
        idempotency_key="episode-1.intervention-1",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=CONTEXT_SHA256,
        seed=17,
    )
    monkeypatch.setattr("agent.workspace_api.bind_candidate_input", lambda *_args: None)
    monkeypatch.setattr("agent.workspace_api.materialize_candidate_config", lambda *_args: None)

    steps = [
        SimpleNamespace(name=name, tool=tool)
        for name, tool in (("placement", "dreamplace"), ("cts", "ecc"), ("harden", "ecc"))
    ]

    _materialize_candidate_rerun(workspace, flow, request, steps)

    assert not (analysis / "parameter_runtime_report.v2.json").exists()
    assert not (analysis / "parameter_application_receipt.v2.json").exists()
    # The seed is the placement step's value, saved to params.toml; never the baseline.
    assert dreamplace.read_text(encoding="utf-8") == '{"random_seed": 3000}'
    assert _stored_step_values(tmp_path) == {"placement": {"place.random_seed": 17}}
    assert workspace.parameters.data["step_params"] == {"placement": {"place.random_seed": 17}}


def test_candidate_rerun_after_placement_stores_no_seed(monkeypatch, tmp_path):
    workspace, dreamplace = _seed_target_workspace(tmp_path)
    flow = SimpleNamespace(
        workspace=SimpleNamespace(
            flow=SimpleNamespace(
                data={"schema_version": 3, "steps": [{"name": "placement"}, {"name": "cts"}]}
            )
        )
    )
    request = CandidateRerunRequest(
        workspace_id="workspace-1",
        target_step="cts",
        end_step="harden",
        candidate_id="candidate-1",
        patch=[{"knob_id": "cts.skew_bound", "value": 0.1}],
        execution_scope="full_flow",
        idempotency_key="episode-1.intervention-1",
        context_sha256=CONTEXT_SHA256,
        parameter_card_sha256=CONTEXT_SHA256,
        seed=17,
    )
    monkeypatch.setattr("agent.workspace_api.bind_candidate_input", lambda *_args: None)
    monkeypatch.setattr("agent.workspace_api.materialize_candidate_config", lambda *_args: None)
    params_before = (tmp_path / "home" / "params.toml").read_bytes()

    _materialize_candidate_rerun(
        workspace, flow, request, [SimpleNamespace(name=name) for name in ("cts", "harden")]
    )

    assert (tmp_path / "home" / "params.toml").read_bytes() == params_before
    assert dreamplace.read_text(encoding="utf-8") == '{"random_seed": 3000}'
