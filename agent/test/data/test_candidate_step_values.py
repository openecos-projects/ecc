import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.data.candidate_step_values import (
    CandidateStepValueError,
    expected_step_config_values,
    seed_steps,
    verify_executed_step_configs,
)


def _step(root: Path, name: str, tool: str, config: dict | None = None) -> SimpleNamespace:
    step = SimpleNamespace(name=name, tool=tool, directory=root / f"{name}_{tool}")
    if config is not None:
        path = step.directory / "config" / "dreamplace_ecc.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(config), encoding="utf-8")
    return step


def test_seed_steps_are_the_steps_consuming_the_dreamplace_seed():
    steps = [SimpleNamespace(name=name) for name in ("floorplan", "placement", "legalization")]

    assert seed_steps(steps) == ["placement"]


def test_expected_step_config_values_bind_seed_and_knob_to_their_step():
    written = [{"knob_id": "place.routability_opt", "value": True}]

    assert expected_step_config_values(written, ["placement"], 17) == {
        "placement": {("random_seed",): 17, ("routability_opt_flag",): 1}
    }


def test_executed_step_config_must_hold_the_candidate_values(tmp_path):
    expected = expected_step_config_values(
        [{"knob_id": "place.target_density", "value": 0.6}], ["placement"], 17
    )
    built = _step(tmp_path, "placement", "dreamplace", {"random_seed": 17, "target_density": 0.6})
    cts = _step(tmp_path, "cts", "ecc")

    verify_executed_step_configs([built, cts], expected)

    stale = _step(
        tmp_path / "stale", "placement", "dreamplace", {"random_seed": 3000, "target_density": 0.6}
    )
    with pytest.raises(CandidateStepValueError, match="does not hold the candidate values"):
        verify_executed_step_configs([stale], expected)
    missing = SimpleNamespace(name="placement", tool="dreamplace", directory=tmp_path / "none")
    with pytest.raises(CandidateStepValueError, match="unreadable"):
        verify_executed_step_configs([missing], expected)
