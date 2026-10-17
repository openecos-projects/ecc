#!/usr/bin/env python
"""Read-only preflight facts for workspace step execution."""

from dataclasses import fields
from pathlib import Path


def build_run_preflight(flow, selected: list[str], *, only: str | None, force: bool) -> dict:
    """Describe the selected steps without changing workspace state."""
    steps_by_name = {step.name: step for step in getattr(flow, "workspace_steps", ())}
    step_facts = []
    missing = []
    for name in selected:
        step = steps_by_name.get(name)
        inputs = {}
        if step is not None:
            for field in fields(step.input):
                value = getattr(step.input, field.name)
                if value is None:
                    continue
                path = Path(value)
                input_name = "def" if field.name == "def_" else field.name
                inputs[input_name] = {"path": str(path), "exists": path.exists()}
                if not path.exists():
                    missing.append({"step": name, "input": input_name, "path": str(path)})
        step_facts.append(
            {
                "step": name,
                "tool": getattr(step, "tool", None),
                "inputs": inputs,
            }
        )
    return {
        "selector": {"only": only, "force": force},
        "selected_steps": step_facts,
        "missing_inputs": missing,
        "ready": not missing,
    }


def output_paths(flow, executed: list[str]) -> dict[str, list[str]]:
    """Return existing and declared output paths for executed steps."""
    steps_by_name = {step.name: step for step in getattr(flow, "workspace_steps", ())}
    result = {}
    for name in executed:
        step = steps_by_name.get(name)
        paths = []
        if step is not None:
            for field in fields(step.output):
                value = getattr(step.output, field.name)
                values = value if isinstance(value, list) else [value]
                for path in values:
                    if path:
                        paths.append(str(path))
        result[name] = paths
    return result
