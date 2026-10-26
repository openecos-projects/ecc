import json

import pytest

from ecc_experience.api import dse_plan
from ecc_experience.dse.space import Axis, expand_space
from ecc_experience.models import ExperienceError
from test.experience import test_dse as fixtures

dse_project = fixtures.dse_project
version2_spec = fixtures.version2_spec
simulated_cli = fixtures.simulated_cli


def test_range_axes_are_quantized_to_replayable_values():
    linear = expand_space(
        {"floorplan.core_util": Axis(kind="range", min=0.25, max=0.65, scale="linear", points=5)}
    )["floorplan.core_util"]
    assert linear == [0.25, 0.35, 0.45, 0.55, 0.65]

    logarithmic = expand_space(
        {"floorplan.core_util": Axis(kind="range", min=0.2, max=0.8, scale="log", points=3)}
    )["floorplan.core_util"]
    assert logarithmic == pytest.approx([0.2, 0.4, 0.8])

    integer = expand_space(
        {"cts.max_fanout": Axis(kind="range", min=1, max=100, scale="log", points=3)}
    )["cts.max_fanout"]
    assert integer == [1, 10, 100]


def test_expanded_dreamplace_axes_quantize_to_replayable_config_values():
    space = expand_space(
        {
            "place.overflow_reference_mode": Axis(values=["ordinary"]),
            "place.timing_placement_carrier": Axis(values=["direct_loss", "gradient_net_weight"]),
            "place.timing_topology_refresh_interval": Axis(kind="range", min=0, max=20, step=5),
            "place.timing_topology_enable_overflow_threshold": Axis(
                kind="range", min=0.2, max=0.4, points=3
            ),
            "place.timing_aggregation_mode": Axis(values=["hard", "smooth"]),
        }
    )

    assert {
        key: value
        for key, value in space.items()
        if key != "place.timing_topology_enable_overflow_threshold"
    } == {
        "place.overflow_reference_mode": ["ordinary"],
        "place.timing_placement_carrier": [
            "direct_loss",
            "gradient_net_weight",
        ],
        "place.timing_topology_refresh_interval": [0, 5, 10, 15, 20],
        "place.timing_aggregation_mode": ["hard", "smooth"],
    }
    assert space["place.timing_topology_enable_overflow_threshold"] == pytest.approx(
        [0.2, 0.3, 0.4]
    )


def test_pin2pin_space_requires_explicit_hard_aggregation():
    valid = expand_space(
        {
            "place.timing_placement_carrier": Axis(values=["pin2pin"]),
            "place.timing_aggregation_mode": Axis(values=["hard"]),
        }
    )
    assert valid["place.timing_placement_carrier"] == ["pin2pin"]

    with pytest.raises(ExperienceError, match="explicit hard-only"):
        expand_space({"place.timing_placement_carrier": Axis(values=["pin2pin"])})
    with pytest.raises(ExperienceError, match="explicit hard-only"):
        expand_space(
            {
                "place.timing_placement_carrier": Axis(values=["pin2pin", "direct_loss"]),
                "place.timing_aggregation_mode": Axis(values=["hard", "smooth"]),
            }
        )


@pytest.mark.parametrize(
    "axis",
    [
        Axis(kind="range", min=0, max=1, scale="log", points=3),
        Axis(kind="range", min=1, max=0, points=3),
        Axis(kind="values"),
        Axis(values=[0.3], kind="range"),
        Axis(kind="range", min=0.1, max=0.2, step=0.05, scale="log"),
    ],
)
def test_invalid_range_axes_are_rejected(axis):
    with pytest.raises(ExperienceError):
        expand_space({"floorplan.core_util": axis})


def test_version2_range_spec_freezes_quantization_and_executes(
    dse_project, simulated_cli, version2_spec
):
    workspace, store, path = dse_project
    payload = json.loads(version2_spec.read_text())
    payload["space"]["floorplan.core_util"] = {
        "kind": "range",
        "min": 0.3,
        "max": 0.4,
        "scale": "linear",
        "points": 3,
    }
    version2_spec.write_text(json.dumps(payload))

    frozen = dse_plan(workspace.parent, workspace, store, path, spec=version2_spec)

    assert frozen["space"]["floorplan.core_util"] == pytest.approx([0.3, 0.35, 0.4])
    assert frozen["axis_quantization"]["floorplan.core_util"] == {
        "kind": "range",
        "requested": [0.3, 0.4],
        "scale": "linear",
        "step": None,
        "points": 3,
        "quantized": pytest.approx([0.3, 0.35, 0.4]),
        "candidate_count": 3,
    }
    assert frozen["execution"] == {"max_concurrent": 1}
    result = fixtures.dse_run(path, path.parent / "output")
    assert result["status"] == "complete", result
