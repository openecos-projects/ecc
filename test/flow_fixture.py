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
    return {"schema_version": 2, "steps": records}


def step_directory(name, tool) -> StepDirectory:
    """Return only the directory field, preserving an explicit category."""
    step_name = name.value if hasattr(name, "value") else str(name)
    return {"directory": new_step_directory(step_name, str(tool))}
