"""Merge a tool's PDK-neutral defaults with its sparse PDK-specific override.

Each tool owns `configs/defaults/<name>.json` (complete, PDK-independent) and
`configs/pdk/<pdk.config_variant>/<name>.json` (sparse, only the fields that
differ for that PDK release). Objects merge recursively; arrays and scalars
in the override replace the default.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.data.parameter import update_parameters
from chipcompiler.utility import json_read

if TYPE_CHECKING:
    from chipcompiler.data.pdk import PDK


def tool_config(tool_configs_dir: Path, name: str, pdk: "PDK") -> dict:
    """Return `defaults/<name>` deep-merged with `pdk/<pdk.config_variant>/<name>`."""
    default_path = tool_configs_dir / "defaults" / name
    config = json_read(default_path)
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
