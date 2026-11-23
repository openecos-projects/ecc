"""Merge a tool's PDK-neutral defaults with its sparse PDK-specific override.

Each tool owns `configs/defaults/<name>.json` (complete, PDK-independent) and
`configs/pdk/<pdk.config_variant>/<name>.json` (sparse, only the fields that
differ for that PDK release). Objects merge recursively; arrays and scalars
in the override replace the default.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.data.parameter import update_parameters
from chipcompiler.utility import json_read, json_read_strict

if TYPE_CHECKING:
    from chipcompiler.data.pdk import PDK

    from . import Workspace


def tool_config(tool_configs_dir: Path, name: str, pdk: "PDK") -> dict:
    """Return `defaults/<name>` deep-merged with `pdk/<pdk.config_variant>/<name>`."""
    default_path = tool_configs_dir / "defaults" / name
    config = json_read_strict(default_path)
    if not isinstance(config, dict):
        raise FileNotFoundError(f"default config missing or corrupt: {default_path}")
    variant = pdk.config_variant
    if not variant:
        return config
    override_path = tool_configs_dir / "pdk" / variant / name
    if not override_path.is_file():
        return config
    override = json_read(override_path)
    if not isinstance(override, dict):
        raise FileNotFoundError(f"PDK override config is corrupt: {override_path}")
    return update_parameters(override, config)


def write_missing_tool_configs(workspace: "Workspace") -> None:
    """Populate each tool's missing workspace config files from its defaults,
    merged with the workspace PDK's sparse override for that tool."""
    import os
    import shutil

    from chipcompiler.utility import json_write

    root_dir = Path(__file__).resolve().parent.parent.parent
    config_dir = workspace.config["dir"]
    os.makedirs(config_dir, exist_ok=True)

    ecc_configs_dir = root_dir / "tools" / "ecc" / "configs"
    for name in sorted(os.listdir(ecc_configs_dir / "defaults")):
        source = ecc_configs_dir / "defaults" / name
        destination = config_dir / name
        if not source.is_file() or destination.exists():
            continue
        if name.endswith(".json"):
            json_write(destination, tool_config(ecc_configs_dir, name, workspace.pdk))
        else:
            shutil.copy2(source, destination)

    for key in ("dreamplace", "sizer"):
        destination = workspace.config[key]
        if destination.exists():
            continue
        tool_configs_dir = root_dir / "tools" / f"ecc_{key}" / "configs"
        json_write(destination, tool_config(tool_configs_dir, destination.name, workspace.pdk))
