import json

import pytest

from ecc_experience.benchmark.manifest import load_manifest
from ecc_experience.models import ExperienceError


def _write_manifest(root, *, output_root="outputs", store="store", designs=None):
    payload = {
        "schema_version": 1,
        "campaign_id": "campaign-1",
        "process_profile": "ics55",
        "store": store,
        "output_root": output_root,
        "knowledge_release_id": None,
        "mode": "baseline",
        "budget": {
            "max_concurrent_flows": 1,
            "max_trials_per_design": 2,
            "timeout_seconds_per_trial": 3600,
        },
        "designs": designs
        or [
            {
                "id": "design-1",
                "input": {"kind": "ecc-project", "path": "design-1"},
                "workspace": "baseline",
                "labels": [],
                "evaluation_group": None,
            }
        ],
    }
    path = root / "campaign.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_load_manifest_returns_frozen_summary(tmp_path):
    (tmp_path / "design-1").mkdir()
    manifest = _write_manifest(tmp_path)

    _model, summary = load_manifest(manifest)

    assert summary["campaign_id"] == "campaign-1"
    assert summary["design_count"] == 1
    assert summary["output_root"] == str((tmp_path / "outputs").resolve())
    assert len(summary["fingerprint"]) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [("store", "design-1/store"), ("output_root", "design-1/out"), ("store", "../store")],
)
def test_load_manifest_rejects_overlapping_or_escaping_paths(tmp_path, field, value):
    (tmp_path / "design-1").mkdir()
    manifest = _write_manifest(tmp_path, **{field: value})

    with pytest.raises(ExperienceError, match="Campaign"):
        load_manifest(manifest)


def test_load_manifest_rejects_duplicate_design_ids(tmp_path):
    (tmp_path / "design-1").mkdir()
    designs = [
        {
            "id": "same",
            "input": {"kind": "ecc-project", "path": "design-1"},
            "workspace": "baseline",
        },
        {
            "id": "same",
            "input": {"kind": "ecc-project", "path": "design-1"},
            "workspace": "candidate",
        },
    ]
    manifest = _write_manifest(tmp_path, designs=designs)

    with pytest.raises(ExperienceError, match="unique"):
        load_manifest(manifest)


def test_load_manifest_reports_missing_input(tmp_path):
    manifest = _write_manifest(tmp_path)

    with pytest.raises(ExperienceError, match="does not exist"):
        load_manifest(manifest)
