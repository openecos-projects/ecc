import copy
import json

import pytest
from typer.testing import CliRunner

from chipcompiler.cli.app import app
from ecc_experience.adapters import process_context as process_adapter
from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import plan as create_plan
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.knowledge.index import build_index
from ecc_experience.knowledge.matching import match_cases
from ecc_experience.knowledge.release import create_release
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


@pytest.fixture
def matching_cases(workspace_factory, tmp_path):
    store = ExperienceStore(tmp_path / "store")
    context = {
        "schema": "ecc-experience-execution-context/1",
        "attempt_id": "execution",
        "process": {"status": "available", "fingerprint": "selected-pdk-content"},
        "runtime": {
            "ecc": "test",
            "sources": {"chipcompiler": "source", "ecc_experience": "source"},
            "native_packages": {},
            "tools": {"yosys": "test-version"},
        },
    }

    def create(
        name,
        *,
        rtl="same content",
        version="test-version",
        process="selected-pdk-content",
        sdc="sdc-hash",
        revision="quality-gates-v4",
        executed=True,
    ):
        workspace = workspace_factory(name)
        source = workspace / "input.v"
        source.write_text(rtl)
        snapshot_path = workspace / "home/engineering-snapshot.json"
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["workspaceSpec"] = {
            "design": {"name": "sample", "topModule": "sample"},
            "pdk": {"familyId": "ics55", "version": "test", "mode": "default"},
            "parameters": {"place.target_density": 0.5},
            "inputs": [{"inputId": "rtl", "role": "rtl"}],
        }
        snapshot["workspaceBindings"] = {"inputs": {"rtl": str(source)}}
        snapshot["qorSnapshotExtension"].update(
            status="available", score=90.0, scalarStatus="GREEN"
        )
        snapshot["qorSnapshotExtension"].pop("reason")
        snapshot["artifacts"][0].update(kind="qor_metrics", stepId="Synthesis")
        snapshot_path.write_text(json.dumps(snapshot))
        report = workspace / "Synthesis_yosys/analysis/qor_metrics.json"
        report.write_text(
            json.dumps(
                {
                    "schema_version": 3,
                    "step": "Synthesis",
                    "tool": "yosys",
                    "status": "success",
                    "integrity": {"status": "pass"},
                    "analysis_revision": revision,
                    "context": {"timing_constraints": {"sdc_sha256": sdc}},
                    "metrics": [
                        {"id": "cells", "value": 100, "unit": "count", "category": "area_cost"}
                    ],
                }
            )
        )
        identity = copy.deepcopy(context)
        identity["runtime"]["tools"]["yosys"] = version
        identity["process"]["fingerprint"] = process
        return collect_committed_case(
            workspace,
            store,
            read_workspace_observation,
            attempt_id="execution",
            execution_context=identity if executed else None,
        ).case

    return create, store, tmp_path / "release.json"


def test_same_input_matches_are_release_bound_and_never_auto_applied(matching_cases):
    create, store, release = matching_cases
    query, candidate = create("query"), create("candidate")
    create_release([candidate.case_id], store.root, release)
    outside = create("outside-release")
    result = match_cases(query.case_id, store.root, release=release, through_step="Synthesis")
    assert result["status"] == "matches_available"
    assert [item["case_id"] for item in result["matches"]] == [candidate.case_id]
    assert outside.case_id not in str(result)
    assert result["matches"][0]["confidence"] == "observed_only"
    assert result["matches"][0]["distance"] == 0
    assert result["matches"][0]["safe_to_apply"] is False
    assert result["matches"][0]["parameters"]["level"] == "configured"


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"version": "other"}, "tool_identity_mismatch"),
        ({"process": "other"}, "process_fingerprint_mismatch"),
        ({"sdc": "other"}, "analysis_context_mismatch"),
        ({"revision": "other"}, "analysis_revision_mismatch"),
        ({"executed": False}, "tool_identity_unknown"),
    ],
)
def test_incompatible_or_unknown_context_is_explained(matching_cases, change, reason):
    create, store, release = matching_cases
    query, candidate = create("query"), create("candidate", **change)
    create_release([candidate.case_id], store.root, release)
    result = match_cases(query.case_id, store.root, release=release, through_step="Synthesis")
    assert result["status"] == "insufficient_evidence"
    assert reason in result["excluded"][0]["reasons"]


def test_cross_design_requires_opt_in_and_family_groups_are_explicit(matching_cases):
    create, store, release = matching_cases
    query, candidate = create("query"), create("candidate", rtl="different design content")
    create_release([candidate.case_id], store.root, release)
    kwargs = {"release": release, "through_step": "Synthesis"}
    normal = match_cases(query.case_id, store.root, **kwargs)
    assert "cross_design_not_enabled" in normal["excluded"][0]["reasons"]
    experimental = match_cases(query.case_id, store.root, experimental_cross_design=True, **kwargs)
    assert experimental["matches"][0]["confidence"] == "experimental"
    groups = release.parent / "groups.json"
    groups.write_text(
        json.dumps(
            {"schema_version": 1, "cases": {query.case_id: "family", candidate.case_id: "family"}}
        )
    )
    isolated = match_cases(
        query.case_id, store.root, groups=groups, experimental_cross_design=True, **kwargs
    )
    assert "same_evaluation_group" in isolated["excluded"][0]["reasons"]
    groups.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "cases": {query.case_id: "query-family", candidate.case_id: "heldout-family"},
            }
        )
    )
    assert (
        match_cases(
            query.case_id, store.root, groups=groups, experimental_cross_design=True, **kwargs
        )["status"]
        == "matches_available"
    )


def test_cross_design_only_excludes_same_input_from_the_match_limit(matching_cases):
    create, store, release = matching_cases
    query = create("query")
    same = create("same")
    cross = create("cross", rtl="different design content")
    create_release([same.case_id, cross.case_id], store.root, release)

    result = match_cases(
        query.case_id,
        store.root,
        release=release,
        through_step="Synthesis",
        experimental_cross_design=True,
        cross_design_only=True,
        limit=1,
    )

    assert [item["case_id"] for item in result["matches"]] == [cross.case_id]
    assert result["matches"][0]["confidence"] == "experimental"
    excluded = next(item for item in result["excluded"] if item["case_id"] == same.case_id)
    assert "same_input_content" in excluded["reasons"]


def test_match_cli_uses_explicit_frozen_release(matching_cases):
    create, store, release = matching_cases
    query, candidate = create("query"), create("candidate")
    create_release([candidate.case_id], store.root, release)
    result = CliRunner().invoke(
        app,
        [
            "experience",
            "match",
            query.case_id,
            "--store",
            str(store.root),
            "--release",
            str(release),
            "--through-step",
            "Synthesis",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)[0]["status"] == "matches_available"


def test_index_prefilter_matches_full_scan_and_damage_falls_back(matching_cases):
    create, store, release = matching_cases
    query, candidate = create("query"), create("candidate")
    create_release([candidate.case_id], store.root, release)
    arguments = {"release": release, "through_step": "Synthesis"}

    baseline = match_cases(query.case_id, store.root, **arguments)
    build_index(store.root)
    indexed = match_cases(query.case_id, store.root, **arguments)
    assert indexed["index"]["status"] == "used"
    assert indexed["matches"] == baseline["matches"]
    assert indexed["excluded"] == baseline["excluded"]

    (store.root / "index/cases.json").write_text("{")
    fallback = match_cases(query.case_id, store.root, **arguments)
    assert fallback["index"]["status"] == "invalid"
    assert fallback["matches"] == baseline["matches"]
    assert fallback["excluded"] == baseline["excluded"]


def test_optimization_plan_keeps_configured_cross_design_as_review_clue(matching_cases, tmp_path):
    create, store, release = matching_cases
    query = create("plan-query")
    candidate = create("plan-candidate", rtl="different design content")
    create_release([candidate.case_id], store.root, release)

    payload = create_plan(
        query.source.workspace_root,
        store.root,
        tmp_path / "cross-plan.json",
        release=release,
        experimental_cross_design=True,
        through_step="Synthesis",
    )

    assert payload["status"] == "insufficient_evidence"
    assert payload["candidates"] == []
    assert payload["cross_design"]["status"] == "matches_available"
    assert payload["cross_design"]["query_case_id"] == query.case_id
    assert payload["cross_design"]["matches"][0]["case_id"] == candidate.case_id
    assert payload["cross_design"]["clues"][0]["parameter_evidence_level"] == "configured"
    assert payload["cross_design"]["safe_to_apply"] is False


def test_optimization_plan_consumes_only_applied_cross_design_matches(
    matching_cases, tmp_path, monkeypatch
):
    from ecc_experience.optimization import plan as plan_module

    create, store, release = matching_cases
    query = create("applied-plan-query")
    candidate = create("applied-plan-candidate", rtl="different design content")
    create_release([candidate.case_id], store.root, release)
    provenance = [
        {
            "release_id": "release-test",
            "case_id": candidate.case_id,
            "distance": 0.1,
            "feature_coverage": 0.9,
            "confidence": "experimental",
        }
    ]
    monkeypatch.setattr(
        plan_module,
        "match_cases",
        lambda *_args, **_kwargs: {
            "status": "matches_available",
            "confidence": "experimental",
            "release_id": "release-test",
            "matches": [
                {
                    "case_id": candidate.case_id,
                    "match_quality": "compatible_design",
                    "confidence": "experimental",
                    "distance": 0.1,
                    "feature_coverage": 0.9,
                    "parameter_evidence_level": "applied",
                    "parameters": {
                        "level": "applied",
                        "values": {"place.target_density": 0.4},
                    },
                    "provenance": provenance,
                }
            ],
        },
    )

    payload = create_plan(
        query.source.workspace_root,
        store.root,
        tmp_path / "applied-plan.json",
        release=release,
        experimental_cross_design=True,
        through_step="Synthesis",
    )

    assert payload["status"] == "recommendations_available"
    candidate_record = payload["candidates"][0]
    assert candidate_record["source"] == "compatible_design"
    assert candidate_record["parameters"] == {"place.target_density": 0.4}
    assert candidate_record["provenance"] == provenance
    assert candidate_record["safe_to_apply"] is False


def test_process_content_changes_are_detected_without_path_identity(tmp_path):
    files = []
    for role in ["tech", "lef", "liberty"]:
        path = tmp_path / role
        path.write_text(role)
        files.append({"role": role, "fileId": role})
    facts = {
        "workspaceSpec": {"pdk": {"familyId": "generic", "mode": "manual", "files": files}},
        "workspaceBindings": {
            "pdk": {"files": {item["fileId"]: str(tmp_path / item["role"]) for item in files}}
        },
    }
    first = process_adapter.process_context(facts)
    assert first["status"] == "available"
    (tmp_path / "liberty").write_text("different content")
    second = process_adapter.process_context(facts)
    assert second["fingerprint"] != first["fingerprint"]
    (tmp_path / "liberty").unlink()
    assert process_adapter.process_context(facts)["status"] == "unknown"
    assert process_adapter.process_context({})["fingerprint"] is None


def test_context_cannot_claim_another_execution(matching_cases):
    create, store, _release = matching_cases
    case = create("sample")
    with pytest.raises(ExperienceError, match="bound"):
        collect_committed_case(
            case.source.workspace_root,
            store,
            read_workspace_observation,
            attempt_id="new-run",
            execution_context=case.facts["experienceExecutionContext"],
        )
