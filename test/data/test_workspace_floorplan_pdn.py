"""Chip PDN defaults follow IO mode without changing user-owned power meshes."""

import json
from copy import deepcopy

import pytest

from chipcompiler.data.config_params.floorplan import pdn_defaults
from chipcompiler.data.parameter_schema import build_config_overrides, resolve_parameters
from chipcompiler.data.pdk import PDK, get_pdk
from chipcompiler.data.workspace import _load_default_floorplan_config
from chipcompiler.data.workspace.floorplan_pdn import refresh_pdn_defaults


@pytest.fixture(params=["v1", "v2"])
def pdk(request):
    return PDK(name="ics55", version=request.param)


@pytest.fixture
def floorplan(pdk):
    return _load_default_floorplan_config(pdk)


@pytest.mark.parametrize("pdk_name", ["ics55", "sg13g2", "custom", None])
@pytest.mark.parametrize("mode", ["auto", "file", "io_cell"])
def test_resolved_defaults_match_workspace_mesh(pdk_name, mode):
    pdk = get_pdk(pdk_name or "", validate=False)
    floorplan = _load_default_floorplan_config(pdk)
    resolved, errors = resolve_parameters(
        toml_overrides={"floorplan.io_placer.mode": mode}, pdk=pdk_name
    )
    assert not errors
    patch = build_config_overrides(resolved)
    expected = deepcopy(floorplan)
    expected["pdn_generator"].update(pdn_defaults(pdk, mode))

    refresh_pdn_defaults(floorplan, {"config_overrides": patch}, pdk)

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
def test_mode_switch_restores_core_defaults_and_refresh_is_idempotent(floorplan, pdk, mode):
    baseline = deepcopy(floorplan)
    parameters = {
        "pdk": "ics55",
        "config_overrides": {"floorplan": {"io_placer": {"mode": "io_cell"}}},
    }
    refresh_pdn_defaults(floorplan, parameters, pdk)
    chip = deepcopy(floorplan)
    assert chip != baseline
    assert [stripe["routing_layer_name"] for stripe in chip["pdn_generator"]["stripe"]] == [
        "MET4",
        "MET5",
        "T4M2",
        "RDL",
    ]
    refresh_pdn_defaults(floorplan, parameters, pdk)
    assert floorplan == chip

    parameters["config_overrides"]["floorplan"]["io_placer"]["mode"] = mode
    refresh_pdn_defaults(floorplan, parameters, pdk)
    assert floorplan == baseline
    refresh_pdn_defaults(floorplan, parameters, pdk)
    assert floorplan == baseline


@pytest.mark.parametrize("name", ["stripe", "connect_layers"])
@pytest.mark.parametrize("custom", [False, True], ids=["explicit-core-default", "custom-list"])
def test_explicit_lists_replace_defaults_independently(floorplan, pdk, name, custom):
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
    expected["pdn_generator"].update(pdn_defaults(pdk, "io_cell"))
    expected["pdn_generator"][name] = value

    refresh_pdn_defaults(floorplan, {"config_overrides": patch}, pdk)
    floorplan["pdn_generator"].update(patch["floorplan"]["pdn_generator"])
    assert floorplan == expected


def test_imported_custom_mesh_is_not_overwritten(floorplan, pdk):
    floorplan["io_placer"]["mode"] = "io_cell"
    floorplan["pdn_generator"].update({"stripe": [], "connect_layers": []})
    expected = deepcopy(floorplan)

    refresh_pdn_defaults(floorplan, {}, pdk)

    assert floorplan == expected


def test_cli_mode_takes_precedence_over_project_mode(floorplan, pdk):
    resolved, errors = resolve_parameters(
        manifest_overrides={"floorplan.io_placer.mode": "io_cell"},
        toml_overrides={"floorplan.io_placer.mode": "file"},
        cli_overrides={"floorplan.io_placer.mode": "io_cell"},
        pdk="ics55",
    )
    assert not errors
    patch = build_config_overrides(resolved)
    refresh_pdn_defaults(floorplan, {"config_overrides": patch}, pdk)
    assert {
        name: floorplan["pdn_generator"][name] for name in ("stripe", "connect_layers")
    } == pdn_defaults(pdk, "io_cell")


@pytest.mark.parametrize("name", ["stripe", "connect_layers"])
def test_pdk_carried_mesh_wins_over_shipped_chip_defaults(tmp_path, pdk, name):
    pdk.root = tmp_path
    override = tmp_path / "ecc-configs" / "ecc" / "floorplan_ecc.json"
    override.parent.mkdir(parents=True)
    # Even an explicit list equal to the shipped core baseline is user-owned.
    custom = pdn_defaults(pdk, "auto")[name]
    override.write_text(json.dumps({"pdn_generator": {name: custom}}))
    floorplan = _load_default_floorplan_config(pdk)
    expected = deepcopy(floorplan)
    expected["pdn_generator"].update(pdn_defaults(pdk, "io_cell"))
    expected["pdn_generator"][name] = custom

    refresh_pdn_defaults(
        floorplan, {"config_overrides": {"floorplan": {"io_placer": {"mode": "io_cell"}}}}, pdk
    )

    assert floorplan == expected


def test_pdk_carried_io_cell_mesh_overrides_both_common_and_shipped_defaults(tmp_path, pdk):
    pdk.root = tmp_path
    common = tmp_path / "ecc-configs" / "ecc" / "floorplan_ecc.json"
    mode = common.parent / "io_cell" / common.name
    mode.parent.mkdir(parents=True)
    common.write_text(json.dumps({"pdn_generator": {"stripe": [], "connect_layers": []}}))
    custom = {"stripe": [{"routing_layer_name": "TOP"}], "connect_layers": []}
    mode.write_text(json.dumps({"pdn_generator": custom}))

    assert pdn_defaults(pdk, "io_cell") == custom
    assert pdn_defaults(pdk, "auto") == {"stripe": [], "connect_layers": []}
