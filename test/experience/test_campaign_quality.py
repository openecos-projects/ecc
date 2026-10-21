import hashlib
import json
import shutil

import pytest

from ecc_experience.adapters.chipcompiler_reader import read_workspace_observation
from ecc_experience.api import campaign_quality
from ecc_experience.benchmark.ledger import initialize, record_trial
from ecc_experience.benchmark.report import report_campaign
from ecc_experience.collection.collect import collect_committed_case
from ecc_experience.files import case_identity
from ecc_experience.knowledge.store import ExperienceStore
from ecc_experience.models import ExperienceError


@pytest.fixture
def campaign(tmp_path):
    (tmp_path / "input").mkdir()
    path = tmp_path / "campaign.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "campaign_id": "quality-test",
                "process_profile": "ics55",
                "store": "store",
                "output_root": "output",
                "mode": "baseline",
                "budget": {
                    "max_concurrent_flows": 1,
                    "max_trials_per_design": 4,
                    "timeout_seconds_per_trial": 60,
                },
                "designs": [
                    {
                        "id": "sample",
                        "input": {"kind": "ecc-project", "path": "input"},
                        "workspace": "baseline",
                        "evaluation_group": "user-provided-family",
                    }
                ],
            }
        )
    )
    initialize(path)
    return path


@pytest.fixture
def make_case(workspace_factory, tmp_path):
    def create(name="workspace", *, score=85.0, family="ics55", attempt="attempt-1", inputs=True):
        workspace = workspace_factory(name)
        input_file = tmp_path / f"{name}.v"
        input_file.write_text("module example; endmodule")
        snapshot_path = workspace / "home/engineering-snapshot.json"
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["workspaceSpec"] = {
            "design": {"topModule": "example"},
            "pdk": {"familyId": family},
            "inputs": [{"inputId": "rtl", "role": "rtl"}] if inputs else [],
            "parameters": {"place.density": 0.7},
        }
        snapshot["workspaceBindings"] = {"inputs": {"rtl": str(input_file)} if inputs else {}}
        if score is not None:
            snapshot["qorSnapshotExtension"].update(
                status="available",
                score=score if type(score) in (int, float) else 85.0,
                scalarStatus="GREEN",
            )
            snapshot["qorSnapshotExtension"].pop("reason")
        snapshot["flow"]["steps"][0].update(runtime="0:0:3", **{"peak memory (mb)": 12.5})
        snapshot_path.write_text(json.dumps(snapshot))
        (workspace / "home/flow.json").write_text(json.dumps(snapshot["flow"]))
        (workspace / "home/params.toml").write_text("[params]\n")
        repository = ExperienceStore(tmp_path / "store")
        case = collect_committed_case(
            workspace, repository, read_workspace_observation, attempt_id=attempt
        ).case
        if score is not None and type(score) not in (int, float):
            facts = json.loads(json.dumps(case.facts))
            facts["qorSnapshotExtension"]["score"] = score
            changed = case.model_copy(update={"facts": facts})
            changed = changed.model_copy(update={"case_id": case_identity(changed.model_dump())})
            copies = {
                item.stored_path: (
                    repository.case_directory(case.case_id) / item.stored_path
                ).read_bytes()
                for item in case.evidence
                if item.stored_path
            }
            repository.put(changed, copies)
            return changed
        return case

    return create


def _record(campaign, case_id=None, *, trial_id="trial-1", status="pass"):
    return record_trial(
        campaign.parent / "output/campaign-ledger.json",
        design_id="sample",
        workspace="baseline",
        trial_id=trial_id,
        status=status,
        case_id=case_id,
    )


def _digests(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_matrix_preserves_every_attempt_and_missing_evidence(campaign, make_case, tmp_path):
    case = make_case()
    _record(campaign, trial_id="failed", status="fail")
    _record(campaign, case.case_id, trial_id="retry")
    before = _digests(campaign.parent)

    report = report_campaign(campaign, tmp_path / "reports/matrix")

    assert [(row["trial_id"], row["status"], row["qor_score"]) for row in report["rows"]] == [
        ("failed", "fail", None),
        ("retry", "pass", 85.0),
    ]
    assert report["exit_code"] == 7
    assert report["safe_to_apply"] is False
    assert report["rows"][1]["parameters"] == {"place.density": 0.7}
    assert "scope=legacy_flow_step_ledger" in (tmp_path / "reports/matrix/matrix.csv").read_text()
    assert json.loads((tmp_path / "reports/matrix/matrix.json").read_text()) == json.loads(
        json.dumps({key: value for key, value in report.items() if key != "output"})
    )
    assert {
        key: value
        for key, value in _digests(campaign.parent).items()
        if not key.startswith("reports/")
    } == before


def test_matrix_pending_and_corruption_are_not_success(campaign, make_case, tmp_path):
    pending = report_campaign(campaign, tmp_path / "reports/pending")
    assert (pending["exit_code"], pending["rows"][0]["status"]) == (7, "pending")
    case = make_case()
    _record(campaign, case.case_id)
    repository = ExperienceStore(tmp_path / "store")
    captured = next(item for item in case.evidence if item.stored_path)
    (repository.case_directory(case.case_id) / captured.stored_path).write_text("corrupted")

    report = report_campaign(campaign, tmp_path / "reports/corrupt")

    assert report["exit_code"] == 6
    assert report["rows"][0]["qor_score"] is None
    assert report["rows"][0]["integrity"] == "fail"


@pytest.mark.parametrize("relative", ["input/report", "store/report", "output/report"])
def test_matrix_rejects_managed_directories(campaign, tmp_path, relative):
    with pytest.raises(ExperienceError, match="outside"):
        report_campaign(campaign, tmp_path / relative)


def test_complete_observation_is_read_only_and_exposes_resource_scope(campaign, make_case):
    case = make_case()
    _record(campaign, case.case_id)
    before = _digests(campaign.parent)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("pass", 0)
    assert result["counts"] == {
        "designs": 1,
        "pending_designs": 0,
        "trials": 1,
        "running_trials": 0,
        "quality": {"pass": 1, "fail": 0, "unknown": 0},
        "execution": {"pass": 1},
    }
    assert all(item == {"available": 1, "total": 1} for item in result["coverage"].values())
    assert result["diversity"] == {
        "unique_cases": 1,
        "unique_execution_identities": 1,
        "unique_input_fingerprints": 1,
        "duplicate_case_references": 0,
        "repeated_execution_references": 0,
        "evaluation_groups_provided": 1,
        "designs_without_evaluation_group": 0,
    }
    assert result["trials"][0]["steps"] == [
        {
            "name": "Synthesis",
            "tool": "yosys",
            "state": "Success",
            "checklist_status": None,
            "runtime": "0:0:3",
            "peak_memory_mb": 12.5,
            "resource_scope": "legacy_flow_step_ledger",
            "resource_observation": None,
        }
    ]
    assert _digests(campaign.parent) == before


def test_all_retries_are_reported_and_duplicate_samples_are_not_independent(campaign, make_case):
    case = make_case()
    _record(campaign, case.case_id, status="fail")
    _record(campaign, case.case_id, trial_id="trial-2")

    result = campaign_quality(campaign)

    assert result["status"] == "pass"
    assert [item["execution_status"] for item in result["trials"]] == ["fail", "pass"]
    assert result["counts"]["execution"] == {"fail": 1, "pass": 1}
    assert result["diversity"]["unique_execution_identities"] == 1
    assert result["diversity"]["duplicate_case_references"] == 1
    assert result["trials"][1]["reused_execution_identity"] is True


def test_different_observations_of_one_execution_are_counted_once(campaign, make_case):
    case = make_case()
    repository = ExperienceStore(campaign.parent / "store")
    changed = case.model_copy(update={"collector_version": "different-collector"})
    changed = changed.model_copy(update={"case_id": case_identity(changed.model_dump())})
    copies = {
        item.stored_path: (repository.case_directory(case.case_id) / item.stored_path).read_bytes()
        for item in case.evidence
        if item.stored_path
    }
    repository.put(changed, copies)
    _record(campaign, case.case_id)
    _record(campaign, changed.case_id, trial_id="trial-2")

    result = campaign_quality(campaign)

    assert result["diversity"]["unique_cases"] == 2
    assert result["diversity"]["unique_execution_identities"] == 1
    assert result["diversity"]["repeated_execution_references"] == 1
    assert result["diversity"]["unique_input_fingerprints"] == 1


@pytest.mark.parametrize("case_id", [None, "case-" + "a" * 64])
def test_missing_evidence_is_unknown(campaign, case_id):
    _record(campaign, case_id)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("unknown", 7)
    assert result["counts"]["quality"] == {"pass": 0, "fail": 0, "unknown": 1}
    assert not (campaign.parent / "store").exists()


def test_pending_campaign_is_unknown_without_creating_store(campaign):
    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"], result["counts"]["pending_designs"]) == (
        "unknown",
        7,
        1,
    )
    assert not (campaign.parent / "store").exists()


@pytest.mark.parametrize("damage", ["case", "stored_evidence", "source"])
def test_corrupt_or_stale_evidence_fails(campaign, make_case, damage):
    case = make_case()
    _record(campaign, case.case_id)
    directory = ExperienceStore(campaign.parent / "store").case_directory(case.case_id)
    if damage == "case":
        target = directory / "case.json"
    elif damage == "stored_evidence":
        target = directory / next(item.stored_path for item in case.evidence if item.stored_path)
    else:
        target = campaign.parent / "workspace/home/flow.json"
    target.write_text("corrupt")

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("fail", 6)
    assert result["trials"][0]["findings"]


def test_unavailable_source_keeps_integrity_but_is_unknown(campaign, make_case):
    case = make_case()
    _record(campaign, case.case_id)
    shutil.rmtree(campaign.parent / "workspace")

    result = campaign_quality(campaign)

    assert (result["status"], result["trials"][0]["integrity"]) == ("unknown", "pass")


@pytest.mark.parametrize("score", [True, "85", -float("inf"), float("nan")])
def test_invalid_qor_is_never_accepted(campaign, make_case, score):
    if isinstance(score, float):
        case = make_case()
        _record(campaign, case.case_id)
        path = ExperienceStore(campaign.parent / "store").case_directory(case.case_id) / "case.json"
        payload = json.loads(path.read_text())
        payload["facts"]["qorSnapshotExtension"]["score"] = score
        path.write_text(json.dumps(payload))
    else:
        case = make_case(score=score)
        _record(campaign, case.case_id)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("fail", 6)


@pytest.mark.parametrize(
    "options", [{"score": None}, {"attempt": None}, {"inputs": False}, {"family": None}]
)
def test_missing_required_facts_are_unknown(campaign, make_case, options):
    case = make_case(**options)
    _record(campaign, case.case_id)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("unknown", 7)


def test_process_mismatch_fails(campaign, make_case):
    case = make_case(family="other-process")
    _record(campaign, case.case_id)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("fail", 6)


def test_running_trial_is_not_reported_as_complete(campaign, make_case):
    case = make_case()
    _record(campaign, case.case_id, status="running")

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"], result["counts"]["running_trials"]) == (
        "unknown",
        7,
        1,
    )


def test_legacy_import_remains_unknown(campaign, workspace_factory):
    workspace = workspace_factory()
    (workspace / "home/engineering-snapshot.json").unlink()
    case = collect_committed_case(
        workspace, ExperienceStore(campaign.parent / "store"), read_workspace_observation
    ).case
    _record(campaign, case.case_id)

    result = campaign_quality(campaign)

    assert (result["status"], result["exit_code"]) == ("unknown", 7)
    assert not (workspace / "home/engineering-snapshot.json").exists()


def test_manifest_change_is_rejected(campaign):
    payload = json.loads(campaign.read_text())
    payload["budget"]["max_trials_per_design"] = 5
    campaign.write_text(json.dumps(payload))

    with pytest.raises(ExperienceError) as failure:
        campaign_quality(campaign)

    assert failure.value.code == "experience_campaign_manifest_changed"
