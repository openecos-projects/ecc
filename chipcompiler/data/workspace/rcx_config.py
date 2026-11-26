"""Resolve native RCX process inputs without conflating RC and GDS layer maps."""

from pathlib import Path
from shutil import copyfile
from typing import TYPE_CHECKING

from chipcompiler.data.parameter import update_parameters
from chipcompiler.utility import JsonReadError, json_read_strict, json_write

from .tool_configs import tool_config

if TYPE_CHECKING:
    from . import Workspace


def refresh_rcx_config(workspace: "Workspace") -> None:
    config_path = workspace.config["rcx"]
    current = json_read_strict(config_path)
    if not isinstance(current, dict):
        raise JsonReadError(f"RCX config must be an object: {config_path}")
    configs_dir = Path(__file__).resolve().parents[2] / "tools" / "ecc" / "configs"
    # Existing configs from the former built-in backend lack process inputs.
    # Fill absent keys from the PDK profile, preserving explicit overrides.
    config = update_parameters(current, tool_config(configs_dir, config_path.name, workspace.pdk))

    bundled_map = configs_dir / "pdk" / workspace.pdk.config_variant / "rcx_layers.map"
    workspace_map = config_path.with_name("rcx_layers.map")
    if config.get("mapping_file", "") in ("", str(workspace_map)) and bundled_map.is_file():
        if not workspace_map.is_file() or workspace_map.read_bytes() != bundled_map.read_bytes():
            copyfile(bundled_map, workspace_map)
        config["mapping_file"] = str(workspace_map)

    def resolve_path(record: dict, key: str) -> None:
        if not record.get(key):
            return
        path = Path(record[key])
        if not path.is_absolute():
            if workspace.pdk.root is None:
                raise ValueError(f"RCX {key} needs a PDK root: {path}")
            path = workspace.pdk.root / path
        record[key] = str(path)

    resolve_path(config, "mapping_file")
    for corner in config.get("corners", []):
        for key in ("process_file", "itf_file", "captab_file"):
            resolve_path(corner, key)
    if not json_write(config_path, config):
        raise OSError(f"Failed to write RCX config: {config_path}")
