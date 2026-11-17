"""ParamSchema.steps: the one parse of ``applies`` every step-scoped consumer shares."""

from chipcompiler.data.config_params.common import ParamSchema
from chipcompiler.params import list_schemas


def _schema(applies: str) -> ParamSchema:
    return ParamSchema("a.b", "a", "b", "int", 1, applies, "d")


def test_registry_names_only_canonical_flow_steps() -> None:
    assert [error for schema in list_schemas() for error in schema.applies_errors()] == []


def test_steps_parse_a_step_list_and_leave_workspace_and_pdk_scopes_empty() -> None:
    assert [_schema(applies).steps for applies in ("placement, diff_opt", "all", "pdk")] == [
        ("placement", "diff_opt"),
        (),
        (),
    ]


def test_a_step_view_lists_declared_steps_and_workspace_wide_parameters_at_the_first_step() -> None:
    views = {
        (applies, step): _schema(applies).listed_at(step, "synthesis")
        for applies in ("placement", "all")
        for step in ("synthesis", "placement", "macro_placement")
    }

    assert views == {
        ("placement", "synthesis"): False,
        ("placement", "placement"): True,
        ("placement", "macro_placement"): False,
        ("all", "synthesis"): True,
        ("all", "placement"): False,
        ("all", "macro_placement"): False,
    }
