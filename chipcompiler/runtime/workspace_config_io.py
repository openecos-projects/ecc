#!/usr/bin/env python

"""Workspace configuration IO helpers for the runtime API.

Config-staging policy extracted from the runtime API: RPC creation payload
conversion and the format-agnostic staging used by layout-edit publish.
"""

import json
import tomllib
from pathlib import Path
from typing import Any


def canonical_request_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize an RPC creation payload to the canonical flat vocabulary.

    GUI flat keys (including the positional geometry aliases) and any legacy
    long keys are both converted here; the result is merged verbatim by the
    workspace layer.
    """
    if not parameters:
        return {}
    from chipcompiler.data.parameter_keys import geometry_to_parameters

    return geometry_to_parameters(parameters)


def read_workspace_config_toml(path: Path) -> None:
    """Validate that a staged workspace config artifact is parseable TOML."""
    try:
        with open(path, "rb") as file:
            tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"failed to read workspace config artifact: {path}") from exc


def workspace_config_bytes(data: dict[str, Any], workspace) -> bytes:
    """Render a workspace configuration TOML document for staging."""
    from chipcompiler.data.workspace_config import render_workspace_config

    workspace_dir = getattr(workspace, "directory", None)
    if workspace_dir is None:
        raise ValueError("workspace directory is missing")
    payload = dict(data)
    flow = payload.pop("_flow", None)
    return render_workspace_config(Path(workspace_dir), payload, flow)


def workspace_state_bytes(kind: str, data: dict[str, Any], workspace, target: Path) -> bytes:
    """Serialize one staged workspace-state artifact in its persisted format.

    The parameters artifact persists as the TOML workspace config when its
    target carries a .toml suffix; every other artifact is JSON.
    """
    if kind == "parameters" and target.suffix == ".toml":
        return workspace_config_bytes(data, workspace)
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def read_workspace_state(kind: str, path: Path) -> None:
    """Validate that a staged artifact parses in its persisted format."""
    if kind == "parameters" and path.suffix == ".toml":
        read_workspace_config_toml(path)
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"failed to read JSON artifact: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"JSON artifact must contain an object: {path}")
