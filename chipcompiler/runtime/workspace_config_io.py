#!/usr/bin/env python

"""Workspace configuration IO helpers for the runtime API.

Config-staging policy extracted from the runtime API: RPC creation payload
conversion and the TOML staging used by layout-edit publish.
"""

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
