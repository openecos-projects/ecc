import json

import pytest

from ecc_experience.api import dse_plan
from ecc_experience.dse.patience import resolve_patience
from ecc_experience.dse.plan import read_dse_plan
from ecc_experience.models import ExperienceError
from test.experience import test_dse as fixtures

dse_project = fixtures.dse_project
version2_spec = fixtures.version2_spec


def test_fixed_patience_is_preserved():
    resolved, policy = resolve_patience(4, strategy="adaptive", domain_size=20, screening_trials=11)

    assert resolved == 4
    assert policy == {
        "mode": "fixed",
        "requested": 4,
        "strategy": "adaptive",
        "domain_size": 20,
        "screening_trials": 11,
        "resolved": 4,
    }


@pytest.mark.parametrize(
    ("strategy", "screening_trials", "expected"),
    [("grid", 11, 11), ("adaptive", 11, 6), ("adaptive", 3, 3)],
)
def test_auto_patience_is_deterministic(strategy, screening_trials, expected):
    resolved, policy = resolve_patience(
        "auto",
        strategy=strategy,
        domain_size=11,
        screening_trials=screening_trials,
    )

    assert resolved == expected
    assert policy["rule"] == "candidate_fraction_v1"
    assert policy["resolved"] == expected


def test_invalid_patience_is_rejected():
    with pytest.raises(ExperienceError, match="positive integer or 'auto'"):
        resolve_patience(0, strategy="adaptive", domain_size=3, screening_trials=3)


def test_version2_auto_patience_is_frozen_and_old_shape_remains_readable(
    dse_project, version2_spec
):
    workspace, store, path = dse_project
    spec_payload = json.loads(version2_spec.read_text())
    spec_payload["space"] = {"floorplan.core_util": {"range": [0.3, 0.4], "step": 0.01}}
    spec_payload["limits"] = {
        "max_trials": 13,
        "max_seconds": 60,
        "trial_timeout_seconds": 30,
        "patience": "auto",
    }
    version2_spec.write_text(json.dumps(spec_payload))

    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)

    assert frozen["limits"]["patience"] == 6
    assert frozen["patience_resolution"] == {
        "mode": "auto",
        "requested": "auto",
        "rule": "candidate_fraction_v1",
        "strategy": "adaptive",
        "domain_size": 11,
        "screening_trials": 11,
        "resolved": 6,
    }
    assert read_dse_plan(path)[1].patience == 6

    old_payload = {
        key: value
        for key, value in json.loads(path.read_text()).items()
        if key != "patience_resolution"
    }
    path.write_text(
        json.dumps(
            {
                **old_payload,
                "plan_fingerprint": fixtures.digest(
                    {key: value for key, value in old_payload.items() if key != "plan_fingerprint"}
                ),
            }
        )
    )
    assert read_dse_plan(path)[1].patience == 6
