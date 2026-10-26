import json
import time
import tomllib

import pytest

from ecc_experience.api import dse_plan, dse_run
from ecc_experience.dse.plan import read_dse_plan
from ecc_experience.dse.trial import execute_trial
from ecc_experience.files import digest
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import CliRunner, Invocation
from test.experience import test_dse as fixtures

dse_project = fixtures.dse_project
simulated_cli = fixtures.simulated_cli
version2_spec = fixtures.version2_spec


@pytest.mark.parametrize("corruption", ["seed", "future_objective", "late_parameter"])
def test_resealed_plan_still_obeys_runtime_boundaries(dse_project, version2_spec, corruption):
    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    if corruption == "seed":
        frozen["algorithm"]["seed"] = -1
    elif corruption == "future_objective":
        frozen["objectives"][0]["step"] = "route"
        frozen["rungs"][0]["objectives"] = frozen["objectives"]
    else:
        frozen["space"] = {"cts.max_fanout": [16]}
        frozen["screening_trials"] = 1
    frozen["plan_fingerprint"] = digest(
        {key: value for key, value in frozen.items() if key != "plan_fingerprint"}
    )
    path.write_text(json.dumps(frozen))
    with pytest.raises(ExperienceError):
        read_dse_plan(path)


@pytest.mark.parametrize(
    "corruption",
    ["missing_fresh", "validation_mode", "delta", "comparison", "front", "shape"],
)
def test_completed_result_cannot_hide_missing_or_changed_evidence(
    dse_project, version2_spec, simulated_cli, corruption
):
    workspace, store, path = dse_project
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    output = path.parent / "output"
    result = dse_run(path, output)
    assert result["status"] == "complete", result
    if corruption == "missing_fresh":
        result["fresh_validation"] = None
    elif corruption == "validation_mode":
        result["full_validation"]["mode"] = "screen"
    elif corruption == "delta":
        result["score_delta"] = 1000
    elif corruption == "comparison":
        result["baseline_comparison"]["reasons"] = []
    elif corruption == "front":
        result["pareto_front"] = []
    else:
        result["trials"] = [None]
    (output / "result.json").write_text(json.dumps(result))
    calls = len(simulated_cli)
    with pytest.raises(ExperienceError):
        dse_run(path, output, resume=True)
    assert len(simulated_cli) == calls


def test_baseline_comparison_reports_runtime_mismatch(dse_project, version2_spec, monkeypatch):
    from ecc_experience.dse.audit import baseline_comparison
    from ecc_experience.knowledge.store import ExperienceStore

    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    repository = ExperienceStore(store)
    baseline = repository.read(frozen["baseline_case_id"])
    observed = {
        "status": "passed",
        "qor_score": baseline.facts["qorSnapshotExtension"]["score"],
    }
    read_case = ExperienceStore.read

    def read_old_runtime(self, case_id):
        selected = read_case(self, case_id)
        if case_id != frozen["baseline_case_id"]:
            return selected
        context = {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": selected.source.attempt_id,
            "runtime": {"ecc": "older-runtime"},
        }
        return selected.model_copy(
            update={"facts": {**selected.facts, "experienceExecutionContext": context}}
        )

    monkeypatch.setattr(ExperienceStore, "read", read_old_runtime)
    compared = baseline_comparison(frozen, observed)
    assert compared["status"] == "unavailable"
    assert compared["runtime_match"] is False
    assert "baseline_runtime_mismatch" in compared["reasons"]


def test_resume_does_not_replenish_per_trial_time(dse_project, version2_spec, monkeypatch):
    workspace, store, path = dse_project
    dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    frozen, limits = read_dse_plan(path)
    candidate = {
        "candidate_id": "candidate-0001",
        "parameters": {"floorplan.core_util": 0.3},
        "sets": ["floorplan.core_util=0.3"],
    }
    identity = "dse_0123456789abcdef"
    record = {
        **candidate,
        "workspace_id": identity,
        "workspace": str(workspace.parent / identity),
        "run_id": "frozen-attempt",
        "mode": "screen",
        "status": "running",
        "commands": [],
        "collection_status": "not_attempted",
        "elapsed_seconds": limits.trial_timeout_seconds,
    }

    def exhausted(self, _arguments, *, deadline, **_kwargs):
        assert deadline <= time.monotonic()
        return Invocation(124, self.output / "stdout", self.output / "stderr")

    monkeypatch.setattr(CliRunner, "invoke", exhausted)
    execute_trial(
        frozen,
        candidate,
        limits,
        CliRunner(path.parent, time.monotonic() + 60),
        record,
        lambda: None,
        mode="screen",
        resume=True,
    )
    assert record["status"] == "timeout"
    assert record["elapsed_seconds"] >= limits.trial_timeout_seconds


def test_durable_parameter_apply_executes_public_cli(tmp_path, minimal_ics55_pdk_factory):
    from chipcompiler.cli.project.toml_edit import set_pdk_root

    deadline = time.monotonic() + 30
    project = tmp_path / "project"
    runner = CliRunner(tmp_path, deadline, durable_receipts=True)
    initialized = runner.invoke(
        ["init", str(project), "--design-name", "sample", "--plain"], deadline=deadline
    )
    assert initialized.exit_code == 0, initialized.stdout.read_text()
    pdk = minimal_ics55_pdk_factory(tmp_path / "pdk")
    config_path = project / "ecc.toml"
    config_path.write_text(set_pdk_root(config_path.read_text(), str(pdk)))
    arguments = [
        "param",
        "apply",
        "--project",
        str(project),
        "--set",
        "floorplan.core_util=0.35",
        "--plain",
    ]
    result = runner.invoke(arguments, deadline=deadline)
    assert result.exit_code == 0, result.stdout.read_text()
    configuration = tomllib.loads((project / "ecc.toml").read_text())
    assert configuration["params"]["floorplan"]["core_util"] == 0.35


def test_explicit_baseline_binds_verified_execution_of_the_same_workspace(
    dse_project, version2_spec, simulated_cli
):
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
    from ecc_experience.collection.collect import collect_committed_case
    from ecc_experience.dse.baseline import bind_baseline
    from ecc_experience.knowledge.store import ExperienceStore

    workspace, store, path = dse_project
    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)
    result = dse_run(path, path.parent / "output")
    final = result["fresh_validation"]
    observed = collect_committed_case(
        final["workspace"], ExperienceStore(store), read_workspace_observation
    ).case
    bound = bind_baseline(observed, final["case_id"], store)
    assert bound.case_id == final["case_id"]
    assert bound.source.attempt_id == final["run_id"]
    with pytest.raises(ExperienceError, match="exact committed workspace"):
        bind_baseline(observed, frozen["baseline_case_id"], store)


def test_project_configuration_excludes_runtime_records_but_protects_objectives(dse_project):
    from ecc_experience.dse.plan import project_configuration

    workspace, _store, _plan = dse_project
    path = workspace.parent / "project.json"
    frozen = project_configuration(workspace.parent)
    document = json.loads(path.read_text())
    document["runtime_processes"] = {"another_workspace": {"run_id": "active"}}
    path.write_text(json.dumps(document))
    assert project_configuration(workspace.parent) == frozen
    document["objectives"] = {"primary": "area"}
    path.write_text(json.dumps(document))
    assert project_configuration(workspace.parent) != frozen
