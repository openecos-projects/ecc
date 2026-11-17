"""Presentation of project parameter values, including per-step values.

A step-scoped (DreamPlace) parameter holds one project value per step,
``[params.step.<step>]`` in ``ecc.toml``, keyed ``<step>:<param>``.
"""

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandContext
from chipcompiler.data.step_parameters import is_step_scoped, step_key


def value_at_step(rp, toml_overrides: dict, step: str | None) -> tuple[object, str]:
    """*rp*'s project value and source at *step* (``[params.step.<step>]`` for a step value)."""
    if step is None or not is_step_scoped(rp.schema):
        return rp.value, rp.source
    key = step_key(step, rp.param)
    if key in toml_overrides:
        return toml_overrides[key], "ecc.toml"
    return rp.default, "default"


def list_record(
    ctx: CommandContext,
    rp,
    toml_overrides: dict,
    step: str | None,
    pdk: str | None,
    *,
    qualified: bool = False,
) -> dict:
    """One ``param list`` row; *qualified* names the step in the key (``placement:place.x``)."""
    s = rp.schema
    project = ctx.project
    value, source = value_at_step(rp, toml_overrides, step)
    param = step_key(step, s.param) if qualified and step is not None else s.param
    record = {
        "param": param,
        "group": s.group,
        "name": s.name,
        "value": value,
        "default": rp.default,
        "source": source,
        "type": s.type,
        "applies": s.applies,
        "maps_to": maps_to_str(s.maps_to),
        "description": s.description,
        "inspect": disclosure_cmd(f"ecc param show {param}", project),
    }
    if s.config_target is not None:
        record["config_target"] = config_target_str(s.config_target)
    if s.pdk_target is not None:
        record["pdk_target"] = pdk_target_str(s.pdk_target)
    if s.range is not None:
        record["range"] = f"[{s.range[0]}, {s.range[1]}]"
    choices = s.choices_for(pdk)
    if choices is not None:
        record["choices"] = ", ".join(choices)
    if s.unit is not None:
        record["unit"] = s.unit
    return record


def step_list_records(ctx: CommandContext, rp, toml_overrides: dict, pdk: str | None) -> list:
    """``param list`` rows of the step values ``ecc.toml`` sets for *rp*."""
    if not is_step_scoped(rp.schema):
        return []
    return [
        list_record(ctx, rp, toml_overrides, step, pdk, qualified=True)
        for step in rp.schema.steps
        if step_key(step, rp.param) in toml_overrides
    ]


def step_diff_records(rp, toml_overrides: dict) -> list[dict]:
    """``param diff`` rows of *rp*'s step values that differ from its default."""
    records = []
    for step in rp.schema.steps if is_step_scoped(rp.schema) else ():
        value, source = value_at_step(rp, toml_overrides, step)
        if value != rp.default:
            records.append(
                {
                    "param": step_key(step, rp.param),
                    "value": value,
                    "default": rp.default,
                    "source": source,
                }
            )
    return records


def maps_to_str(maps_to):
    if maps_to is None:
        return ""
    if isinstance(maps_to, str):
        return maps_to
    parts = [f"{k}.{v}" for k, v in maps_to.items()]
    return ", ".join(parts)


def config_target_str(target) -> str:
    return f"{target.config_key}:{'.'.join(target.json_path)}"


def pdk_target_str(target: str) -> str:
    return f"pdk.overrides:{target}"
