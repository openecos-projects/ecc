"""Types for the persisted ``home/flow.json`` ledger document."""

from pathlib import Path
from typing import Literal, NotRequired, Required, TypedDict, cast


class ChecklistStatus(TypedDict, total=False):
    """The gate projection stored beside a step's checklist rows."""

    status: Literal["passed", "blocked", "attention", "unknown"]
    blocked: bool
    failed_items: list[str]
    source: str
    summary: dict
    requirements_status: Literal["none", "present"]
    revision: str
    updated_at: str


FlowStepEntry = TypedDict(
    "FlowStepEntry",
    {
        "name": Required[str],
        "tool": Required[str],
        "state": Required[str],
        "category": NotRequired[str],
        "input_step": NotRequired[str],
        "info": NotRequired[dict],
        "runtime": NotRequired[str],
        "peak memory (mb)": NotRequired[float | int],
        "checklist": NotRequired[list[dict]],
        "checklist_status": NotRequired[ChecklistStatus],
        "resource_observation": NotRequired[dict],
    },
)


class FlowDocument(TypedDict, total=False):
    """The ledger document; unknown keys read by the GUI are preserved."""

    steps: list[FlowStepEntry]
    schema_version: int


def load_flow_document(path: Path | None) -> FlowDocument:
    """Read a ledger; an absent or non-object document loads as an empty one."""
    if path is None:
        return {}
    from chipcompiler.utility import json_read

    raw = json_read(path)
    if not isinstance(raw, dict):
        return {}
    return cast(FlowDocument, raw)  # Shape guards stay in the readers, not the loader.
