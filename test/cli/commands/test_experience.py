import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from chipcompiler.engine.snapshot_qor import unavailable_qor_snapshot_extension

runner = CliRunner()


@pytest.mark.parametrize("subcommand,status", [("create", 0), ("report", 7)])
def test_campaign_utilities_preserve_json_and_exit_code(tmp_path, monkeypatch, subcommand, status):
    monkeypatch.chdir(tmp_path)
    calls = []

    def operation(source, output, **options):
        calls.append((source, output, options))
        return {"status": "created" if status == 0 else "unknown", "exit_code": status}

    monkeypatch.setattr(f"ecc_experience.api.campaign_{subcommand}", operation)
    selector = "--spec" if subcommand == "create" else "--manifest"
    result = runner.invoke(
        app,
        [
            "experience",
            "campaign",
            subcommand,
            selector,
            "input.json",
            "--output",
            "batch",
            "--json",
        ],
    )

    assert result.exit_code == status, result.output
    assert json.loads(result.stdout)[0]["exit_code"] == status
    assert calls == [("input.json", "batch", {} if subcommand == "create" else {"ledger": None})]


def test_optimize_uses_current_project_and_preserves_structured_failure(tmp_path, monkeypatch):
    (tmp_path / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "design_name": "sample",
                "root_path": str(tmp_path),
                "workspaces": [
                    {"workspace_id": name, "workspace_path": str(tmp_path / name)}
                    for name in ("baseline", "other")
                ],
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    calls = []

    def optimize(project, plan_path, store, output):
        calls.append((project, plan_path, store, output))
        return {"status": "timeout", "exit_code": 124}

    monkeypatch.setattr("ecc_experience.api.optimize", optimize)
    result = runner.invoke(
        app,
        [
            "experience",
            "optimize",
            "--store",
            str(tmp_path / "store"),
            "--plan",
            str(tmp_path / "plan.json"),
            "--output",
            str(tmp_path / "results"),
            "--json",
        ],
    )

    assert result.exit_code == 124, result.output
    assert json.loads(result.stdout)[0]["status"] == "timeout"
    assert Path(calls[0][0]) == tmp_path


def test_plan_passes_explicit_execution_limits(legacy_project, tmp_path, monkeypatch):
    project, workspace = legacy_project

    def plan(_workspace, _store, _output, *, limit, release, optimization):
        return {"optimization": optimization.model_dump()}

    monkeypatch.setattr("ecc_experience.api.plan", plan)
    result = runner.invoke(
        app,
        [
            "experience",
            "plan",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            "--store",
            str(tmp_path / "store"),
            "--output",
            str(tmp_path / "plan.json"),
            "--allow-param",
            "place.target_density",
            "--max-trials",
            "2",
            "--max-seconds",
            "60",
            "--trial-timeout",
            "30",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    limits = json.loads(result.stdout)[0]["optimization"]
    assert limits["allow_parameters"] == ["place.target_density"]
    assert limits["max_trials"] == 2


@pytest.fixture
def legacy_project(create_cli_project, create_flow_json):
    from pathlib import Path

    project = Path(create_cli_project())
    workspace = project / "sample-workspace"
    create_flow_json(str(workspace))
    return project, workspace


def test_experience_collect_uses_current_workspace_defaults(legacy_project, tmp_path, monkeypatch):
    project, workspace = legacy_project
    monkeypatch.chdir(workspace)
    result = runner.invoke(
        app, ["experience", "collect", "--store", str(tmp_path / "store"), "--json"]
    )
    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)[0]
    assert record["status"] == "created"
    assert record["source"]["workspace_root"] == str(workspace)
    assert record["validation_scope"] == "legacy_import"
    assert not (workspace / "home/engineering-snapshot.json").exists()


def test_experience_store_commands_work_outside_project(legacy_project, tmp_path, monkeypatch):
    project, workspace = legacy_project
    store_args = ["--store", str(tmp_path / "store"), "--json"]
    collected = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            *store_args,
        ],
    )
    assert collected.exit_code == 0, collected.output
    case_id = json.loads(collected.stdout)[0]["case_id"]
    monkeypatch.chdir(tmp_path)
    listing = runner.invoke(app, ["experience", "list", *store_args])
    assert listing.exit_code == 0
    assert [item["case_id"] for item in json.loads(listing.stdout)] == [case_id]
    shown = runner.invoke(app, ["experience", "show", case_id, *store_args])
    assert shown.exit_code == 0
    assert json.loads(shown.stdout)[0]["case_id"] == case_id
    verification = runner.invoke(app, ["experience", "verify", case_id, *store_args])
    assert verification.exit_code == 7
    assert json.loads(verification.stdout)[0]["status"] == "unknown"


def test_experience_verify_preserves_json_on_corrupt_case(legacy_project, tmp_path):
    project, workspace = legacy_project
    store = tmp_path / "store"
    args = ["--store", str(store), "--json"]
    result = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            *args,
        ],
    )
    assert result.exit_code == 0
    case_id = json.loads(result.stdout)[0]["case_id"]
    (store / "cases" / case_id / "case.json").write_text("{")
    result = runner.invoke(app, ["experience", "verify", *args])
    assert result.exit_code == 6
    assert json.loads(result.stdout)[0]["status"] == "fail"


def test_experience_busy_workspace_returns_20(legacy_project, tmp_path):
    project, workspace = legacy_project
    (workspace / "home/flow.json").write_text('{"steps": [{"state": "Ongoing"}]}')
    result = runner.invoke(
        app,
        [
            "experience",
            "collect",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            "--store",
            str(tmp_path / "store"),
            "--json",
        ],
    )
    assert result.exit_code == 20
    assert json.loads(result.stdout)[0]["error"] == "experience_workspace_busy"


def test_experience_json_plain_conflict_returns_usage_error(tmp_path):
    result = runner.invoke(
        app,
        [
            "experience",
            "list",
            "--store",
            str(tmp_path),
            "--json",
            "--plain",
        ],
    )
    assert result.exit_code == 2


def test_experience_recording_enable_status_disable(create_cli_project, tmp_path):
    project = create_cli_project()
    store = tmp_path / "experience-store"

    enabled = runner.invoke(
        app,
        [
            "experience",
            "enable",
            "--project",
            project,
            "--store",
            str(store),
            "--json",
        ],
    )
    assert enabled.exit_code == 0, enabled.output
    assert json.loads(enabled.stdout)[0]["enabled"] is True

    current = runner.invoke(app, ["experience", "status", "--project", project, "--json"])
    assert current.exit_code == 0, current.output
    payload = json.loads(current.stdout)[0]
    assert payload["configured"] is True
    assert payload["store"] == str(store.resolve())
    assert payload["outbox"]["pending"] == 0

    disabled = runner.invoke(app, ["experience", "disable", "--project", project, "--json"])
    assert disabled.exit_code == 0, disabled.output
    assert json.loads(disabled.stdout)[0]["enabled"] is False


def test_experience_recommend_is_read_only(legacy_project, tmp_path):
    project, workspace = legacy_project
    result = runner.invoke(
        app,
        [
            "experience",
            "recommend",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            "--store",
            str(tmp_path / "store"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    record = json.loads(result.stdout)[0]
    assert record["status"] == "insufficient_evidence"
    assert not (tmp_path / "store").exists()


def test_experience_plan_writes_insufficient_evidence_plan(legacy_project, tmp_path):
    project, workspace = legacy_project
    output = tmp_path / "plan.json"
    result = runner.invoke(
        app,
        [
            "experience",
            "plan",
            "--project",
            str(project),
            "--workspace",
            workspace.name,
            "--store",
            str(tmp_path / "store"),
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["status"] == "insufficient_evidence"
    assert json.loads(output.read_text())["execution_policy"]["auto_apply"] is False


def test_experience_evaluate_returns_structured_comparison(experience_workspace_factory, tmp_path):
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    baseline_workspace = experience_workspace_factory("baseline")
    candidate_workspace = experience_workspace_factory("candidate")
    for root, score in ((baseline_workspace, 90.0), (candidate_workspace, 100.0)):
        snapshot_path = root / "home/engineering-snapshot.json"
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["workspaceSpec"] = {
            "design": {"topModule": "sample"},
            "inputs": [{"inputId": "rtl", "role": "rtl"}],
        }
        snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
        qor = unavailable_qor_snapshot_extension("test fixture")
        qor["status"] = "available"
        qor.pop("reason")
        qor["score"] = score
        qor["scalarStatus"] = "GREEN"
        snapshot["qorSnapshotExtension"] = qor
        snapshot_path.write_text(json.dumps(snapshot))
    from ecc_experience.api import collect

    store = tmp_path / "store"
    baseline = collect(baseline_workspace, store).case
    candidate = collect(candidate_workspace, store).case
    result = runner.invoke(
        app,
        [
            "experience",
            "evaluate",
            "--store",
            str(store),
            "--baseline",
            baseline.case_id,
            "--candidate",
            candidate.case_id,
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["comparison"] == "improved"


def test_experience_release_create_and_verify(experience_workspace_factory, tmp_path):
    input_file = tmp_path / "design.v"
    input_file.write_text("module sample; endmodule")
    workspace = experience_workspace_factory("release")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)}}
    qor = unavailable_qor_snapshot_extension("test fixture")
    qor["status"] = "available"
    qor.pop("reason")
    qor["score"] = 95.0
    qor["scalarStatus"] = "GREEN"
    snapshot["qorSnapshotExtension"] = qor
    snapshot_path.write_text(json.dumps(snapshot))
    from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
    from ecc_experience.collection.collect import collect_committed_case
    from ecc_experience.knowledge.store import ExperienceStore

    store = tmp_path / "store"
    case = collect_committed_case(
        workspace,
        ExperienceStore(store),
        read_workspace_observation,
        attempt_id="attempt-test-release",
    ).case
    release = tmp_path / "release.json"
    created = runner.invoke(
        app,
        [
            "experience",
            "release",
            "create",
            "--store",
            str(store),
            "--case-id",
            case.case_id,
            "--output",
            str(release),
            "--json",
        ],
    )
    verified = runner.invoke(
        app,
        [
            "experience",
            "release",
            "verify",
            "--store",
            str(store),
            "--release",
            str(release),
            "--json",
        ],
    )

    assert created.exit_code == 0, created.output
    assert verified.exit_code == 0, verified.output
    assert json.loads(verified.stdout)[0]["status"] == "pass"


def test_experience_recording_rejects_store_inside_project(create_cli_project, tmp_path):
    project = create_cli_project()
    nested_store = Path(project) / "nested-store"
    result = runner.invoke(
        app,
        [
            "experience",
            "enable",
            "--project",
            project,
            "--store",
            str(nested_store),
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)[0]["error"] == "experience_project_invalid"


def test_campaign_validate_is_read_only(tmp_path):
    (tmp_path / "design-1").mkdir()
    manifest = tmp_path / "campaign.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": "campaign-1",
                "process_profile": "ics55",
                "store": "store",
                "output_root": "outputs",
                "knowledge_release_id": None,
                "mode": "baseline",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 1,
                    "timeout_seconds_per_trial": 60,
                },
                "designs": [
                    {
                        "id": "design-1",
                        "input": {"kind": "ecc-project", "path": "design-1"},
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["experience", "campaign", "validate", "--manifest", str(manifest), "--json"]
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["design_count"] == 1
    assert not (tmp_path / "outputs").exists()


def test_campaign_ledger_commands_initialize_record_and_status(tmp_path):
    (tmp_path / "design-1").mkdir()
    manifest = tmp_path / "campaign.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": "campaign-1",
                "process_profile": "ics55",
                "store": "store",
                "output_root": "outputs",
                "mode": "baseline",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 1,
                    "timeout_seconds_per_trial": 60,
                },
                "designs": [
                    {
                        "id": "design-1",
                        "input": {"kind": "ecc-project", "path": "design-1"},
                        "workspace": "baseline",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    initialized = runner.invoke(
        app, ["experience", "campaign", "init", "--manifest", str(manifest), "--json"]
    )
    assert initialized.exit_code == 0, initialized.output
    ledger = tmp_path / "outputs/campaign-ledger.json"
    recorded = runner.invoke(
        app,
        [
            "experience",
            "campaign",
            "record",
            "--ledger",
            str(ledger),
            "--design",
            "design-1",
            "--workspace",
            "baseline-001",
            "--status",
            "pass",
            "--trial-id",
            "trial-1",
            "--json",
        ],
    )
    current = runner.invoke(
        app,
        [
            "experience",
            "campaign",
            "status",
            "--manifest",
            str(manifest),
            "--json",
        ],
    )
    summary = runner.invoke(
        app,
        [
            "experience",
            "campaign",
            "summary",
            "--manifest",
            str(manifest),
            "--json",
        ],
    )
    assert recorded.exit_code == 0, recorded.output
    assert current.exit_code == 0, current.output
    assert summary.exit_code == 0, summary.output
    assert json.loads(current.stdout)[0]["counts"]["pass"] == 1
    assert json.loads(summary.stdout)[0]["evidence_counts"]["missing"] == 1


@pytest.mark.parametrize("command", ["show", "verify"])
def test_experience_rejects_invalid_case_id_as_usage_error(tmp_path, command):
    result = runner.invoke(
        app,
        [
            "experience",
            command,
            "../outside",
            "--store",
            str(tmp_path),
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stdout)[0]["error"] == "experience_case_id_invalid"
