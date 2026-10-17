from pathlib import Path

import pytest

from ecc_experience.files import case_identity
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.knowledge.summary import summarize_store
from ecc_experience.models import ExperienceCase, ExperienceError, InputDigest, SourceObservation


def _case(root: Path, name: str, *, signoff: str = "ready", qor: bool = True) -> ExperienceCase:
    facts = {
        "experienceExecutionContext": {
            "schema": "ecc-experience-execution-context/1",
            "attempt_id": f"attempt-{name}",
            "runtime": {
                "sources": {"ecc": {"revision": "test-revision"}},
                "tools": {"yosys": "0.60"},
                "native_packages": {},
                "ecc": "test",
            },
        },
        "workspaceSpec": {
            "design": {"name": name, "topModule": name},
            "pdk": {"familyId": "ics55"},
            "parameters": {"place.target_density": 0.4},
        },
        "qorSnapshotExtension": {
            "status": "available" if qor else "unavailable",
            "score": 80.0 if qor else None,
        },
        "signoffAssessment": {"status": signoff},
        "flow": {
            "steps": [
                {
                    "name": "Synthesis",
                    "tool": "yosys",
                    "state": "Success",
                    "checklist_status": {"status": "passed"},
                    "resource_observation": {
                        "elapsed_seconds": 12.0,
                        "peak_rss_bytes": 1024,
                        "scope": "isolated_worker_process_tree",
                    },
                }
            ]
        },
        "metrics": [{"id": "synthesis_cell_count", "value": 10_000}],
    }
    source = SourceObservation(
        workspace_root=str(root),
        workspace_id="rtl2signoff",
        workspace_revision=1,
        snapshot_schema=4,
        snapshot_digest="a" * 64,
        cause="flow_step.success",
        observation_type="committed_import",
        attempt_id=f"attempt-{name}",
    )
    case = ExperienceCase(
        case_id="case-" + "0" * 64,
        collector_version="test",
        collected_at="2026-01-01T00:00:00Z",
        source=source,
        input_content_fingerprint="input-fingerprint",
        design_fingerprint=f"design-{name}",
        process_fingerprint="process-ics55",
        inputs=[InputDigest(input_id="rtl", role="rtl", status="available", sha256="a" * 64)],
        facts=facts,
        evidence=[],
        limitations=[],
        parameter_evidence="configured",
        validation_scope="committed_observation",
    )
    return case.model_copy(update={"case_id": case_identity(case.model_dump())})


def test_summary_classifies_cases_and_writes_report(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    passed = _case(tmp_path, "passed")
    blocked = _case(tmp_path, "blocked", signoff="blocked")
    unknown = _case(tmp_path, "unknown", qor=False)
    store.put(passed, {})
    store.put(blocked, {})
    store.put(unknown, {})

    report = summarize_store(store.root, tmp_path / "summary")

    assert report["status"] == "unknown"
    assert report["counts"]["cases"] == 3
    assert report["counts"]["quality"] == {
        "verified_pass": 1,
        "verified_observation": 0,
        "blocked": 1,
        "qor_unknown": 1,
        "incomplete": 0,
        "evidence_invalid": 0,
    }
    assert report["counts"]["release_eligible"] == 1
    assert report["deduplication"]["configuration_groups"] == 1
    assert (tmp_path / "summary/summary.json").is_file()
    assert (tmp_path / "summary/summary.md").is_file()
    assert report["steps"]["Synthesis"]["peak_rss_bytes"]["max"] == 1024


def test_summary_uses_case_id_when_input_fingerprint_is_missing(tmp_path):
    store = ExperienceStore(tmp_path / "store")
    case = _case(tmp_path, "missing-input").model_copy(update={"input_content_fingerprint": None})
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    store.put(case, {})

    report = summarize_store(store.root)

    assert report["deduplication"]["configuration_groups"] == 1
    assert report["cases"][0]["dedupe_key"] == case.case_id
    assert not report["cases"][0]["release_eligible"]


@pytest.mark.parametrize("change", ["checklist", "bad_step", "bad_specification"])
def test_summary_never_selects_incomplete_facts(tmp_path, change):
    store = ExperienceStore(tmp_path / "store")
    case = _case(tmp_path, "incomplete")
    if change == "checklist":
        case.facts["flow"]["steps"][0].pop("checklist_status")
    elif change == "bad_step":
        case.facts["flow"]["steps"].append(None)
    else:
        case.facts["workspaceSpec"] = None
    case = case.model_copy(update={"case_id": case_identity(case.model_dump())})
    store.put(case, {})

    report = summarize_store(store.root)

    assert not report["cases"][0]["release_eligible"]
    assert report["counts"]["read_errors"] == 0


def test_empty_summary_is_unknown(tmp_path):
    assert summarize_store(tmp_path)["status"] == "unknown"


def test_summary_rejects_writes_into_source_store(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(ExperienceError, match="outside"):
        summarize_store(store, store / "summary")
    assert not (store / "summary").exists()
