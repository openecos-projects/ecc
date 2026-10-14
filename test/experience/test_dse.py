import hashlib
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.api import dse_plan, dse_run
from ecc_experience.dse import execute, plan, trial
from ecc_experience.files import digest
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import Invocation


@pytest.fixture
def dse_project(workspace_factory, tmp_path, monkeypatch):
    workspace = workspace_factory("source")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    rtl = tmp_path / "design.v"
    rtl.write_text("module sample; endmodule")
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "pdk": {"familyId": "ics55"},
        "flow": {"flowId": "custom"},
        "parameters": {"floorplan.core_util": 0.3},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(rtl)}}
    snapshot["flow"]["steps"] = [
        {
            "name": name,
            "tool": tool,
            "state": "Success",
            "checklist_status": {"status": "passed", "blocked": False},
        }
        for name, tool in [("Synthesis", "yosys"), ("postFloorplan", "ecc"), ("route", "ecc")]
    ]
    reference = "postFloorplan_ecc/analysis/qor_metrics.json"
    report = workspace / reference
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": "postFloorplan",
                "tool": "ecc",
                "status": "success",
                "integrity": {"status": "pass"},
                "analysis_revision": "quality-gates-v4",
                "metrics": [
                    {
                        "id": "core_area",
                        "value": 100.0,
                        "unit": "um^2",
                        "scope": "floorplan",
                        "category": "area_cost",
                    }
                ],
            }
        )
    )
    snapshot["artifacts"].append(
        {
            "artifactId": "artifact-"
            + hashlib.sha256(f"{snapshot['workspaceId']}\0{reference}".encode()).hexdigest()[:32],
            "reference": reference,
            "kind": "qor_metrics",
            "stepId": "postFloorplan",
            "availability": "available",
        }
    )
    snapshot["qorSnapshotExtension"].update(status="available", score=90.0, scalarStatus="GREEN")
    snapshot["qorSnapshotExtension"].pop("reason")
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "sample",
                "root_path": str(tmp_path),
                "workspaces": [{"workspace_id": "source", "workspace_path": str(workspace)}],
            }
        )
    )
    monkeypatch.setattr(plan, "runtime_identity", lambda: {"test": "runtime"})
    monkeypatch.setattr(trial, "runtime_identity", lambda: {"test": "runtime"})
    return workspace, tmp_path / "store", tmp_path / "plan.json"


def make_plan(dse_project, *, parameters=None, **overrides):
    workspace, store, output = dse_project
    options = {
        "parameters": parameters or ["floorplan.core_util=0.35"],
        "through_step": "postFloorplan",
        "metric": "core_area",
        "unit": "um^2",
        "direction": "minimize",
        "limits": {"max_trials": 3, "max_seconds": 60, "trial_timeout_seconds": 30},
        **overrides,
    }
    return dse_plan(workspace.parent, workspace, store, output, **options)


@pytest.fixture
def simulated_cli(dse_project, monkeypatch):
    workspace, _store, _output = dse_project
    calls = []

    def invoke(self, arguments, *, deadline):
        calls.append(arguments)
        stdout = self.output / f"stdout-{len(calls)}"
        stderr = self.output / f"stderr-{len(calls)}"
        stdout.write_text("")
        stderr.write_text("")
        root = Path(arguments[arguments.index("--project") + 1])
        if arguments[:2] == ["workspace", "derive"]:
            shutil.copytree(workspace, root / arguments[3])
        elif arguments[:2] == ["param", "apply"]:
            target = root / arguments[arguments.index("--workspace") + 1]
            path = target / "home/engineering-snapshot.json"
            payload = json.loads(path.read_text())
            from chipcompiler.data.parameter_schema import parse_cli_overrides

            pairs = [
                arguments[index + 1] for index, item in enumerate(arguments) if item == "--set"
            ]
            parsed, errors = parse_cli_overrides(pairs)
            assert not errors
            payload["workspaceSpec"]["parameters"].update(parsed)
            path.write_text(json.dumps(payload))
        elif arguments[0] == "run":
            target = root / arguments[arguments.index("--workspace") + 1]
            run_id = arguments[arguments.index("--run-id") + 1]
            (target / "log").mkdir(exist_ok=True)
            (target / "log" / f"{run_id}.log").write_text(f"ECC run {run_id} started\n")
            path = target / "home/engineering-snapshot.json"
            payload = json.loads(path.read_text())
            if "--to" in arguments:
                payload["flow"]["steps"][-1]["state"] = "Unstart"
                payload["qorSnapshotExtension"]["score"] = None
            else:
                payload["qorSnapshotExtension"]["score"] = 95.0
            path.write_text(json.dumps(payload))
            (target / "home/flow.json").write_text(json.dumps(payload["flow"]))
            report = target / "postFloorplan_ecc/analysis/qor_metrics.json"
            metrics = json.loads(report.read_text())
            metrics["metrics"][0]["value"] = 80.0
            report.write_text(json.dumps(metrics))
        return Invocation(0, stdout, stderr)

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    monkeypatch.setattr(
        trial,
        "inspect_workspace",
        lambda *_args, **_kwargs: {
            "status": "passed",
            "qor_score": 95.0,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 0,
        },
    )
    monkeypatch.setattr(
        execute,
        "inspect_workspace",
        lambda *_args, **_kwargs: {"status": "passed", "qor_score": 90.0},
    )
    return calls


def test_dse_keeps_stage_acceptance_separate_and_reserves_full_and_fresh(
    dse_project, simulated_cli
):
    workspace, _store, path = dse_project
    before = {
        str(item.relative_to(workspace)): item.read_bytes()
        for item in workspace.rglob("*")
        if item.is_file()
    }
    make_plan(dse_project)
    result = dse_run(path, path.parent / "output")
    assert result["status"] == "complete", result
    assert result["exit_code"] == 0
    assert result["score_delta"] == 5.0
    assert result["stage_winner"]["stage_value"] == 80.0
    assert result["stage_winner"]["validation_scope"] == "flow_prefix_only"
    assert result["stage_winner"]["full_signoff"] == "not_evaluated"
    assert result["stage_winner"]["verification"]["status"] == "unknown"
    flows = [item for item in simulated_cli if item[0] == "run"]
    assert len(flows) == 3
    assert "--from" in flows[0] and "--to" in flows[0]
    assert all("--to" not in item for item in flows[1:])
    assert (
        len(
            {
                item["workspace"]
                for item in [
                    result["stage_winner"],
                    result["full_validation"],
                    result["fresh_validation"],
                ]
            }
        )
        == 3
    )
    assert {
        str(item.relative_to(workspace)): item.read_bytes()
        for item in workspace.rglob("*")
        if item.is_file()
    } == before


@pytest.mark.parametrize(
    "parameters,overrides",
    [
        (["floorplan.core_util=0.3,0.4"], {}),
        (["floorplan.core_util=0.3", "floorplan.core_util=0.4"], {}),
        (["cts.max_fanout=16"], {}),
        (["floorplan.core_util=2.0"], {}),
        (["route.top_layer=MET5"], {}),
        (["floorplan.core_util=0.4"], {"metric": "missing"}),
        (["floorplan.core_util=0.4"], {"unit": "ns"}),
        (["floorplan.core_util=0.4"], {"through_step": "route"}),
    ],
)
def test_dse_rejects_unbounded_unsupported_or_incomparable_plans(
    dse_project, parameters, overrides
):
    with pytest.raises(ExperienceError):
        make_plan(dse_project, parameters=parameters, **overrides)


@pytest.mark.parametrize(
    "failure", ["timeout", "cancelled", "failed", "full_failure", "fresh_failure"]
)
def test_dse_preserves_failure_records_and_never_reports_partial_winner_as_success(
    dse_project, simulated_cli, monkeypatch, failure
):
    _workspace, _store, path = dse_project
    make_plan(dse_project)
    original = execute.execute_trial

    def invoke(plan, candidate, limits, runner, record, save, *, mode):
        if (
            failure == "full_failure"
            and mode == "full"
            or failure == "fresh_failure"
            and mode == "fresh"
        ):
            record.update(status="failed", exit_code=6, collection_status="failed", mode=mode)
        elif failure in {"timeout", "cancelled", "failed"} and mode == "screen":
            record.update(
                status=failure,
                exit_code={"timeout": 124, "cancelled": 130, "failed": 6}[failure],
                collection_status="not_attempted",
                mode=mode,
            )
            save()
            if failure == "cancelled":
                raise KeyboardInterrupt
        else:
            original(plan, candidate, limits, runner, record, save, mode=mode)

    monkeypatch.setattr(execute, "execute_trial", invoke)
    result = dse_run(path, path.parent / "output")
    assert result["exit_code"] == {"timeout": 124, "cancelled": 130}.get(failure, 6)
    assert result["status"] != "complete"
    assert result["trials"]
    assert (
        json.loads((path.parent / "output/result.json").read_text())["status"] == result["status"]
    )


def test_dse_revalidates_resealed_unsupported_candidates_and_frozen_source(dse_project):
    workspace, _store, path = dse_project
    make_plan(dse_project)
    payload = json.loads(path.read_text())
    payload["candidates"][0]["parameters"] = {"route.top_layer": "MET5"}
    payload["candidates"][0]["sets"] = ["route.top_layer=MET5"]
    payload["plan_fingerprint"] = digest(
        {key: value for key, value in payload.items() if key != "plan_fingerprint"}
    )
    path.write_text(json.dumps(payload))
    with pytest.raises(ExperienceError, match="unsupported"):
        dse_run(path, path.parent / "output")
    path.unlink()
    make_plan(dse_project)
    (workspace.parent / "design.v").write_text("changed")
    with pytest.raises(ExperienceError) as caught:
        dse_run(path, path.parent / "output")
    assert caught.value.code == "experience_source_changed"
    assert not (path.parent / "output").exists()


def test_dse_cli_exposes_project_workspace_defaults_and_json(dse_project):
    workspace, store, output = dse_project
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "dse",
            "plan",
            "--project",
            str(workspace.parent),
            "--workspace",
            "source",
            "--store",
            str(store),
            "--output",
            str(output),
            "--param",
            "floorplan.core_util=0.35",
            "--through-step",
            "postFloorplan",
            "--metric",
            "core_area",
            "--unit",
            "um^2",
            "--max-trials",
            "3",
            "--max-seconds",
            "60",
            "--trial-timeout",
            "30",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["experience"] == "dse_plan"


@pytest.mark.parametrize(
    "condition,expected",
    [("blocked", "blocked"), ("unknown", "unknown"), ("metric_missing", "unknown")],
)
def test_stage_checklist_and_objective_gate_only_the_prefix(
    dse_project, simulated_cli, monkeypatch, condition, expected
):
    from ecc_experience.dse.evidence import stage_acceptance

    _workspace, store, path = dse_project
    frozen = make_plan(dse_project)
    baseline_id = frozen["baseline_case_id"]
    if condition == "metric_missing":
        frozen["objective"]["id"] = "not-present"
    else:
        monkeypatch.setattr(
            "ecc_experience.dse.evidence._checklists",
            lambda *_args: [{"status": condition, "blocked": condition == "blocked"}],
        )
    result = stage_acceptance(baseline_id, store, frozen, exit_code=0)
    assert result["status"] == expected
    assert result["full_signoff"] == "not_evaluated"


def test_failure_during_pretrial_checks_keeps_intent_and_does_not_run(
    dse_project, simulated_cli, monkeypatch
):
    _workspace, _store, path = dse_project
    make_plan(dse_project)

    def changed(_plan):
        raise ExperienceError("Source changed", code="experience_source_changed")

    monkeypatch.setattr(trial, "check_source", changed)
    result = dse_run(path, path.parent / "output")
    assert result["exit_code"] == 21
    assert result["trials"][0]["candidate_id"] == "candidate-0001"
    assert result["trials"][0]["status"] == "failed"
    assert not simulated_cli
