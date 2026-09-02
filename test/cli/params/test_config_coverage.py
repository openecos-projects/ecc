import json

from chipcompiler.cli.project.config_params import (
    CONFIG_PARAM_SCHEMAS,
    validate_config_registry,
)
from chipcompiler.cli.project.config_params.coverage import (
    TEMPLATES,
    covered_fields,
    template_fields,
)


def test_config_schema_registry_is_valid():
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
