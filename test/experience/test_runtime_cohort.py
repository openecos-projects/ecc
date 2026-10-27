import hashlib
import json

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.cohort import case_knowledge, cohort_status
from ecc_experience.knowledge.store import ExperienceStore


def _context(attempt="attempt-cohort"):
    return {
        "schema": "ecc-experience-execution-context/1",
        "attempt_id": attempt,
        "snapshot_digest": "snapshot",
        "runtime": {
            "ecc": "0.1.0-alpha.12",
            "sources": {"ecc": "source"},
            "tools": {"yosys": "0.61"},
            "native_packages": {"ecc-tools-bin": "0.1.0a13"},
        },
        "process": {"status": "available", "fingerprint": "process-a"},
        "scope": "test",
        "checks": {"runtime": "available", "process": "available"},
        "observations": {},
    }


def _workspace(workspace_factory):
    workspace = workspace_factory()
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    reference = "Synthesis_yosys/analysis/qor_metrics.json"
    report = workspace / reference
    report.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": "Synthesis",
                "tool": "yosys",
                "status": "success",
                "analysis_revision": "qor-analyzer-2",
                "integrity": {"status": "pass"},
                "metrics": [
                    {
                        "id": "cell_count",
                        "value": 10,
                        "unit": "count",
                        "scope": "design",
                        "corner": "tt",
                    }
                ],
            }
        )
    )
    snapshot["artifacts"] = [
        {
            "artifactId": "artifact-"
            + hashlib.sha256(f"{snapshot['workspaceId']}\0{reference}".encode()).hexdigest()[:32],
            "reference": reference,
            "kind": "qor_metrics",
            "stepId": "Synthesis",
            "availability": "available",
        }
    ]
    snapshot_path.write_text(json.dumps(snapshot))
    return workspace


def test_collection_binds_deterministic_cohort_and_step_contract(workspace_factory, tmp_path):
    workspace = _workspace(workspace_factory)
    store = ExperienceStore(tmp_path / "store")
    context = _context()
    first = collect_committed_case(
        workspace,
        store,
        read_workspace_observation,
        attempt_id=context["attempt_id"],
        execution_context=context,
    ).case
    second = collect_committed_case(
        workspace,
        store,
        read_workspace_observation,
        attempt_id=context["attempt_id"],
        execution_context=context,
    ).case

    assert first.schema_version == 3
    assert first.case_id == second.case_id
    knowledge = case_knowledge(first)
    assert knowledge["status"] == "available"
    assert knowledge["runtime_cohort"]["cohort_id"].startswith("cohort-")
    assert knowledge["step_contracts"][0]["report_schema"] == 3
    assert knowledge["step_contracts"][0]["analysis_revision"] == "qor-analyzer-2"
    assert knowledge["step_contracts"][0]["metrics"][0]["id"] == "cell_count"
    assert cohort_status(first) == "available"
    assert cohort_status(first, knowledge["runtime_cohort"]["cohort_id"]) == "same_cohort"


def test_legacy_case_has_no_silent_cohort(workspace_factory, tmp_path):
    workspace = workspace_factory()
    case = collect_committed_case(
        workspace, ExperienceStore(tmp_path / "store"), read_workspace_observation
    ).case

    assert case.schema_version == 3
    assert case_knowledge(case)["status"] == "legacy_unknown"
    assert cohort_status(case, "cohort-new") == "legacy_unknown"
