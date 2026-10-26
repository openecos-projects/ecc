import json

import pytest

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.study.evidence import acceptance


def collect_case(workspace_factory, tmp_path, name, *, policy="warn", risk_state="warning"):
    workspace = workspace_factory(name)
    source = workspace / "input.v"
    source.write_text("module sample; endmodule")
    snapshot_path = workspace / "home/engineering-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    snapshot["workspaceSpec"] = {
        "design": {"topModule": "sample"},
        "pdk": {"familyId": "ics55"},
        "flow": {"flowId": "test"},
        "parameters": {"floorplan.core_util": 0.3},
        "inputs": [{"inputId": "rtl", "role": "rtl"}],
    }
    snapshot["workspaceBindings"] = {"inputs": {"rtl": str(source)}}
    snapshot["flow"]["steps"][0].update(
        checklist_status={"status": "attention", "blocked": False, "failed_items": []}
    )
    snapshot["checklist"] = {"items": [{"state": "warning", "blocked": False}]}
    snapshot["signoffAssessment"] = {
        "status": "attention",
        "risks": [
            {
                "severity": "warning",
                "details": [
                    {
                        "policy": policy,
                        "state": risk_state,
                        "blocked": False,
                    }
                ],
            }
        ],
    }
    snapshot["qorSnapshotExtension"].update(
        status="available",
        score=90.0,
        feasibility={"status": "PASS", "gates": []},
    )
    snapshot["qorSnapshotExtension"].pop("reason", None)
    snapshot["artifacts"][0].update(kind="qor_metrics", stepId="Synthesis")
    snapshot_path.write_text(json.dumps(snapshot))
    (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
    (workspace / "Synthesis_yosys/analysis/qor_metrics.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "step": "Synthesis",
                "tool": "yosys",
                "status": "success",
                "integrity": {"status": "pass"},
                "analysis_revision": "revision",
                "context": {"timing_constraints": {"sdc_sha256": "constraints"}},
                "metrics": [{"id": "cells", "value": 10, "unit": "count", "category": "area_cost"}],
            }
        )
    )
    repository = ExperienceStore(tmp_path / f"store-{name}")
    case = collect_committed_case(
        workspace,
        repository,
        read_workspace_observation,
        attempt_id=name,
        execution_context={
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": name,
            "process": {"status": "available", "fingerprint": "process"},
            "runtime": {
                "ecc": "test",
                "sources": {"chipcompiler": "source"},
                "native_packages": {},
                "tools": {"yosys": "runtime"},
            },
        },
    ).case
    return acceptance(case, repository.case_directory(case.case_id))


def test_acceptance_allows_explicit_advisory_only(tmp_path, workspace_factory):
    result = collect_case(workspace_factory, tmp_path, "advisory")
    assert result["status"] == "pass"
    assert result["advisory_only"] is True
    assert result["signoff_status"] == "unknown"
    assert result["qor_score"] == 90.0


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"policy": "block"}, "unknown"),
        ({"risk_state": "failed"}, "unknown"),
    ],
)
def test_acceptance_rejects_non_advisory_attention(tmp_path, workspace_factory, changes, expected):
    result = collect_case(workspace_factory, tmp_path, "non-advisory", **changes)
    assert result["status"] == expected
    assert result["advisory_only"] is False
