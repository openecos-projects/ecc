"""Helpers for current flow-ledger fixtures.

These helpers fill required ``directory`` and ``category`` fields while
preserving each fixture's unindexed directory names.
"""

from collections.abc import Iterable, Mapping
from typing import Any, TypedDict, cast

from chipcompiler.data.step import new_step_directory
from chipcompiler.data.types import default_flow_step_category
from chipcompiler.data.workspace.flow_types import FlowDocument, FlowStepEntry


class StepFields(TypedDict):
    category: str
    directory: str


class StepDirectory(TypedDict):
    directory: str


def step_fields(name, tool) -> StepFields:
    """Return the required metadata for one current ledger step record."""
    step_name = name.value if hasattr(name, "value") else str(name)
    return {
        "category": default_flow_step_category(step_name).value,
        "directory": new_step_directory(step_name, str(tool)),
    }


def current_flow_document(steps: Iterable[Mapping[str, Any]]) -> FlowDocument:
    """Build a schema-v2 ledger, adding only missing per-step metadata."""
    records: list[FlowStepEntry] = []
    for step in steps:
        record = dict(step)
        fields = step_fields(record["name"], record["tool"])
        for key, value in fields.items():
            record.setdefault(key, value)
        records.append(cast(FlowStepEntry, record))
    return {"schema_version": 3, "steps": records}


def step_directory(name, tool) -> StepDirectory:
    """Return only the directory field, preserving an explicit category."""
    step_name = name.value if hasattr(name, "value") else str(name)
    return {"directory": new_step_directory(step_name, str(tool))}


def publish_response(workspace_directory, step_directory: str):
    """Publish the successful rsp.json a run of the step in *step_directory* writes.

    The design carries every design state, and each analysis item the step
    provides names one file. Returns the link a downstream request accepts.
    """
    from chipcompiler.data.handshake import (
        DesignFiles,
        ResponseStatus,
        StepResponse,
        UpstreamResponse,
        write_response,
    )
    from chipcompiler.data.step import unindexed_step_directory
    from chipcompiler.data.types import AnalysisData, DesignState, ToolName, flow_step_policy

    name = unindexed_step_directory(step_directory)
    tool = next(tool.value for tool in ToolName if name.endswith(f"_{tool.value}"))
    step = name.removesuffix(f"_{tool}")
    directory = workspace_directory / step_directory
    attempt_id = f"attempt-{step}"
    write_response(
        directory,
        StepResponse(
            step=step,
            tool=tool,
            attempt_id=attempt_id,
            status=ResponseStatus.SUCCESS,
            design=DesignFiles(),
            design_states=frozenset(DesignState),
            outputs={
                item: (directory / "output" / item.value,)
                for item in flow_step_policy(step).provides
                if isinstance(item, AnalysisData)
            },
            design_source=None,
            upstream={},
            warnings=frozenset(),
        ),
    )
    return UpstreamResponse(step_directory, attempt_id)
