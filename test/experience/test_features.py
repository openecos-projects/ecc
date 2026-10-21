import hashlib
import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import features
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


@pytest.fixture
def stage_case(workspace_factory, tmp_path):
    workspace = workspace_factory()
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["flow"]["steps"].append({"name": "route", "tool": "ecc", "state": "Success"})
    snapshot["workspaceSpec"] = {"parameters": {"place.target_density": 0.5}}
    snapshot["artifacts"] = []
    for step, tool, value in [("Synthesis", "yosys", 0), ("route", "ecc", 999)]:
        reference = f"{step}_{tool}/analysis/qor_metrics.json"
        report = workspace / reference
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "step": step,
                    "tool": tool,
                    "status": "success",
                    "integrity": {"status": "pass"},
                    "metrics": [
                        {"id": "cell_count", "value": value, "unit": "count"},
                        {"id": "missing", "value": None, "unit": "ns"},
                    ],
                }
            )
        )
        snapshot["artifacts"].append(
            {
                "artifactId": "artifact-"
                + hashlib.sha256(f"{snapshot['workspaceId']}\0{reference}".encode()).hexdigest()[
                    :32
                ],
                "reference": reference,
                "kind": "qor_metrics",
                "stepId": step,
                "availability": "available",
            }
        )
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    store = ExperienceStore(tmp_path / "store")
    case = collect_committed_case(workspace, store, read_workspace_observation).case
    return workspace, store, case


def test_prefix_has_provenance_zero_and_missing_but_no_later_metrics(stage_case):
    _workspace, store, case = stage_case
    result = features(case.case_id, store.root, through_step="Synthesis")
    assert result["status"] == "available"
    assert [item["step"] for item in result["steps"]] == ["Synthesis"]
    metrics = result["steps"][0]["metrics"]
    assert [(item["value"], item["status"]) for item in metrics] == [
        (0, "available"),
        (None, "unavailable"),
    ]
    assert metrics[0]["provenance"]["sha256"] is not None
    assert "qor" not in result
    assert result["parameters"]["level"] == "configured"
    assert result["parameters"]["values"] == {"place.target_density": 0.5}
    assert result["steps"][0]["tool_identity"] is None


def test_invalid_metric_sources_are_not_used_as_zero_counts(stage_case):
    workspace, store, _case = stage_case
    path = workspace / "Synthesis_yosys/analysis/qor_metrics.json"
    report = json.loads(path.read_text())
    report["integrity"] = {"status": "pass", "invalid_metric_source_ids": ["cell_count"]}
    path.write_text(json.dumps(report))
    case = collect_committed_case(workspace, store, read_workspace_observation).case

    result = features(case.case_id, store.root, through_step="Synthesis")

    assert [(item["value"], item["status"]) for item in result["steps"][0]["metrics"]] == [
        (None, "unavailable"),
        (None, "unavailable"),
    ]


def test_stored_features_survive_source_removal_and_detect_corruption(stage_case):
    workspace, store, case = stage_case
    import shutil

    shutil.rmtree(workspace)
    assert features(case.case_id, store.root)["status"] == "available"
    item = next(item for item in case.evidence if item.reference.endswith("qor_metrics.json"))
    (store.case_directory(case.case_id) / item.stored_path).write_text("{}")
    result = features(case.case_id, store.root)
    assert result["status"] == "fail"
    assert result["steps"] == []


def test_unknown_step_is_not_silently_mapped_to_full_flow(stage_case):
    _workspace, store, case = stage_case
    with pytest.raises(ExperienceError, match="absent"):
        features(case.case_id, store.root, through_step="unknown")


def test_legacy_features_remain_unknown(workspace_factory, tmp_path):
    workspace = workspace_factory()
    (workspace / "home/engineering-snapshot.json").unlink()
    store = ExperienceStore(tmp_path / "store")
    case = collect_committed_case(workspace, store, read_workspace_observation).case
    result = features(case.case_id, store.root)
    assert result["status"] == "unknown"
    assert result["steps"][0]["metrics"] == []


def test_features_cli_preserves_prefix_and_json(stage_case):
    _workspace, store, case = stage_case
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "features",
            case.case_id,
            "--store",
            str(store.root),
            "--through-step",
            "Synthesis",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["through_step"] == "Synthesis"


@pytest.mark.parametrize("invalid", [None, {}, [None]])
def test_malformed_metric_rows_remain_unknown(stage_case, invalid):
    workspace, store, _case = stage_case
    report = workspace / "Synthesis_yosys/analysis/qor_metrics.json"
    payload = json.loads(report.read_text())
    payload["metrics"] = invalid
    report.write_text(json.dumps(payload))
    case = collect_committed_case(workspace, store, read_workspace_observation).case
    result = features(case.case_id, store.root, through_step="Synthesis")
    assert result["status"] == "unknown"
    assert result["steps"][0]["metrics"] == []
