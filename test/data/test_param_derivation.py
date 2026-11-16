"""derive_parameter_configs: stored and forked parameters reach their tool configs."""

import json
from pathlib import Path
from typing import Any

from chipcompiler.params.targets import derive_parameter_configs

_MANAGED = ("CTS", "route", "db", "dreamplace", "floorplan")


def _configs(tmp_path: Path, documents: dict[str, dict[str, Any]]) -> dict[str, Path]:
    """Every config a forked parameter targets must exist, as in a real workspace."""
    paths: dict[str, Path] = {}
    for key, document in {**dict.fromkeys(_MANAGED, {}), **documents}.items():
        paths[key] = tmp_path / f"{key}.json"
        paths[key].write_text(json.dumps(document))
    return paths


def _read(paths: dict[str, Path], key: str) -> dict[str, Any]:
    return json.loads(paths[key].read_text())


def test_forked_route_layers_reach_every_target_with_the_pdk_default(tmp_path: Path) -> None:
    paths = _configs(
        tmp_path,
        {"route": {"RT": {}}, "db": {"LayerSettings": {}}, "dreamplace": {}},
    )

    derive_parameter_configs(paths, {"pdk": "sg13g2"})

    assert _read(paths, "route") == {
        "RT": {"-bottom_routing_layer": "Metal2", "-top_routing_layer": "Metal5"}
    }
    assert _read(paths, "db") == {"LayerSettings": {"routing_layer_1st": "Metal2"}}
    assert _read(paths, "dreamplace")["gpugr_bottom_routing_layer"] == "Metal2"
    assert _read(paths, "dreamplace")["gpugr_top_routing_layer"] == "Metal5"


def test_stored_core_margin_fans_out_into_per_side_scalars(tmp_path: Path) -> None:
    paths = _configs(tmp_path, {"floorplan": {"die_builder": {}}})

    derive_parameter_configs(paths, {"pdk": "ics55", "core": {"margin": [3, 4]}})

    assert _read(paths, "floorplan")["die_builder"]["margin"] == {
        "left_micron": 3,
        "right_micron": 3,
        "top_micron": 4,
        "bottom_micron": 4,
    }


def test_stored_value_absent_from_the_payload_leaves_the_config_untouched(
    tmp_path: Path,
) -> None:
    document = {"die_builder": {"die_util": {"utilization": 0.5}}}
    paths = _configs(tmp_path, {"floorplan": document})

    derive_parameter_configs(paths, {"pdk": "ics55"})

    assert _read(paths, "floorplan") == document
