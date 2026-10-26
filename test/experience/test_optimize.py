import json

import pytest

from ecc_experience.api import collect, optimize, plan
from ecc_experience.files import digest
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.policy import OptimizationLimits, parse_limits
from ecc_experience.optimization.process import Invocation


@pytest.fixture
def optimization_project(workspace_factory, tmp_path):
    workspace = workspace_factory()
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "pdk": {"familyId": "ics55"},
        "flow": {"flowId": "rtl2gds"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "parameters": {"place.target_density": 0.5, "design.frequency_mhz": 100.0},
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    snapshot_path.write_text(json.dumps(snapshot))
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "sample",
                "root_path": str(tmp_path),
                "workspaces": [
                    {"workspace_id": snapshot["workspaceId"], "workspace_path": str(workspace)}
                ],
            }
        )
    )
    store = tmp_path / "store"
    collect(workspace, store)
    limits = OptimizationLimits(
        allow_parameters=["place.target_density"],
        max_trials=2,
        max_seconds=60,
        trial_timeout_seconds=30,
    )
    plan_path = tmp_path / "plan.json"
    plan(workspace, store, plan_path, optimization=limits)
    return workspace, store, plan_path


@pytest.fixture
def fake_execution(monkeypatch):
    from ecc_experience.optimization import execute

    commands = []

    def invoke(self, arguments, *, deadline):
        commands.append(arguments)
        return Invocation(0, self.output / "stdout.log", self.output / "stderr.log")

    def inspect(*_args, **_kwargs):
        return {
            "status": "passed",
            "qor_score": 90.0,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 0,
        }

    def validate(workspace, _store, _baseline, parameters, run_id):
        return {
            "case_id": workspace.name,
            "verification": {"status": "pass", "integrity": "pass"},
            "attempt_id": run_id,
        }

    monkeypatch.setattr(execute.CliRunner, "invoke", invoke)
    monkeypatch.setattr(execute, "inspect_workspace", inspect)
    monkeypatch.setattr(execute, "validate_trial", validate)
    monkeypatch.setattr(execute, "check_trial_configuration", lambda *_args, **_kwargs: None)
    return commands


def test_optimize_reserves_fresh_workspace_and_preserves_baseline(
    optimization_project, tmp_path, fake_execution
):
    workspace, store, plan_path = optimization_project
    before = (workspace / "home/engineering-snapshot.json").read_bytes()

    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["status"] == "complete"
    assert result["exit_code"] == 0
    assert result["improved"] is False
    assert len(result["trials"]) == 1
    assert result["trials"][0]["workspace"] != result["fresh_validation"]["workspace"]
    assert result["trials"][0]["run_id"] != result["fresh_validation"]["run_id"]
    assert len([command for command in fake_execution if command[0] == "run"]) == 2
    assert (workspace / "home/engineering-snapshot.json").read_bytes() == before
    assert json.loads((tmp_path / "output/result.json").read_text())["status"] == "complete"


def test_optimize_refuses_modified_plan_before_mutation(
    optimization_project, tmp_path, fake_execution
):
    _workspace, store, plan_path = optimization_project
    payload = json.loads(plan_path.read_text())
    payload["optimization"]["max_trials"] = 99
    plan_path.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="fingerprint"):
        optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert fake_execution == []
    assert not (tmp_path / "output").exists()


def test_optimize_refuses_changed_inputs(optimization_project, tmp_path, fake_execution):
    _workspace, store, plan_path = optimization_project
    (tmp_path / "design.v").write_text("module changed; endmodule")

    with pytest.raises(ExperienceError, match="changed"):
        optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert fake_execution == []


def test_optimize_requires_explicit_limits(optimization_project, tmp_path, fake_execution):
    workspace, store, plan_path = optimization_project
    plan(workspace, store, plan_path)

    with pytest.raises(ExperienceError):
        optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert fake_execution == []


@pytest.mark.parametrize(
    "key", ["design.frequency_mhz", "sta.max_paths", "pdk.root", "place.detailed_place_command"]
)
def test_limits_refuse_constraint_and_command_parameters(key):
    with pytest.raises(ExperienceError):
        parse_limits(
            {
                "allow_parameters": [key],
                "max_trials": 2,
                "max_seconds": 60,
                "trial_timeout_seconds": 30,
            }
        )


def test_optimize_skips_changes_outside_allowlist(optimization_project, tmp_path, fake_execution):
    workspace, store, plan_path = optimization_project
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
    from ecc_experience.optimization.policy import eligible_candidates, read_execution_plan

    payload, limits = read_execution_plan(plan_path, store)
    baseline = read_workspace_observation(workspace)
    baseline.facts["workspaceSpec"]["parameters"]["design.frequency_mhz"] = 200.0
    selected, skipped = eligible_candidates(payload, limits, baseline, store)

    assert selected == []
    assert skipped[0]["reason"] == "changes_outside_allowlist"


def test_optimize_does_not_run_fresh_after_timeout(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    _workspace, store, plan_path = optimization_project
    from ecc_experience.optimization import execute

    def invoke(self, arguments, *, deadline):
        fake_execution.append(arguments)
        return Invocation(124, self.output / "stdout.log", self.output / "stderr.log")

    monkeypatch.setattr(execute.CliRunner, "invoke", invoke)
    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 124
    assert result["fresh_validation"] is None
    assert len(result["trials"]) == 1


def test_optimize_requires_fresh_quality_gate(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    _workspace, store, plan_path = optimization_project
    from ecc_experience.optimization import execute

    def inspect(_project, workspace, *_args, **_kwargs):
        return {
            "status": "blocked" if workspace.name.endswith("_fresh") else "passed",
            "qor_score": 91.0,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 0,
        }

    monkeypatch.setattr(execute, "inspect_workspace", inspect)
    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["status"] == "fresh_validation_failed"
    assert result["exit_code"] == 6


def test_optimize_records_interrupted_workspace(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    _workspace, store, plan_path = optimization_project
    from ecc_experience.optimization import execute

    def invoke(self, arguments, *, deadline):
        raise KeyboardInterrupt

    monkeypatch.setattr(execute.CliRunner, "invoke", invoke)
    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 130
    assert result["trials"][0]["status"] == "cancelled"
    assert result["trials"][0]["workspace_id"]
    assert json.loads((tmp_path / "output/result.json").read_text())["exit_code"] == 130


def test_plan_fingerprint_includes_insufficient_evidence_reason(workspace_factory, tmp_path):
    result = plan(workspace_factory(), tmp_path / "store", tmp_path / "plan.json")
    identity = {
        key: value
        for key, value in result.items()
        if key not in {"plan", "created_at", "plan_fingerprint"}
    }
    assert result["plan_fingerprint"] == digest(identity)


def test_plan_rejects_candidates_outside_bound_release(optimization_project, monkeypatch):
    from ecc_experience.optimization.policy import plan_identity, read_execution_plan

    _workspace, store, plan_path = optimization_project
    payload = json.loads(plan_path.read_text())
    payload["query"]["release"] = "selected-release.json"
    payload["release_id"] = "release-selected"
    payload["plan_fingerprint"] = plan_identity(payload)
    plan_path.write_text(json.dumps(payload))
    monkeypatch.setattr(
        "ecc_experience.optimization.policy.verify_release",
        lambda *_args: {
            "status": "pass",
            "release_id": "release-selected",
            "cases": [{"case_id": "other-case"}],
        },
    )

    with pytest.raises(ExperienceError, match="outside"):
        read_execution_plan(plan_path, store)


def test_default_additions_keep_old_workspace_compatible():
    from ecc_experience.optimization.policy import configuration_differences

    assert configuration_differences({}, {"sta.max_parallel_corners": 1}) == set()
    assert configuration_differences({}, {"sta.max_parallel_corners": 2}) == {
        "sta.max_parallel_corners"
    }


def test_configuration_differences_ignores_only_workspace_local_paths():
    from ecc_experience.optimization.policy import configuration_differences

    baseline = {
        "emir.technology_file_path": "/tmp/design/baseline/config/tech",
        "sta.liberty": ["/technology/timing.lib"],
    }
    candidate = {
        "emir.technology_file_path": "/tmp/design/warmseed/config/tech",
        "sta.liberty": ["/technology/timing.lib"],
    }

    assert (
        configuration_differences(
            baseline,
            candidate,
            baseline_root="/tmp/design/baseline",
            candidate_root="/tmp/design/warmseed",
        )
        == set()
    )

    candidate["sta.liberty"] = ["/other-technology/timing.lib"]
    assert configuration_differences(
        baseline,
        candidate,
        baseline_root="/tmp/design/baseline",
        candidate_root="/tmp/design/warmseed",
    ) == {"sta.liberty"}


def test_baseline_unknown_does_not_block_execution(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    from ecc_experience.optimization import execute

    workspace, store, plan_path = optimization_project

    def inspect(_project, current, *_args, **_kwargs):
        baseline = current == workspace
        return {
            "status": "blocked" if baseline else "passed",
            "qor_score": None if baseline else 92.0,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 6 if baseline else 0,
        }

    monkeypatch.setattr(execute, "inspect_workspace", inspect)
    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 0
    assert result["score_delta"] is None
    assert result["improved"] is None
    assert result["baseline_evidence"]["status"] == "blocked"


@pytest.mark.parametrize("observed_density", [0.6, None])
def test_optimize_applies_only_allowed_observed_changes(
    optimization_project, workspace_factory, tmp_path, fake_execution, observed_density
):
    from chipcompiler.data.parameter_schema import lookup_schema

    workspace, store, plan_path = optimization_project
    observed = workspace_factory("observed")
    source = json.loads((workspace / "home/engineering-snapshot.json").read_text())
    snapshot_path = observed / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = source["workspaceSpec"]
    snapshot["workspaceBindings"] = source["workspaceBindings"]
    if observed_density is None:
        snapshot["workspaceSpec"]["parameters"].pop("place.target_density")
        expected_density = lookup_schema("place.target_density").default
    else:
        snapshot["workspaceSpec"]["parameters"]["place.target_density"] = observed_density
        expected_density = observed_density
    snapshot["qorSnapshotExtension"].update(status="available", score=95.0, scalarStatus="GREEN")
    snapshot["qorSnapshotExtension"].pop("reason", None)
    snapshot_path.write_text(json.dumps(snapshot))
    collect(observed, store)
    limits = OptimizationLimits(
        allow_parameters=["place.target_density"],
        max_trials=2,
        max_seconds=60,
        trial_timeout_seconds=30,
    )
    plan(workspace, store, plan_path, optimization=limits)

    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 0
    assert result["trials"][0]["parameters"] == {"place.target_density": expected_density}
    applied = [command for command in fake_execution if command[:2] == ["param", "apply"]]
    assert len(applied) == 2
    assert all(f"place.target_density={expected_density}" in command for command in applied)
    assert result["stop_reason"] == "trial_budget"


def test_failed_flow_is_recorded_and_collected_without_promoting(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    from ecc_experience.optimization import execute

    _workspace, store, plan_path = optimization_project
    collected = []

    def invoke(self, arguments, *, deadline):
        return Invocation(
            1 if arguments[0] == "run" else 0, self.output / "stdout", self.output / "stderr"
        )

    def inspect(*_args, **kwargs):
        return {
            "status": "failed" if kwargs.get("exit_code") else "passed",
            "qor_score": None,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 6,
        }

    def validate(workspace, *_args):
        collected.append(workspace)
        return {"case_id": "failed-case", "verification": {"status": "unknown"}}

    monkeypatch.setattr(execute.CliRunner, "invoke", invoke)
    monkeypatch.setattr(execute, "inspect_workspace", inspect)
    monkeypatch.setattr(execute, "validate_trial", validate)
    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 6
    assert result["trials"][0]["status"] == "failed"
    assert result["trials"][0]["case_id"] == "failed-case"
    assert len(collected) == 1
    assert result["winner"] is None


def test_changed_trial_inputs_stop_before_fresh_validation(
    optimization_project, tmp_path, fake_execution, monkeypatch
):
    from ecc_experience.optimization import execute

    _workspace, store, plan_path = optimization_project

    def changed_inputs(*_args):
        raise ExperienceError("Trial inputs changed", code="experience_source_changed")

    monkeypatch.setattr(execute, "validate_trial", changed_inputs)

    result = optimize(tmp_path, plan_path, store, tmp_path / "output")

    assert result["exit_code"] == 21
    assert result["status"] == "stopped"
    assert result["stop_reason"] == "experience_source_changed"
    assert len(result["trials"]) == 1
    assert result["fresh_validation"] is None
    assert result["winner"] is None
