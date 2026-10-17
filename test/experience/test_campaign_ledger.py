import json

import pytest

from ecc_experience.benchmark.ledger import initialize, record_trial, status
from ecc_experience.benchmark.summary import summarize
from ecc_experience.models import ExperienceError


def _manifest(root):
    (root / "design-1").mkdir()
    path = root / "campaign.json"
    path.write_text(
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
                    "max_trials_per_design": 2,
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
    return path


def test_initialize_and_record_trial_are_idempotent(tmp_path):
    manifest = _manifest(tmp_path)

    created = initialize(manifest)
    repeated = initialize(manifest)
    ledger = tmp_path / "outputs/campaign-ledger.json"
    recorded = record_trial(
        ledger,
        design_id="design-1",
        workspace="baseline-001",
        status="pass",
        trial_id="trial-1",
        case_id="case-" + "a" * 64,
    )
    repeated_record = record_trial(
        ledger,
        design_id="design-1",
        workspace="baseline-001",
        status="pass",
        trial_id="trial-1",
        case_id="case-" + "a" * 64,
    )

    assert created["created"] is True
    assert repeated["created"] is False
    assert recorded["status"] == "recorded"
    assert repeated_record["status"] == "already_present"
    assert status(manifest)["counts"]["pass"] == 1


def test_record_trial_rejects_conflicting_reuse(tmp_path):
    manifest = _manifest(tmp_path)
    initialize(manifest)
    ledger = tmp_path / "outputs/campaign-ledger.json"
    record_trial(
        ledger, design_id="design-1", workspace="baseline", status="fail", trial_id="trial-1"
    )

    with pytest.raises(ExperienceError, match="different data"):
        record_trial(
            ledger, design_id="design-1", workspace="baseline", status="pass", trial_id="trial-1"
        )


def test_status_rejects_changed_manifest(tmp_path):
    manifest = _manifest(tmp_path)
    initialize(manifest)
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["budget"]["max_trials_per_design"] = 3
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExperienceError, match="manifest changed"):
        status(manifest)


def test_summary_reports_missing_case_evidence(tmp_path):
    manifest = _manifest(tmp_path)
    initialize(manifest)
    ledger = tmp_path / "outputs/campaign-ledger.json"
    record_trial(
        ledger,
        design_id="design-1",
        workspace="baseline",
        status="pass",
        trial_id="trial-1",
    )

    result = summarize(manifest)

    assert result["campaign_status"] == "complete"
    assert result["evidence_counts"]["missing"] == 1
    assert result["trials"][0]["evidence_status"] == "missing"
