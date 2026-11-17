"""Presentation of project parameter values, including per-step values.

A step-scoped (DreamPlace) parameter holds one project value per step,
``[params.step.<step>]`` in ``ecc.toml``, keyed ``<step>:<param>``;
``resolve_parameters`` returns each set step value as its own record.
"""

from chipcompiler.cli.core.output import disclosure_cmd
from chipcompiler.cli.core.types import CommandContext
from chipcompiler.data.step_parameters import is_step_scoped, step_key


def record_at_step(by_key: dict, rp, step: str | None):
    """The resolved record holding *rp*'s project value at *step*.

    *by_key* maps :attr:`ResolvedParam.key` to its record. A step-scoped
    parameter takes its ``<step>:<param>`` record there, else *rp* (its default).
    """
    if step is None or not is_step_scoped(rp.schema):
        return rp
    return by_key.get(step_key(step, rp.param), rp)


def list_record(
    ctx: CommandContext,
    rp,
    pdk: str | None,
    *,
    step: str | None = None,
    qualified: bool = False,
) -> dict:
    """One ``param list`` row of *rp*.

    In a *step* view the row keeps the plain parameter name unless *qualified*;
    a step-scoped parameter is always inspected at its step (``placement:place.x``).
    """
    s = rp.schema
    inspect_key = step_key(step, s.param) if step is not None and is_step_scoped(s) else rp.key
    record = {
        "param": inspect_key if qualified else (s.param if step is not None else rp.key),
        "group": s.group,
        "name": s.name,
        "value": rp.value,
        "default": rp.default,
        "source": rp.source,
        "type": s.type,
        "applies": s.applies,
        "maps_to": maps_to_str(s.maps_to),
        "description": s.description,
        "inspect": disclosure_cmd(f"ecc param show {inspect_key}", ctx.project),
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
