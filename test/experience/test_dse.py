import copy
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

    def invoke(self, arguments, *, deadline, on_prepared=None):
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


@pytest.fixture
def version2_spec(dse_project, monkeypatch):
    from ecc_experience.dse import execute2

    workspace, _store, path = dse_project
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["signoffAssessment"] = {"status": "ready"}
    snapshot["checklist"] = {"items": [{"state": "pass", "blocked": False}]}
    snapshot["qorSnapshotExtension"]["feasibility"]["status"] = "PASS"
    snapshot_path.write_text(json.dumps(snapshot))
    spec = path.parent / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "strategy": "adaptive",
                "seed": 42,
                "space": {"floorplan.core_util": {"range": [0.3, 0.4], "step": 0.05}},
                "objectives": [{"metric": "core_area", "unit": "um^2", "direction": "minimize"}],
                "rungs": [{"through_step": "postFloorplan", "promote_count": 1}],
                "limits": {"max_trials": 5, "max_seconds": 60, "trial_timeout_seconds": 30},
            }
        )
    )
    monkeypatch.setattr(
        execute2,
        "inspect_workspace",
        lambda *_args, **_kwargs: {"status": "passed", "qor_score": 90.0},
    )
    return spec


def test_version2_adaptive_full_fresh_report_and_idempotent_resume(
    dse_project, simulated_cli, version2_spec
):
    from ecc_experience.dse.report import report_dse

    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    assert frozen["schema"] == "ecc-experience-stage-dse-plan/2"
    output = path.parent / "output"
    result = dse_run(path, output)
    assert (result["status"], result["exit_code"]) == ("complete", 0), result
    assert len(result["trials"]) == 3
    assert result["trials"][0]["decision"]["reason"] == "space_center"
    before = len(simulated_cli)
    assert dse_run(path, output, resume=True) == result
    assert len(simulated_cli) == before
    report = report_dse(path, output / "result.json", path.parent / "report")
    assert len(report["feedback_case_ids"]) == 2
    assert report["budget"]["executed_trials"] == 5
    assert len(report["pareto_front"]) == 3
    assert report["safe_to_apply"] is False


@pytest.mark.parametrize("change", ["budget", "order", "polarity", "axis"])
def test_version2_rejects_invalid_spec_before_execution(dse_project, version2_spec, change):
    workspace, store, path = dse_project
    payload = json.loads(version2_spec.read_text())
    if change == "budget":
        payload["strategy"] = "grid"
        payload["limits"]["max_trials"] = 3
    elif change == "order":
        payload["rungs"] *= 2
    elif change == "polarity":
        payload["objectives"][0]["direction"] = "maximize"
    else:
        payload["space"]["floorplan.core_util"]["step"] = 0
    version2_spec.write_text(json.dumps(payload))
    with pytest.raises(ExperienceError):
        dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    assert not path.exists()


def test_version2_rungs_pareto_manual_selection_and_replay(
    dse_project, simulated_cli, version2_spec
):
    from ecc_experience.dse.report import report_dse

    workspace, store, path = dse_project
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["flow"]["steps"].insert(
        2,
        {
            "name": "place",
            "tool": "dreamplace",
            "state": "Success",
            "checklist_status": {"status": "passed", "blocked": False},
        },
    )
    reference = "place_dreamplace/analysis/qor_metrics.json"
    report_path = workspace / reference
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": "place",
                "tool": "dreamplace",
                "status": "success",
                "integrity": {"status": "pass"},
                "metrics": [{"id": "place_hpwl", "value": 100, "unit": "um"}],
            }
        )
    )
    snapshot["artifacts"].append(
        {
            "artifactId": "artifact-"
            + hashlib.sha256(f"{snapshot['workspaceId']}\0{reference}".encode()).hexdigest()[:32],
            "reference": reference,
            "kind": "qor_metrics",
            "stepId": "place",
            "availability": "available",
        }
    )
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    settings = json.loads(version2_spec.read_text())
    area = settings["objectives"][0]
    settings["objectives"] = [
        {"metric": "place_hpwl", "unit": "um", "direction": "minimize"},
        {**area, "step": "postFloorplan"},
    ]
    settings["rungs"] = [
        {"through_step": "postFloorplan", "promote_count": 2, "objectives": [area]},
        {"through_step": "place", "promote_count": 1},
    ]
    settings["limits"]["max_trials"] = 7
    version2_spec.write_text(json.dumps(settings))
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    output = path.parent / "output"
    result = dse_run(path, output)
    assert (result["status"], result["exit_code"]) == ("selection_required", 7), result
    assert len(result["trials"]) == 5
    assert len([command for command in simulated_cli if command[0] == "run"]) == 5
    chosen = result["pareto_front"][0]
    result = dse_run(path, output, resume=True, select=chosen)
    assert (result["status"], result["exit_code"]) == ("complete", 0), result
    assert len([command for command in simulated_cli if command[0] == "run"]) == 7
    summary = report_dse(path, output / "result.json", path.parent / "summary")
    assert len(summary["pareto_front"]) == 2
    assert summary["selection"]["candidate"] == chosen
    assert len(summary["promotions"]) == 1
    payload = json.loads((output / "result.json").read_text())
    payload["trials"][0]["objective_values"] = [0]
    (output / "result.json").write_text(json.dumps(payload))
    with pytest.raises(ExperienceError, match="immutable"):
        dse_run(path, output, resume=True)


def test_version2_resume_replays_completed_history_without_rerunning(
    dse_project, simulated_cli, version2_spec, monkeypatch
):
    from ecc_experience.dse import execute2

    workspace, store, path = dse_project
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    original = execute2.propose

    def interrupt_after_first(plan, history):
        if len(history) == 1:
            raise KeyboardInterrupt
        return original(plan, history)

    monkeypatch.setattr(execute2, "propose", interrupt_after_first)
    interrupted = dse_run(path, path.parent / "resumed")
    assert (interrupted["status"], interrupted["exit_code"], len(interrupted["trials"])) == (
        "cancelled",
        130,
        1,
    )
    monkeypatch.setattr(execute2, "propose", original)
    resumed = dse_run(path, path.parent / "resumed", resume=True)
    uninterrupted = dse_run(path, path.parent / "uninterrupted")
    assert resumed["status"] == uninterrupted["status"] == "complete"
    assert [row["decision"] for row in resumed["trials"]] == [
        row["decision"] for row in uninterrupted["trials"]
    ]
    assert len([command for command in simulated_cli if command[0] == "run"]) == 10


def test_version2_equal_budget_receipt_and_warm_seed_filters(
    dse_project, simulated_cli, version2_spec, monkeypatch
):
    from ecc_experience.api import dse_compare
    from ecc_experience.dse import warm_start

    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    adaptive = dse_run(path, path.parent / "adaptive")
    settings = json.loads(version2_spec.read_text())
    settings["strategy"] = "grid"
    version2_spec.write_text(json.dumps(settings))
    grid_plan = path.parent / "grid-plan.json"
    dse_plan(workspace.parent, workspace, store, grid_plan, spec=version2_spec)
    dse_run(grid_plan, path.parent / "grid")
    receipt = dse_compare(
        path,
        path.parent / "adaptive/result.json",
        grid_plan,
        path.parent / "grid/result.json",
        path.parent / "comparison.json",
    )
    assert receipt["status"] == "observed_only"
    assert [row["budget"]["executed_trials"] for row in receipt["pairs"]] == [5, 5]
    assert receipt["benefit_status"] == "not_established"
    frozen["release"] = "explicit-release.json"
    frozen["baseline_case_id"] = adaptive["fresh_validation"]["case_id"]
    repository = warm_start.ExperienceStore(store)
    read_case = warm_start.ExperienceStore.read
    baseline = repository.read(frozen["baseline_case_id"])
    configurations = {
        "compatible": {"floorplan.core_util": 0.35},
        "outside": {"floorplan.core_util": 0.9},
        "other_knob": {"floorplan.core_util": 0.35, "place.target_density": 0.4},
        "other_library": {"floorplan.core_util": 0.35},
    }
    for parameters in configurations.values():
        parameters["sta.liberty"] = ["/technology/timing.lib"]
    configurations["other_library"]["sta.liberty"] = ["/other-technology/timing.lib"]
    baseline.facts["workspaceSpec"]["parameters"]["sta.liberty"] = ["/technology/timing.lib"]

    def observed_case(repository, case_id):
        if case_id == frozen["baseline_case_id"]:
            return baseline
        if case_id not in configurations:
            return read_case(repository, case_id)
        facts = {**baseline.facts, "workspaceSpec": {"parameters": configurations[case_id]}}
        return baseline.model_copy(update={"facts": facts})

    monkeypatch.setattr(warm_start.ExperienceStore, "read", observed_case)
    monkeypatch.setattr(
        warm_start,
        "match_cases",
        lambda *_args, **_kwargs: {
            "matches": [
                {
                    "case_id": "compatible",
                    "distance": 0.0,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.35}},
                },
                {
                    "case_id": "outside",
                    "distance": 0.1,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.9}},
                },
                {
                    "case_id": "other_knob",
                    "distance": 0.2,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {
                        "values": {"floorplan.core_util": 0.35, "place.target_density": 0.4}
                    },
                },
                {
                    "case_id": "other_library",
                    "distance": 0.0,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.35}},
                },
            ]
        },
    )
    seeds = warm_start.freeze_warm_start(frozen, 3)
    assert [seed["case_id"] for seed in seeds["seeds"]] == ["compatible"]


def test_warm_start_cross_design_requires_applied_evidence_and_records_provenance(
    dse_project, version2_spec, monkeypatch
):
    from ecc_experience.dse import warm_start

    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    repository = warm_start.ExperienceStore(store)
    baseline = repository.read(frozen["baseline_case_id"])
    baseline_facts = copy.deepcopy(baseline.facts)
    baseline_facts["experienceExecutionContext"] = {"runtime": frozen["runtime"]}
    baseline = baseline.model_copy(update={"facts": baseline_facts})

    def observed(core_util):
        facts = copy.deepcopy(baseline_facts)
        facts["workspaceSpec"]["parameters"]["floorplan.core_util"] = core_util
        return baseline.model_copy(update={"facts": facts})

    observed_cases = {"applied": observed(0.35), "configured": observed(0.4)}

    def read_case(_repository, case_id):
        if case_id == baseline.case_id:
            return baseline
        return observed_cases[case_id]

    monkeypatch.setattr(warm_start.ExperienceStore, "read", read_case)
    monkeypatch.setattr(
        warm_start,
        "match_cases",
        lambda *_args, **_kwargs: {
            "matches": [
                {
                    "case_id": "applied",
                    "distance": 0.2,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.35}},
                    "match_quality": "compatible_design",
                    "confidence": "experimental",
                    "feature_coverage": 0.9,
                    "parameter_evidence_level": "applied",
                },
                {
                    "case_id": "configured",
                    "distance": 0.1,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.4}},
                    "match_quality": "compatible_design",
                    "confidence": "experimental",
                    "feature_coverage": 0.9,
                    "parameter_evidence_level": "configured",
                },
                {
                    "case_id": "same_input",
                    "distance": 0.0,
                    "compatibility": "selected_process_tool_analysis_match",
                    "parameters": {"values": {"floorplan.core_util": 0.3}},
                    "match_quality": "exact_input",
                    "same_input_content": True,
                    "confidence": "observed_only",
                    "feature_coverage": 1.0,
                    "parameter_evidence_level": "applied",
                },
            ]
        },
    )
    frozen["release"] = "release.json"
    frozen["release_id"] = "release-test"
    frozen["warm_start"]["experimental_cross_design"] = True

    result = warm_start.freeze_warm_start(frozen, 3)

    assert [seed["case_id"] for seed in result["seeds"]] == ["applied"]
    seed = result["seeds"][0]
    assert seed["confidence"] == "experimental"
    assert seed["feature_coverage"] == 0.9
    assert seed["provenance"] == {
        "release": "release.json",
        "release_id": "release-test",
        "case_id": "applied",
        "distance": 0.2,
        "feature_coverage": 0.9,
        "confidence": "experimental",
    }


def test_dse_summary_exports_only_verified_feedback(dse_project, simulated_cli):
    from ecc_experience.dse.report import report_dse
    from ecc_experience.knowledge.release import verify_release

    _workspace, store, path = dse_project
    make_plan(dse_project)
    output = path.parent / "output"
    result = dse_run(path, output)
    summary = report_dse(path, output / "result.json", path.parent / "summary")
    assert summary["status"] == "complete"
    assert summary["convergence"]["screened_candidates"] == 1
    assert summary["convergence"]["fresh_passed"] is True
    assert len(summary["feedback_case_ids"]) == 2
    assert result["stage_winner"]["case_id"] not in summary["feedback_case_ids"]
    assert verify_release(path.parent / "summary/feedback-release.json", store)["status"] == "pass"
    result["fresh_validation"]["qor_score"] = 9999.0
    (output / "result.json").write_text(json.dumps(result))
    with pytest.raises(ExperienceError, match="QoR does not match"):
        report_dse(path, output / "result.json", path.parent / "rejected-summary")
    assert not (path.parent / "rejected-summary").exists()


def test_model_selection_still_requires_full_and_fresh(dse_project, simulated_cli, monkeypatch):
    _workspace, _store, path = dse_project
    make_plan(
        dse_project,
        parameters=["floorplan.core_util=0.35,0.4"],
        limits={"max_trials": 4, "max_seconds": 60, "trial_timeout_seconds": 30},
    )
    monkeypatch.setattr(execute, "check_model", lambda *_args: {"release_id": "model-test"})
    monkeypatch.setattr(
        execute,
        "predict_trial",
        lambda _plan, record, *_args: {
            "prediction": {
                "prediction": 100.0 if record["parameters"]["floorplan.core_util"] == 0.4 else 90.0
            }
        },
    )
    result = dse_run(path, path.parent / "model-output", model_release=path.parent / "model.json")
    assert result["status"] == "complete"
    assert result["selection_policy"] == "predicted_final_qor"
    assert result["stage_winner"]["parameters"] == {"floorplan.core_util": 0.4}
    assert result["full_validation"]["status"] == result["fresh_validation"]["status"] == "passed"
    assert result["safe_to_apply"] is False


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
