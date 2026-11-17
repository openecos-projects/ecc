"""Resolve the filler allowlist before passing configuration to iMJ."""

from typing import TYPE_CHECKING

from chipcompiler.utility import json_read, json_write

if TYPE_CHECKING:
    from . import Workspace


def refresh_filler_config(workspace: "Workspace") -> None:
    path = workspace.config["filler"]
    config = json_read(path)
    if not isinstance(config, dict):
        raise FileNotFoundError(f"Filler config missing or corrupt: {path}")
    minimum = config.get("-min_filler_width")
    if minimum is None:
        legacy = config.get("PL", {})
        legacy = legacy.get("Filler", {}) if isinstance(legacy, dict) else {}
        minimum = legacy.get("min_filler_width", 1) if isinstance(legacy, dict) else 1

    profile = workspace.pdk.description.get("tools", {}).get("configs", {}).get("filler", {})
    overrides = workspace.parameters.data.get("config_overrides", {}).get("filler", {})
    selected = overrides.get("MJ", {}).get("-filler", profile.get("MJ", {}).get("-filler", ""))
    if not isinstance(selected, str):
        raise ValueError("filler.-filler must be a whitespace-separated string of cell masters")
    selected = selected.strip() or " ".join(workspace.pdk.fillers)
    if not json_write(path, {"MJ": {"-filler": selected}, "-min_filler_width": minimum}):
        raise OSError(f"Failed to write filler config: {path}")
