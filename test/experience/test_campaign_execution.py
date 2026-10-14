import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import run_campaign
from ecc_experience.benchmark import execute, trial
from ecc_experience.benchmark.evidence import collect_trial
from ecc_experience.benchmark.ledger import record_trial, status
from ecc_experience.models import ExperienceError
from ecc_experience.optimization.process import Invocation


@pytest.fixture
def campaign(workspace_factory, tmp_path, monkeypatch):
    workspace = workspace_factory("input/source")
    project = workspace.parent
    rtl = project / "design.v"
    rtl.write_text("module sample; endmodule")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"name": "sample", "topModule": "sample"},
        "pdk": {"familyId": "ics55"},
        "flow": {"flowId": "rtl2gds"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
        "parameters": {"place.target_density": 0.5},
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(rtl)}}
    qor = snapshot["qorSnapshotExtension"]
    qor.update(status="available", score=90.0, scalarStatus="GREEN")
    qor.pop("reason")
    snapshot_path.write_text(json.dumps(snapshot))
    (project / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "sample",
                "root_path": str(project),
                "workspaces": [{"workspace_id": "source", "workspace_path": str(workspace)}],
            }
        )
    )
    manifest = tmp_path / "campaign.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": "test-campaign",
                "process_profile": "ics55",
                "mode": "baseline",
                "store": "store",
                "output_root": "output",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 2,
                    "timeout_seconds_per_trial": 30,
                },
                "designs": [
                    {
                        "id": "example",
                        "input": {"kind": "ecc-project", "path": "input"},
                        "workspace": "source",
                    }
                ],
            }
        )
    )
    monkeypatch.setattr(execute, "runtime_identity", lambda: {"version": "test"})
    return manifest, workspace


@pytest.fixture
def public_commands(monkeypatch):
    commands = []

    def invoke(self, arguments, *, deadline):
        commands.append(arguments)
        stdout = self.output / f"stdout-{len(commands)}.log"
        stderr = self.output / f"stderr-{len(commands)}.log"
        stdout.write_text("")
        stderr.write_text("")
        if arguments[0] == "init":
            project = Path(arguments[1])
            project.mkdir()
            (project / "ecc.toml").write_text("generated example config")
        elif arguments[:2] == ["workspace", "derive"]:
            project = Path(arguments[arguments.index("--project") + 1])
            source = Path(
                next(command for command in commands if command[:2] == ["workspace", "import"])[4]
            )
            shutil.copytree(source, project / arguments[3])
        elif arguments[0] == "run":
            run_id = arguments[arguments.index("--run-id") + 1]
            project = Path(arguments[arguments.index("--project") + 1])
            workspace = project / arguments[arguments.index("--workspace") + 1]
            (workspace / "log").mkdir()
            (workspace / "log" / f"{run_id}.log").write_text(f"ECC run {run_id} started\n")
        return Invocation(0, stdout, stderr)

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    monkeypatch.setattr(
        trial,
        "inspect_workspace",
        lambda *_args, **_kwargs: {
            "status": "passed",
            "qor_score": 90.0,
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 0,
        },
    )
    return commands


def test_baseline_uses_public_commands_and_resume_does_not_rerun(campaign, public_commands):
    manifest, source = campaign
    before = {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()}

    first = run_campaign(manifest)
    repeated = run_campaign(manifest, retry_failed=True)

    assert first["exit_code"] == repeated["exit_code"] == 0
    assert repeated["status"] == "complete"
    assert len(repeated["trials"]) == 1
    assert [command[0] for command in public_commands] == ["init", "workspace", "workspace", "run"]
    assert repeated["summary"]["evidence_counts"] == {
        "available": 1,
        "missing": 0,
        "fail": 0,
        "unknown": 0,
    }
    assert {str(path): path.read_bytes() for path in source.rglob("*") if path.is_file()} == before
    assert status(manifest)["designs"][0]["trial_count"] == 1
    verification_file = Path(first["trials"][0]["verification_file"])
    assert json.loads(verification_file.read_text())["status"] == "pass"


def test_failed_trials_require_explicit_retry_and_obey_budget(
    campaign, public_commands, monkeypatch
):
    manifest, _source = campaign
    monkeypatch.setattr(
        trial,
        "inspect_workspace",
        lambda *_args, **_kwargs: {
            "status": "blocked",
            "workspace_status_exit_code": 0,
            "signoff_exit_code": 6,
        },
    )

    first = run_campaign(manifest)
    skipped = run_campaign(manifest)
    retried = run_campaign(manifest, retry_failed=True)
    exhausted = run_campaign(manifest, retry_failed=True)

    assert [item["exit_code"] for item in (first, skipped, retried, exhausted)] == [6, 6, 6, 6]
    assert [len(item["trials"]) for item in (first, skipped, retried, exhausted)] == [1, 1, 2, 2]
    assert len({item["run_id"] for item in exhausted["trials"]}) == 2
    assert len([command for command in public_commands if command[0] == "run"]) == 2


def test_resume_rejects_input_or_runtime_changes(campaign, public_commands, monkeypatch):
    manifest, source = campaign
    run_campaign(manifest)
    (source.parent / "design.v").write_text("module changed; endmodule")
    with pytest.raises(ExperienceError, match="changed"):
        run_campaign(manifest)
    (source.parent / "design.v").write_text("module sample; endmodule")
    monkeypatch.setattr(execute, "runtime_identity", lambda: {"version": "changed"})
    with pytest.raises(ExperienceError, match="changed"):
        run_campaign(manifest)
    assert len(public_commands) == 4


def test_terminal_state_replays_missing_ledger_without_new_execution(campaign, public_commands):
    manifest, _source = campaign
    run_campaign(manifest)
    ledger = manifest.parent / "output/campaign-ledger.json"
    payload = json.loads(ledger.read_text())
    payload["designs"][0]["trials"] = []
    ledger.write_text(json.dumps(payload))

    recovered = run_campaign(manifest)

    assert recovered["exit_code"] == 0
    assert status(manifest)["designs"][0]["trial_count"] == 1
    assert len(public_commands) == 4


def test_unfinished_intent_is_never_taken_over(campaign, public_commands):
    manifest, _source = campaign
    run_campaign(manifest)
    path = manifest.parent / "output/campaign-run.json"
    payload = json.loads(path.read_text())
    payload["trials"][0]["status"] = "running"
    path.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError, match="Unfinished"):
        run_campaign(manifest, retry_failed=True)
    assert len(public_commands) == 4


@pytest.mark.parametrize("failure,expected", [(124, 124), (1, 6), ("cancel", 130)])
def test_command_failures_timeout_and_cancel_preserve_trial(
    campaign, public_commands, monkeypatch, failure, expected
):
    manifest, _source = campaign
    original = trial.CliRunner.invoke

    def invoke(self, arguments, *, deadline):
        if arguments[0] == "run":
            if failure == "cancel":
                raise KeyboardInterrupt
            return Invocation(failure, self.output / "failed.stdout", self.output / "failed.stderr")
        return original(self, arguments, deadline=deadline)

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    result = run_campaign(manifest)

    assert result["exit_code"] == expected
    assert result["trials"][0]["status"] in {"fail", "cancelled"}
    assert status(manifest)["designs"][0]["trial_count"] == 1


def test_source_change_during_execution_stops_campaign(campaign, public_commands, monkeypatch):
    manifest, source = campaign
    original = trial.CliRunner.invoke

    def invoke(self, arguments, *, deadline):
        result = original(self, arguments, deadline=deadline)
        if arguments[0] == "run":
            (source.parent / "design.v").write_text("module changed; endmodule")
        return result

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    result = run_campaign(manifest)

    assert result["exit_code"] == 21
    assert result["status"] == "stopped"
    assert result["trials"][0]["case_id"] is None


@pytest.mark.parametrize(
    "field,value", [("knowledge_release_id", "release-example"), ("concurrency", 2)]
)
def test_unsupported_execution_modes_rejected_before_output(
    campaign, public_commands, field, value
):
    manifest, _source = campaign
    payload = json.loads(manifest.read_text())
    if field == "concurrency":
        payload["budget"]["max_concurrent_flows"] = value
    else:
        payload[field] = value
    manifest.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError):
        run_campaign(manifest)
    assert public_commands == []
    assert not (manifest.parent / "output").exists()


def test_campaign_lock_blocks_another_runner_and_manual_record(
    campaign,
    public_commands,
    monkeypatch,
):
    manifest, _source = campaign
    original = trial.CliRunner.invoke

    def competing_operations():
        for operation in (
            lambda: run_campaign(manifest),
            lambda: record_trial(
                manifest.parent / "output/campaign-ledger.json",
                design_id="example",
                workspace="external",
                status="fail",
            ),
        ):
            with pytest.raises(ExperienceError) as caught:
                operation()
            assert caught.value.code == "experience_workspace_busy"

    def invoke(self, arguments, *, deadline):
        if arguments[0] == "run":
            execution = status(manifest)["execution"]
            assert execution["status"] == "running"
            assert len(execution["active_trials"]) == 1
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(competing_operations).result(timeout=10)
        return original(self, arguments, deadline=deadline)

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    result = run_campaign(manifest)
    assert result["exit_code"] == 0
    assert status(manifest)["designs"][0]["trial_count"] == 1


def test_busy_source_on_resume_keeps_busy_error(campaign, public_commands, monkeypatch):
    manifest, _source = campaign
    run_campaign(manifest)

    def prepare(*_args):
        raise ExperienceError("Source is active", code="experience_workspace_busy")

    monkeypatch.setattr(execute, "prepare", prepare)
    with pytest.raises(ExperienceError) as caught:
        run_campaign(manifest)
    assert caught.value.code == "experience_workspace_busy"


def test_source_query_lock_contention_is_busy_not_changed(campaign, public_commands, monkeypatch):
    from ecc_experience.benchmark import preparation

    manifest, _source = campaign
    original = trial.CliRunner.invoke

    def busy(*_args, **_kwargs):
        raise ExperienceError("A source query holds the lock", code="experience_workspace_busy")

    def invoke(self, arguments, *, deadline):
        result = original(self, arguments, deadline=deadline)
        if arguments[0] == "init":
            monkeypatch.setattr(preparation, "read_workspace_observation", busy)
        return result

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    result = run_campaign(manifest)

    assert result["exit_code"] == 20
    assert result["trials"][0]["status"] == "blocked"
    assert result["trials"][0]["reason"] == "experience_workspace_busy"
    assert len(public_commands) == 1


def test_unknown_evidence_blocks_acceptance(campaign, public_commands, monkeypatch):
    manifest, source = campaign
    snapshot = source / "home/engineering-snapshot.json"
    payload = json.loads(snapshot.read_text())
    payload["qorSnapshotExtension"]["score"] = None
    snapshot.write_text(json.dumps(payload))

    result = run_campaign(manifest)

    assert result["exit_code"] == 6
    assert result["trials"][0]["status"] == "blocked"
    assert result["trials"][0]["verification"]["status"] == "unknown"
    assert result["summary"]["evidence_counts"]["unknown"] == 1


def test_resume_rechecks_evidence_instead_of_trusting_pass_ledger(campaign, public_commands):
    manifest, _source = campaign
    first = run_campaign(manifest)
    case_id = first["trials"][0]["case_id"]
    case_root = manifest.parent / "store/cases" / case_id
    evidence = next((case_root / "evidence").iterdir())
    evidence.write_bytes(b"corrupted evidence")

    resumed = run_campaign(manifest)

    assert resumed["exit_code"] == 6
    assert resumed["status"] == "completed_with_evidence_issues"
    assert resumed["summary"]["evidence_counts"]["fail"] == 1
    assert len(public_commands) == 4


def test_failed_design_does_not_prevent_other_designs(campaign, public_commands, monkeypatch):
    manifest, _source = campaign
    payload = json.loads(manifest.read_text())
    payload["designs"].append({**payload["designs"][0], "id": "second"})
    manifest.write_text(json.dumps(payload))
    original = trial.CliRunner.invoke
    run_count = 0

    def invoke(self, arguments, *, deadline):
        nonlocal run_count
        if arguments[0] == "run":
            run_count += 1
            if run_count == 1:
                return Invocation(1, self.output / "failed.stdout", self.output / "failed.stderr")
        return original(self, arguments, deadline=deadline)

    monkeypatch.setattr(trial.CliRunner, "invoke", invoke)
    result = run_campaign(manifest)

    assert result["exit_code"] == 6
    assert [(item["design_id"], item["status"]) for item in result["trials"]] == [
        ("example", "fail"),
        ("second", "pass"),
    ]


@pytest.mark.parametrize(
    "aspect,density,accepted", [(0.8, 0.5, True), (0.9, 0.5, False), (0.8, 0.7, False)]
)
def test_runtime_geometry_requires_matching_tool_report(
    campaign, tmp_path, aspect, density, accepted
):
    _manifest, source = campaign
    baseline = read_workspace_observation(source)
    workspace = tmp_path / "executed"
    shutil.copytree(source, workspace)
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"]["parameters"].update(
        {
            "floorplan.aspect_ratio": aspect,
            "place.target_density": density,
        }
    )
    snapshot["flow"]["steps"].append({"name": "postFloorplan", "tool": "ecc", "state": "Success"})
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    report = workspace / "postFloorplan_ecc/feature/postFloorplan.db.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        json.dumps({"Design Layout": {"die_bounding_width": 8.0, "die_bounding_height": 10.0}})
    )

    if not accepted:
        with pytest.raises(ExperienceError, match="parameters differ"):
            collect_trial(workspace, str(tmp_path / "store"), baseline, "actual-run")
    else:
        result = collect_trial(workspace, str(tmp_path / "store"), baseline, "actual-run")
        assert result["verification"]["status"] == "pass"
        assert result["runtime_parameter_updates"]["floorplan.aspect_ratio"]["observed"] == 0.8
