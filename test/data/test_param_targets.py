"""Multi-target config parameters: fan-out, transforms, list elements, PDK variants."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from chipcompiler.data.config_params import validate_config_registry
from chipcompiler.data.config_params.common import (
    ConfigTarget,
    ParamSchema,
    PdkVariant,
    flag_to_int,
)
from chipcompiler.data.parameter_schema import (
    ResolvedParam,
    build_config_overrides,
    resolve_parameters,
    validate_value,
)
from chipcompiler.data.workspace_parameters import workspace_param_value

_LAYER = ParamSchema(
    param="route.layer",
    group="route",
    name="layer",
    type="str",
    default="MET2",
    applies="routing",
    description="layer fanned out to two configs",
    config_target=ConfigTarget("route", ("RT", "-layer")),
    extra_config_targets=(ConfigTarget("db", ("LayerSettings", "layer")),),
    choices=("MET1", "MET2"),
    pdk_variants={"sg13g2": PdkVariant("Metal2", ("Metal1", "Metal2"))},
)
_FLAG = ParamSchema(
    param="place.flag",
    group="place",
    name="flag",
    type="int",
    default=1,
    applies="placement",
    description="boolean flag stored as an int",
    config_target=ConfigTarget("dreamplace", ("flag",), flag_to_int, flag_to_int),
)
_MARGIN = ParamSchema(
    param="floorplan.margin",
    group="floorplan",
    name="margin",
    type="list[int]",
    default=[2, 2],
    applies="floorplan",
    description="[horizontal, vertical] margin fanned into per-side scalars",
    config_target=ConfigTarget("Floorplan", ("margin", "left"), element=0),
    extra_config_targets=(
        ConfigTarget("Floorplan", ("margin", "right"), element=0),
        ConfigTarget("Floorplan", ("margin", "top"), element=1),
        ConfigTarget("Floorplan", ("margin", "bottom"), element=1),
    ),
)


def _workspace(tmp_path: Path, configs: dict[str, dict], pdk: str = "ics55") -> SimpleNamespace:
    paths: dict[str, Path] = {}
    for key, document in configs.items():
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_text(json.dumps(document))
    return SimpleNamespace(config=paths, parameters=SimpleNamespace(data={"pdk": pdk}))


def _resolved(schema: ParamSchema, value: object) -> ResolvedParam:
    return ResolvedParam(schema.param, value, schema.default, "workspace", schema)


def test_override_patch_fans_out_to_every_target_with_transforms_and_elements() -> None:
    patch = build_config_overrides(
        [_resolved(_LAYER, "MET1"), _resolved(_FLAG, "on"), _resolved(_MARGIN, [3, 5])]
    )

    assert patch == {
        "route": {"RT": {"-layer": "MET1"}},
        "db": {"LayerSettings": {"layer": "MET1"}},
        "dreamplace": {"flag": 1},
        "Floorplan": {"margin": {"left": 3, "right": 3, "top": 5, "bottom": 5}},
    }


def test_element_target_rejects_a_value_without_that_element() -> None:
    with pytest.raises(ValueError, match="needs element 1"):
        build_config_overrides([_resolved(_MARGIN, [3])])


def test_workspace_value_reads_the_primary_target_through_the_inverse_transform(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, {"dreamplace": {"flag": "yes"}})

    assert workspace_param_value(workspace, _FLAG) == 1


def test_workspace_value_assembles_a_list_from_element_targets(tmp_path: Path) -> None:
    workspace = _workspace(
        tmp_path,
        {"Floorplan": {"margin": {"left": 7, "right": 7, "top": 9, "bottom": 9}}},
    )

    assert workspace_param_value(workspace, _MARGIN) == [7, 9]


def test_workspace_value_falls_back_to_the_default_when_an_element_is_missing(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path, {"Floorplan": {"margin": {"left": 7}}})

    assert workspace_param_value(workspace, _MARGIN) == [2, 2]


def test_pdk_variant_overrides_default_and_choices_only_for_its_family() -> None:
    assert [_LAYER.default_for(pdk) for pdk in (None, "ics55", "SG13G2")] == [
        "MET2",
        "MET2",
        "Metal2",
    ]
    assert validate_value("Metal1", _LAYER, "sg13g2") == []
    assert validate_value("Metal1", _LAYER, "ics55") == [
        "value 'Metal1' not in allowed choices ('MET1', 'MET2') for route.layer"
    ]


def test_workspace_default_follows_the_workspace_pdk(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, {"route": {}}, pdk="sg13g2")

    assert workspace_param_value(workspace, _LAYER) == "Metal2"


def test_resolve_parameters_uses_the_pdk_default() -> None:
    resolved, errors = resolve_parameters(pdk="sg13g2")

    assert errors == []
    assert all(item.default == item.schema.default_for("sg13g2") for item in resolved)


@pytest.mark.parametrize(
    ("schema", "expected"),
    [
        (
            ParamSchema(
                "a.b",
                "a",
                "b",
                "int",
                1,
                "x",
                "d",
                extra_config_targets=(ConfigTarget("route", ("x",)),),
                maps_to="b",
            ),
            ["extra config targets need a primary target: a.b"],
        ),
        (
            ParamSchema(
                "a.c",
                "a",
                "c",
                "int",
                1,
                "x",
                "d",
                config_target=ConfigTarget("route", ("x",), element=0),
            ),
            ["element targets need a list parameter: a.c"],
        ),
    ],
)
def test_registry_validation_rejects_malformed_multi_target_schemas(
    monkeypatch: pytest.MonkeyPatch, schema: ParamSchema, expected: list[str]
) -> None:
    monkeypatch.setattr("chipcompiler.data.config_params.CONFIG_PARAM_SCHEMAS", (schema,))

    assert [error for error in validate_config_registry() if "missing target" not in error] == (
        expected
    )
