"""Pure ecc.toml parameter edits shared by single and batch commands."""

from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key
from chipcompiler.data.step_parameters import STEP_TABLE


def set_parameter(text: str, schema, value: object, step: str | None = None) -> str:
    table, name = parameter_location(schema, step)
    return set_scoped_key(text, table, name, value)


def unset_parameter(text: str, schema, step: str | None = None) -> str | None:
    table, name = parameter_location(schema, step)
    return remove_scoped_key(text, table, name)


def parameter_location(schema, step: str | None = None) -> tuple[str, str]:
    """The ``ecc.toml`` table and key of *schema*; a step value lives under ``params.step``."""
    if schema.pdk_target is not None:
        return "pdk.overrides", schema.pdk_target
    group, _, name = schema.param.rpartition(".")
    if step is not None:
        return f"params.{STEP_TABLE}.{step}.{group}", name
    return f"params.{group}", name
