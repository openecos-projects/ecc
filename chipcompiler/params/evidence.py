"""Per-step record of the parameters that fed a step, for tracing and review.

``params.json`` sits beside ``req.json``/``rsp.json`` in the step directory. It
is evidence only: nothing reads it back, so the worker's inputs stay
``req.json``-only and the format can evolve freely.
"""

import logging
from collections.abc import Collection, Mapping
from pathlib import Path
from typing import Any

from chipcompiler.data.config_params.common import ParamSchema
from chipcompiler.data.parameter_schema import list_schemas
from chipcompiler.data.workspace import step_config_keys
from chipcompiler.data.workspace.config_overrides import config_path_for_key
from chipcompiler.data.workspace_parameters import (
    PARAM_SOURCES_KEY,
    WORKSPACE_PARAM_OVERRIDES_KEY,
    workspace_param_value,
)
from chipcompiler.utility import json_read, json_write

logger = logging.getLogger(__name__)

EVIDENCE_FILE = "params.json"

# ``ParamSchema.applies`` groups that span several flow steps.
_APPLIES_ALIASES = {
    "synthesis": {"synthesis"},
    "floorplan": {"pre_floorplan", "macro_placement", "post_floorplan"},
    "placement": {"placement", "macro_placement"},
    "fixfanout": {"fixfanout"},
}


def _applies_to_step(applies: str, step_name: str) -> bool:
    from chipcompiler.rtl2gds import normalize_flow_step

    step = normalize_flow_step(step_name).casefold()
    for part in (item.strip() for item in applies.split(",")):
        if part == "all":
            return True
        if step in _APPLIES_ALIASES.get(part.casefold(), {normalize_flow_step(part).casefold()}):
            return True
    return False


def _source(parameters: Mapping[str, object], schema: ParamSchema) -> str:
    """The layer a value came from: workspace edit, recorded creation layer, or default."""
    journal = parameters.get(WORKSPACE_PARAM_OVERRIDES_KEY)
    if isinstance(journal, list) and any(
        isinstance(record, dict) and record.get("key") == schema.param for record in journal
    ):
        return "workspace"
    recorded = parameters.get(PARAM_SOURCES_KEY)
    if isinstance(recorded, Mapping):
        source = recorded.get(schema.param)
        if isinstance(source, str):
            return source
    return "default"


def _config_values(
    workspace: Any, schemas: list[ParamSchema], consumed: Collection[str]
) -> dict[str, dict[str, object]]:
    """The values those parameters hold in the configs the step consumes.

    Keyed by config key and JSON path; targets in configs this step and tool do
    not read (for example a fanned-out DreamPlace layer at the route step) are
    left out so the record shows what actually reaches the tool.
    """
    values: dict[str, dict[str, object]] = {}
    consumed_keys = {key.casefold() for key in consumed}
    for schema in schemas:
        for target in schema.config_targets:
            if target.config_key.casefold() not in consumed_keys:
                continue
            path = config_path_for_key(dict(workspace.config), target.config_key)
            if path is None or not Path(path).is_file():
                continue
            node: object = json_read(path)
            for key in target.json_path:
                node = node.get(key) if isinstance(node, dict) else None
            values.setdefault(target.config_key, {})[".".join(target.json_path)] = node
    return values


def build_step_parameter_record(workspace: Any, step_name: str, tool: str) -> dict[str, Any]:
    """Step-applicable parameters with value, default and source, plus the config they reach."""
    parameters: Mapping[str, object] = workspace.parameters.data
    pdk = str(parameters.get("pdk") or "") or None
    schemas = sorted(
        (
            schema
            for schema in list_schemas()
            if schema.pdk_target is None and _applies_to_step(schema.applies, step_name)
        ),
        key=lambda schema: schema.param,
    )
    records = []
    readable: list[ParamSchema] = []
    for schema in schemas:
        try:
            value = workspace_param_value(workspace, schema)
        except (OSError, ValueError):
            continue
        readable.append(schema)
        records.append(
            {
                "param": schema.param,
                "value": value,
                "default": schema.default_for(pdk),
                "source": _source(parameters, schema),
            }
        )
    return {
        "step": step_name,
        "tool": tool,
        "parameters": records,
        "config": _config_values(workspace, readable, step_config_keys(step_name, tool)),
    }


def write_step_parameter_evidence(workspace: Any, step: Any, directory: Path) -> bool:
    """Write ``params.json`` into *directory*; evidence must never fail the step."""
    try:
        record = build_step_parameter_record(workspace, str(step.name), str(step.tool))
        return json_write(Path(directory) / EVIDENCE_FILE, record)
    except Exception as exc:
        logger.warning("step parameter evidence not written for %s: %s", step.name, exc)
        return False
