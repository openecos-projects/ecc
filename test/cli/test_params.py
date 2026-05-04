import pytest

from chipcompiler.cli.params import (
    PARAM_REGISTRY,
    ParamSchema,
    ResolvedParam,
    build_backend_overrides,
    is_known_key,
    list_groups,
    list_schemas,
    lookup_schema,
    parse_cli_overrides,
    parse_toml_params,
    parse_value,
    resolve_parameters,
    validate_schema_record,
    validate_value,
)

REQUIRED_KEYS = [
    "design.frequency_mhz",
    "floorplan.core_util",
    "floorplan.core_margin",
    "floorplan.aspect_ratio",
    "synth.max_fanout",
    "place.target_density",
    "place.target_overflow",
    "place.global_right_padding",
    "place.cell_padding_x",
    "place.routability_opt",
    "route.bottom_layer",
    "route.top_layer",
]


class TestSchemaRegistry:
    def test_registry_contains_all_required_keys(self):
        params = {s.param for s in PARAM_REGISTRY}
        for key in REQUIRED_KEYS:
            assert key in params, f"Missing key: {key}"

    def test_every_record_has_required_metadata(self):
        required = ("param", "group", "name", "type", "default", "applies", "maps_to", "description")
        for schema in PARAM_REGISTRY:
            for field_name in required:
                val = getattr(schema, field_name, None)
                assert val is not None and val != "", (
                    f"{schema.param} missing required field: {field_name}"
                )

    def test_optional_fields_present_when_relevant(self):
        for schema in PARAM_REGISTRY:
            if schema.type in ("float", "int") and schema.choices is None:
                assert schema.range is not None, (
                    f"{schema.param}: numeric param without range or choices should have range"
                )

    def test_cli_keys_map_to_backend_names(self):
        density = lookup_schema("place.target_density")
        assert density.maps_to == {"DreamPlace": "target_density"}

        fanout = lookup_schema("synth.max_fanout")
        assert fanout.maps_to == "Max fanout"

        util = lookup_schema("floorplan.core_util")
        assert util.maps_to == {"Core": "Utilitization"}

    def test_internal_keys_not_accepted_as_cli_keys(self):
        assert not is_known_key("Core.Utilitization")
        assert not is_known_key("Target density")
        assert not is_known_key("Max fanout")
        assert not is_known_key("Frequency max [MHz]")

    def test_schema_record_missing_required_fields_rejected(self):
        bad = ParamSchema(
            param="", group="", name="", type="int", default=0,
            applies="", maps_to="", description="",
        )
        errors = validate_schema_record(bad)
        assert len(errors) > 0

    def test_lookup_schema_returns_none_for_unknown(self):
        assert lookup_schema("nonexistent.key") is None

    def test_list_groups_returns_ordered_groups(self):
        groups = list_groups()
        assert "design" in groups
        assert "floorplan" in groups
        assert "synth" in groups
        assert "place" in groups
        assert "route" in groups


class TestValueParsing:
    @pytest.mark.parametrize("raw,ptype,expected", [
        ("0.65", "float", 0.65),
        ("42", "int", 42),
        ("true", "bool", True),
        ("false", "bool", False),
        ("MET5", "str", "MET5"),
        ("1.5,2.5", "list[float]", [1.5, 2.5]),
        ("1,2,3", "list[int]", [1, 2, 3]),
        ("a,b,c", "list[str]", ["a", "b", "c"]),
    ])
    def test_parse_value_correct_types(self, raw, ptype, expected):
        schema = lookup_schema("place.target_density")
        schema = ParamSchema(
            param="test", group="test", name="test", type=ptype,
            default=None, applies="test", maps_to="test", description="test",
        )
        result = parse_value(raw, schema)
        assert result == expected

    def test_parse_int_rejects_alpha(self):
        schema = ParamSchema(
            param="test", group="test", name="test", type="int",
            default=0, applies="test", maps_to="test", description="test",
        )
        with pytest.raises(ValueError, match="expected int"):
            parse_value("abc", schema)

    def test_parse_float_rejects_alpha(self):
        schema = ParamSchema(
            param="test", group="test", name="test", type="float",
            default=0.0, applies="test", maps_to="test", description="test",
        )
        with pytest.raises(ValueError, match="expected float"):
            parse_value("not_a_number", schema)

    def test_range_validation_rejects_out_of_bounds(self):
        schema = lookup_schema("place.target_density")
        errors = validate_value(1.2, schema)
        assert len(errors) > 0
        assert "out of range" in errors[0]

    def test_range_validation_accepts_in_bounds(self):
        schema = lookup_schema("place.target_density")
        errors = validate_value(0.5, schema)
        assert errors == []

    def test_choice_validation_rejects_invalid(self):
        schema = lookup_schema("route.top_layer")
        errors = validate_value("MET99", schema)
        assert len(errors) > 0
        assert "not in allowed choices" in errors[0]

    def test_choice_validation_accepts_valid(self):
        schema = lookup_schema("route.top_layer")
        errors = validate_value("MET5", schema)
        assert errors == []

    def test_unknown_key_returns_error_in_cli_overrides(self):
        result, errors = parse_cli_overrides(["unknown.key=5"])
        assert len(errors) > 0
        assert "unknown parameter" in errors[0]

    def test_malformed_key_value_rejected(self):
        result, errors = parse_cli_overrides(["no_equals_sign"])
        assert len(errors) > 0
        assert "malformed" in errors[0]

    def test_out_of_range_value_rejected(self):
        result, errors = parse_cli_overrides(["place.target_density=1.2"])
        assert len(errors) > 0

    def test_type_mismatch_rejected(self):
        result, errors = parse_cli_overrides(["synth.max_fanout=abc"])
        assert len(errors) > 0


class TestSourceAwareResolution:
    def test_default_source_when_no_overrides(self):
        resolved, errors = resolve_parameters()
        assert len(errors) == 0
        for rp in resolved:
            assert rp.source == "default"

    def test_toml_override_source(self):
        toml = {"place.target_density": 0.65}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert errors == []
        density = next(r for r in resolved if r.param == "place.target_density")
        assert density.value == 0.65
        assert density.source == "ecc.toml"

    def test_cli_override_source(self):
        cli = {"place.target_density": 0.7}
        resolved, errors = resolve_parameters(cli_overrides=cli)
        assert errors == []
        density = next(r for r in resolved if r.param == "place.target_density")
        assert density.value == 0.7
        assert density.source == "cli"

    def test_cli_beats_toml(self):
        toml = {"place.target_density": 0.65}
        cli = {"place.target_density": 0.7}
        resolved, errors = resolve_parameters(toml_overrides=toml, cli_overrides=cli)
        assert errors == []
        density = next(r for r in resolved if r.param == "place.target_density")
        assert density.value == 0.7
        assert density.source == "cli"

    def test_invalid_toml_type_produces_error(self):
        toml = {"synth.max_fanout": "not_int"}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert len(errors) > 0

    def test_float_rejected_for_int_schema(self):
        toml = {"synth.max_fanout": 16.5}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert len(errors) > 0

    def test_bool_rejected_for_int_schema(self):
        toml = {"synth.max_fanout": True}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert len(errors) > 0

    def test_int_accepted_for_float_schema(self):
        toml = {"place.target_density": 1}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        # 1 converts to 1.0 which is out of range for target_density
        assert len(errors) > 0  # range validation catches it

    def test_int_in_range_accepted_for_float_schema(self):
        toml = {"floorplan.core_util": 1}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert errors == []
        util = next(r for r in resolved if r.param == "floorplan.core_util")
        assert util.value == 1.0

    def test_float_in_list_int_rejected(self):
        toml = {"floorplan.core_margin": [2.5, 3]}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert len(errors) > 0

    def test_str_rejected_for_int_schema(self):
        toml = {"synth.max_fanout": "abc"}
        resolved, errors = resolve_parameters(toml_overrides=toml)
        assert len(errors) > 0


class TestBackendMapping:
    def test_flat_key_mapping(self):
        schema = lookup_schema("place.target_density")
        rp = ResolvedParam(
            param="place.target_density", value=0.65, default=0.3,
            source="cli", schema=schema,
        )
        result = build_backend_overrides([rp])
        assert result == {"DreamPlace": {"target_density": 0.65}}

    def test_nested_key_mapping(self):
        schema = lookup_schema("floorplan.core_util")
        rp = ResolvedParam(
            param="floorplan.core_util", value=0.45, default=0.4,
            source="cli", schema=schema,
        )
        result = build_backend_overrides([rp])
        assert result == {"Core": {"Utilitization": 0.45}}

    def test_nested_list_mapping(self):
        schema = lookup_schema("floorplan.core_margin")
        rp = ResolvedParam(
            param="floorplan.core_margin", value=(3, 3), default=(2, 2),
            source="cli", schema=schema,
        )
        result = build_backend_overrides([rp])
        assert result == {"Core": {"Margin": (3, 3)}}

    def test_string_key_mapping(self):
        schema = lookup_schema("route.top_layer")
        rp = ResolvedParam(
            param="route.top_layer", value="MET4", default="MET5",
            source="cli", schema=schema,
        )
        result = build_backend_overrides([rp])
        assert result == {"Top layer": "MET4"}

    def test_default_values_excluded(self):
        resolved, _ = resolve_parameters()
        result = build_backend_overrides(resolved)
        assert result == {}

    def test_mapping_does_not_mutate_schema_defaults(self):
        schema = lookup_schema("place.target_density")
        original_default = schema.default
        rp = ResolvedParam(
            param="place.target_density", value=0.65, default=original_default,
            source="cli", schema=schema,
        )
        build_backend_overrides([rp])
        assert schema.default == original_default


class TestCliOverrides:
    def test_repeatable_set(self):
        result, errors = parse_cli_overrides([
            "place.target_density=0.65",
            "synth.max_fanout=16",
        ])
        assert errors == []
        assert result == {"place.target_density": 0.65, "synth.max_fanout": 16}

    def test_malformed_rejected(self):
        result, errors = parse_cli_overrides(["noequals"])
        assert len(errors) > 0

    def test_unknown_key_rejected(self):
        result, errors = parse_cli_overrides(["bogus.key=5"])
        assert len(errors) > 0

    def test_raw_backend_key_rejected(self):
        result, errors = parse_cli_overrides(["Target density=0.5"])
        assert len(errors) > 0

    def test_invalid_value_does_not_produce_override(self):
        result, errors = parse_cli_overrides(["place.target_density=1.5"])
        assert "place.target_density" not in result
        assert len(errors) > 0


class TestTomlParams:
    def test_flat_toml_parsing(self):
        table = {"place": {"target_density": 0.65}}
        flat, errors = parse_toml_params(table)
        assert errors == []
        assert flat == {"place.target_density": 0.65}

    def test_unknown_toml_key_rejected(self):
        table = {"bogus": {"key": 5}}
        flat, errors = parse_toml_params(table)
        assert len(errors) > 0
        assert "unknown parameter" in errors[0]

    def test_non_table_toml_section_rejected(self):
        table = {"place": "not_a_table"}
        flat, errors = parse_toml_params(table)
        assert len(errors) > 0
