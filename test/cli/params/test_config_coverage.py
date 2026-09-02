from chipcompiler.cli.project.config_params import validate_config_registry
from chipcompiler.cli.project.config_params.coverage import covered_fields, template_fields


def test_config_schema_registry_is_valid():
    assert validate_config_registry() == []


def test_every_template_field_is_explicitly_covered():
    templates = template_fields()
    covered = covered_fields()
    assert templates == covered
