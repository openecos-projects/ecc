"""Workspace edits cannot diverge from frozen literal primary-clock commands."""

from copy import deepcopy

import pytest

from chipcompiler.data.parameter import Parameters
from chipcompiler.data.parameter_schema import lookup_schema
from chipcompiler.data.pdk import PDK
from chipcompiler.data.workspace import OriginDesign, Workspace
from chipcompiler.data.workspace.parameters import (
    set_workspace_param,
    unset_workspace_param,
    update_workspace_param_value,
)
from chipcompiler.data.workspace.sdc_inputs import SdcInputs


@pytest.fixture
def timing_workspace(tmp_path):
    inputs = SdcInputs(
        primary_clocks="create_clock -name BUS -period 12.5 [get_ports clk]\n"
        "create_clock -name AUX -period 40 [get_ports aux]\n"
    )
    return Workspace(
        directory=tmp_path,
        design=OriginDesign(name="chip"),
        pdk=PDK(),
        parameters=Parameters(data=inputs.parameters()),
    )


@pytest.mark.parametrize("mutation", [set_workspace_param, update_workspace_param_value])
@pytest.mark.parametrize("existing_override", [False, True])
def test_conflicting_frequency_edit_leaves_parameters_and_journal_unchanged(
    timing_workspace, mutation, existing_override
):
    schema = lookup_schema("design.frequency_mhz")
    if existing_override:
        update_workspace_param_value(timing_workspace, schema, 80.0)
    before = deepcopy(timing_workspace.parameters.data)

    with pytest.raises(ValueError, match="primary_clocks"):
        mutation(timing_workspace, schema, 200.0)

    assert timing_workspace.parameters.data == before


def test_matching_frequency_can_be_set_and_unset(timing_workspace):
    schema = lookup_schema("design.frequency_mhz")
    before = deepcopy(timing_workspace.parameters.data)

    update_workspace_param_value(timing_workspace, schema, 80.0)
    unset_workspace_param(timing_workspace, schema)

    assert timing_workspace.parameters.data == before


@pytest.mark.parametrize("baseline", [80.0, 200.0])
def test_unset_validates_the_restored_frequency_before_removing_its_record(
    timing_workspace, baseline
):
    schema = lookup_schema("design.frequency_mhz")
    # A journal saved before this guard can contain inconsistent metadata.
    data = timing_workspace.parameters.data
    data["frequency_max"] = 150.0
    data["workspace_param_overrides"] = [
        {"key": "design.frequency_mhz", "baseline": baseline, "value": 150.0}
    ]
    before = deepcopy(data)
    if baseline == 200.0:
        with pytest.raises(ValueError, match="primary_clocks"):
            unset_workspace_param(timing_workspace, schema)
        assert data == before
    else:
        unset_workspace_param(timing_workspace, schema)
        assert data == SdcInputs.from_parameters(before).parameters()
