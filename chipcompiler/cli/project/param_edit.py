"""Pure ecc.toml parameter edits shared by single and batch commands."""

from chipcompiler.cli.project.toml_edit import remove_scoped_key, set_scoped_key


def set_parameter(text: str, schema, value: object) -> str:
    table, name = parameter_location(schema)
    return set_scoped_key(text, table, name, value)


def unset_parameter(text: str, schema) -> str | None:
    table, name = parameter_location(schema)
    return remove_scoped_key(text, table, name)


def parameter_location(schema) -> tuple[str, str]:
    if schema.pdk_target is not None:
        return "pdk.overrides", schema.pdk_target
    group, _, name = schema.param.rpartition(".")
    return f"params.{group}", name
