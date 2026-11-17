"""Per-step values of step-scoped parameters (the DreamPlace config).

Each DreamPlace step resolves its own config into its step directory, so a
DreamPlace parameter holds one value per flow step instead of one workspace
value. Step values live in the parameter payload under ``step_params``
(``[params.step_params.<step>]`` in ``params.toml``)::

    step_params = {"placement": {"place.target_density": 0.7}, "diff_opt": {...}}

The workspace ``config/dreamplace_ecc.json`` stays the baseline every step
starts from; a step's values are replayed onto it as that step's direct
config patch when the step builds its config.

Project inputs name the step in the key, ``<step>:<param>``: ``[params.step.
<step>]`` tables in ``ecc.toml`` and ``--set <step>:<param>=<value>``.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Final

from chipcompiler.data.config_params.common import ParamSchema

STEP_PARAMS_KEY: Final = "step_params"
#: The config whose parameters are step-scoped.
STEP_SCOPED_CONFIG: Final = "dreamplace"
#: Separator between the step and the parameter in a project override key.
STEP_KEY_SEPARATOR: Final = ":"
#: ``ecc.toml`` table holding step values: ``[params.step.<step>.<group>]``.
STEP_TABLE: Final = "step"


class ParameterStepError(ValueError):
    """A step-scoped parameter set without a step, or on a step it does not apply to."""

    def __init__(self, code: str, param: str, step: str | None, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.param = param
        self.step = step


def is_step_scoped(schema: ParamSchema) -> bool:
    """Whether *schema* holds one value per step: its primary target is the DreamPlace config."""
    target = schema.config_target
    return target is not None and target.config_key == STEP_SCOPED_CONFIG


def check_parameter_step(schema: ParamSchema, step: str | None) -> str | None:
    """*step* if it is a valid scope for *schema*; raises :class:`ParameterStepError` otherwise.

    A step-scoped parameter needs one of its declared steps; any other
    parameter is workspace-wide and takes ``None`` (a step there only names
    the step view it was edited from, which must still be declared).
    """
    if step is None:
        if is_step_scoped(schema):
            raise ParameterStepError(
                "parameter_step_required",
                schema.param,
                None,
                f"{schema.param} is set per step; name one of: {', '.join(schema.steps)}",
            )
        return None
    if not schema.applies_to(step) and not schema.workspace_wide:
        raise ParameterStepError(
            "parameter_not_applicable",
            schema.param,
            step,
            f"{schema.param} does not apply to step {step}",
        )
    return step


def step_key(step: str, param: str) -> str:
    return f"{step}{STEP_KEY_SEPARATOR}{param}"


def split_step_key(key: str) -> tuple[str | None, str]:
    """``("placement", "place.x")`` for ``"placement:place.x"``; ``(None, key)`` otherwise."""
    step, separator, param = key.partition(STEP_KEY_SEPARATOR)
    return (step.strip(), param.strip()) if separator else (None, key)


def step_values(parameters: Mapping[str, object]) -> dict[str, dict[str, object]]:
    raw = parameters.get(STEP_PARAMS_KEY)
    if not isinstance(raw, Mapping):
        return {}
    return {str(step): dict(values) for step, values in raw.items() if isinstance(values, Mapping)}


def step_value(parameters: Mapping[str, object], step: str, param: str, missing: object) -> object:
    values = step_values(parameters).get(step, {})
    return deepcopy(values[param]) if param in values else missing


def set_step_value(parameters: dict, step: str, param: str, value: object) -> None:
    values = step_values(parameters)
    values.setdefault(step, {})[param] = deepcopy(value)
    parameters[STEP_PARAMS_KEY] = values


def unset_step_value(parameters: dict, step: str, param: str) -> None:
    values = step_values(parameters)
    values.get(step, {}).pop(param, None)
    values = {name: entries for name, entries in values.items() if entries}
    if values:
        parameters[STEP_PARAMS_KEY] = values
    else:
        parameters.pop(STEP_PARAMS_KEY, None)


def step_config_patch(parameters: Mapping[str, object], step: str) -> dict:
    """*step*'s values as a direct config patch (``{config_key: {json path...}}``)."""
    from chipcompiler.data.parameter_schema import ResolvedParam, config_patch, lookup_schema

    resolved = []
    for param, value in step_values(parameters).get(step, {}).items():
        schema = lookup_schema(param)
        if schema is not None:
            resolved.append(ResolvedParam(param, value, schema.default, "workspace", schema))
    return config_patch(resolved)


def step_parameter_view(parameters: Mapping[str, object], step: str) -> dict:
    """The parameter payload as *step* sees it: its values merged into the config patch.

    The step's patch is merged over the workspace patch, so builders that
    replay ``config_overrides`` (and treat its keys as explicit) apply the
    step's own values without knowing about steps.
    """
    from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY

    view = deepcopy(dict(parameters))
    patch = step_config_patch(parameters, step)
    if not patch:
        return view
    merged = view.get(CONFIG_OVERRIDES_KEY)
    merged = deepcopy(merged) if isinstance(merged, dict) else {}
    for config_key, values in patch.items():
        # Config keys match case-insensitively (``config_path_for_key``); merge
        # into the workspace spelling so the step value is not a losing sibling.
        existing = next((key for key in merged if key.casefold() == config_key.casefold()), None)
        _merge(merged, {existing or config_key: values})
    view[CONFIG_OVERRIDES_KEY] = merged
    return view


def _merge(target: dict, patch: Mapping) -> None:
    for key, value in patch.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = deepcopy(value)


def resolve_step_parameters(
    *layers: tuple[Mapping[str, object], str],
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    """Step values and their sources from ``<step>:<param>`` keys of override *layers*.

    *layers* are ``(overrides, source)`` pairs, highest precedence first, as
    produced by ``parse_toml_params`` / ``parse_cli_overrides``.
    """
    values: dict[str, dict[str, object]] = {}
    sources: dict[str, str] = {}
    for overrides, source in reversed(layers):
        for key, value in overrides.items():
            step, param = split_step_key(key)
            if step is None:
                continue
            values.setdefault(step, {})[param] = deepcopy(value)
            sources[key] = source
    return values, sources


def parse_step_key(key: str) -> tuple[str | None, ParamSchema | None, str | None]:
    """``(step, schema, error)`` for a possibly step-qualified parameter *key*."""
    from chipcompiler.data.parameter_schema import lookup_schema

    step, param = split_step_key(key)
    schema = lookup_schema(param)
    if schema is None:
        return step, None, f"unknown parameter: '{param}'"
    try:
        check_parameter_step(schema, step)
    except ParameterStepError as exc:
        return step, schema, str(exc)
    if step is not None and not is_step_scoped(schema):
        return step, schema, f"{param} is workspace-wide; drop the '{step}:' step prefix"
    return step, schema, None
