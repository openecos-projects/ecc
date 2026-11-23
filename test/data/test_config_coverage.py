import json
from pathlib import Path

from chipcompiler.data.config_params import (
    CONFIG_PARAM_SCHEMAS,
    validate_config_registry,
)
from chipcompiler.params import list_schemas

# Template location constants were vendored from the former
# chipcompiler.data.config_params.coverage module: they describe test-only
# traversal policy and belong beside the tests that consume them.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "chipcompiler"
TEMPLATES = {
    "db": _PACKAGE_ROOT / "tools/ecc/configs/db_ecc.json",
    "cts": _PACKAGE_ROOT / "tools/ecc/configs/cts_ecc.json",
    "floorplan": _PACKAGE_ROOT / "tools/ecc/configs/floorplan_ecc.json",
    "dreamplace": _PACKAGE_ROOT / "tools/ecc_dreamplace/configs/dreamplace_ecc.json",
    "routing": _PACKAGE_ROOT / "tools/ecc/configs/routing_ecc.json",
    "filler": _PACKAGE_ROOT / "tools/ecc/configs/filler_ecc.json",
    "rcx": _PACKAGE_ROOT / "tools/ecc/configs/rcx_ecc.json",
    "sta": _PACKAGE_ROOT / "tools/ecc/configs/sta_ecc.json",
    "emir": _PACKAGE_ROOT / "tools/ecc/configs/emir_ecc.json",
    "sizer": _PACKAGE_ROOT / "tools/ecc/configs/sizer_ecc.json",
}
# drc_ecc.json is empty today; add it here once it grows static fields so the
# coverage test starts pinning them.

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
    "floorplan": {
        ("ifp", "temp_directory_path"),
        ("macro_placer", "file_path"),
        ("io_placer", "file_path"),
    },
    "dreamplace": {
        ("aux_input",),
        ("base_design_name",),
        ("def_input",),
        ("lef_input",),
        ("macro_only",),
        ("result_dir",),
        ("verilog_input",),
    },
    "routing": {("RT", "-temp_directory_path")},
    "rcx": {("output",)},
}


def template_fields() -> dict[str, set[tuple[str, ...]]]:
    return {key: _config_fields(path) for key, path in TEMPLATES.items()}


def covered_fields() -> dict[str, set[tuple[str, ...]]]:
    fields: dict[str, set[tuple[str, ...]]] = {}
    # Every registered schema, including the semantic ones and every fanned-out
    # or per-element target, so no template field needs an exemption.
    for schema in list_schemas():
        for target in schema.config_targets:
            fields.setdefault(target.config_key, set()).update(
                _iter_fields(schema.default, target.json_path)
            )
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


def test_config_registry_is_valid():
    assert validate_config_registry() == []


def test_every_template_field_is_explicitly_covered():
    templates = template_fields()
    covered = covered_fields()
    assert templates == covered


def test_schema_defaults_match_template_values():
    templates = {
        config_key: json.loads(path.read_text(encoding="utf-8"))
        for config_key, path in TEMPLATES.items()
    }
    for schema in CONFIG_PARAM_SCHEMAS:
        target = schema.config_target
        if target is None:
            continue
        value = templates[target.config_key]
        for key in target.json_path:
            value = value[key]
        assert schema.default == value, (
            f"{schema.param} default {schema.default!r} drifted from template value {value!r}"
        )
