import json
from pathlib import Path

from . import CONFIG_PARAM_SCHEMAS

_REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATES = {
    "db": _REPO_ROOT / "chipcompiler/tools/ecc/configs/db_ecc.json",
    "CTS": _REPO_ROOT / "chipcompiler/tools/ecc/configs/cts_ecc.json",
    "Floorplan": _REPO_ROOT / "chipcompiler/tools/ecc/configs/floorplan_ecc.json",
    "dreamplace": _REPO_ROOT / "chipcompiler/tools/ecc_dreamplace/configs/dreamplace_ecc.json",
    "route": _REPO_ROOT / "chipcompiler/tools/ecc/configs/route_ecc.json",
    "filler": _REPO_ROOT / "chipcompiler/tools/ecc/configs/filler_ecc.json",
    "RCX": _REPO_ROOT / "chipcompiler/tools/ecc/configs/rcx_ecc.json",
    "sta": _REPO_ROOT / "chipcompiler/tools/ecc/configs/sta_ecc.json",
}

LEGACY_FIELDS = {
    "db": {("LayerSettings", "routing_layer_1st")},
    "CTS": {("max_fanout",)},
    "Floorplan": {
        ("die_builder", "die_util", "utilization"),
        ("die_builder", "die_util", "aspect_ratio"),
        ("die_builder", "margin", "left_micron"),
        ("die_builder", "margin", "right_micron"),
        ("die_builder", "margin", "top_micron"),
        ("die_builder", "margin", "bottom_micron"),
    },
    "dreamplace": {
        ("target_density",),
        ("stop_overflow",),
        ("cell_padding_x",),
        ("routability_opt_flag",),
    },
    "route": {
        ("RT", "-bottom_routing_layer"),
        ("RT", "-top_routing_layer"),
    },
}

PROTECTED_FIELDS = {
    "db": {
        ("INPUT", "tech_lef_path"),
        ("INPUT", "lef_paths"),
        ("INPUT", "def_path"),
        ("INPUT", "verilog_path"),
        ("INPUT", "lib_path"),
        ("INPUT", "sdc_path"),
        ("OUTPUT", "output_dir_path"),
    },
    "Floorplan": {
        ("ifp", "temp_directory_path"),
        ("macro_placer", "macro_location_path"),
    },
    "dreamplace": {
        ("aux_input",),
        ("base_design_name",),
        ("def_input",),
        ("lef_input",),
        ("result_dir",),
        ("verilog_input",),
    },
    "route": {("RT", "-temp_directory_path")},
    "RCX": {("output",)},
    "sta": {("liberty",)},
}


def template_fields() -> dict[str, set[tuple[str, ...]]]:
    return {key: _config_fields(path) for key, path in TEMPLATES.items()}


def covered_fields() -> dict[str, set[tuple[str, ...]]]:
    fields: dict[str, set[tuple[str, ...]]] = {
        key: set(value) for key, value in LEGACY_FIELDS.items()
    }
    for schema in CONFIG_PARAM_SCHEMAS:
        target = schema.config_target
        if target is not None:
            fields.setdefault(target.config_key, set()).add(target.json_path)
    for key, protected in PROTECTED_FIELDS.items():
        fields.setdefault(key, set()).update(protected)
    return fields


def _config_fields(path: Path) -> set[tuple[str, ...]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    return set(_iter_fields(data))


def _iter_fields(value: object, path: tuple[str, ...] = ()):  # noqa: ANN001
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _iter_fields(child, (*path, key))
        return
    yield path
