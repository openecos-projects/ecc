"""Chip PDN defaults follow IO mode without changing user-owned power meshes."""

from copy import deepcopy

import pytest

from chipcompiler.data.config_params.floorplan import pdn_defaults
from chipcompiler.data.parameter_schema import build_config_overrides, resolve_parameters
from chipcompiler.data.workspace import _load_default_floorplan_config
from chipcompiler.data.workspace.floorplan_pdn import refresh_pdn_defaults


@pytest.fixture
def floorplan():
    return _load_default_floorplan_config()


@pytest.mark.parametrize("pdk", ["ics55", "sg13g2", None])
@pytest.mark.parametrize("mode", ["auto", "file", "io_cell"])
def test_resolved_defaults_match_workspace_mesh(floorplan, pdk, mode):
    resolved, errors = resolve_parameters(
        toml_overrides={"floorplan.io_placer.mode": mode}, pdk=pdk
    )
    assert not errors
    patch = build_config_overrides(resolved)
    expected = deepcopy(floorplan)
    expected["pdn_generator"].update(pdn_defaults(pdk, mode))

    refresh_pdn_defaults(floorplan, {"pdk": pdk, "config_overrides": patch})

    assert floorplan == expected
    assert {
        item.schema.name: {"value": item.value, "default": item.default, "source": item.source}
        for item in resolved
        if item.param
        in ("floorplan.pdn_generator.stripe", "floorplan.pdn_generator.connect_layers")
    } == {
        name: {"value": value, "default": value, "source": "default"}
        for name, value in expected["pdn_generator"].items()
        if name in ("stripe", "connect_layers")
    }


@pytest.mark.parametrize("mode", ["auto", "file"])
def test_mode_switch_restores_core_defaults_and_refresh_is_idempotent(floorplan, mode):
    baseline = deepcopy(floorplan)
    parameters = {
        "pdk": "ics55",
        "config_overrides": {"floorplan": {"io_placer": {"mode": "io_cell"}}},
    }
    refresh_pdn_defaults(floorplan, parameters)
    chip = deepcopy(floorplan)
    assert chip != baseline
    assert [stripe["routing_layer_name"] for stripe in chip["pdn_generator"]["stripe"]] == [
        "MET4",
        "MET5",
        "T4M2",
        "RDL",
    ]
    refresh_pdn_defaults(floorplan, parameters)
    assert floorplan == chip

    parameters["config_overrides"]["floorplan"]["io_placer"]["mode"] = mode
    refresh_pdn_defaults(floorplan, parameters)
    assert floorplan == baseline
    refresh_pdn_defaults(floorplan, parameters)
    assert floorplan == baseline


@pytest.mark.parametrize("name", ["stripe", "connect_layers"])
@pytest.mark.parametrize("custom", [False, True], ids=["explicit-core-default", "custom-list"])
def test_explicit_lists_replace_defaults_independently(floorplan, name, custom):
    value = [] if custom else deepcopy(floorplan["pdn_generator"][name])
    resolved, errors = resolve_parameters(
        toml_overrides={
            "floorplan.io_placer.mode": "io_cell",
            f"floorplan.pdn_generator.{name}": value,
        },
        pdk="ics55",
    )
    assert not errors
    patch = build_config_overrides(resolved)
    expected = deepcopy(floorplan)
    expected["pdn_generator"].update(pdn_defaults("ics55", "io_cell"))
    expected["pdn_generator"][name] = value

    refresh_pdn_defaults(floorplan, {"pdk": "ics55", "config_overrides": patch})
    floorplan["pdn_generator"].update(patch["floorplan"]["pdn_generator"])
    assert floorplan == expected


def test_imported_custom_mesh_is_not_overwritten(floorplan):
    floorplan["io_placer"]["mode"] = "io_cell"
    floorplan["pdn_generator"].update({"stripe": [], "connect_layers": []})
    expected = deepcopy(floorplan)

    refresh_pdn_defaults(floorplan, {"pdk": "ics55"})

    assert floorplan == expected


def test_cli_mode_takes_precedence_over_project_mode(floorplan):
    resolved, errors = resolve_parameters(
        manifest_overrides={"floorplan.io_placer.mode": "io_cell"},
        toml_overrides={"floorplan.io_placer.mode": "file"},
        cli_overrides={"floorplan.io_placer.mode": "io_cell"},
        pdk="ics55",
    )
    assert not errors
    patch = build_config_overrides(resolved)
    refresh_pdn_defaults(floorplan, {"pdk": "ics55", "config_overrides": patch})
    assert {
        name: floorplan["pdn_generator"][name] for name in ("stripe", "connect_layers")
    } == pdn_defaults("ics55", "io_cell")
