"""Merge a tool's PDK-neutral defaults with its sparse PDK-specific overrides.

Each tool owns `configs/defaults/<name>.json` (complete, PDK-independent).
Two sparse override layers may sit on top, least specific first:

1. `configs/pdk/<pdk.config_variant>/<name>.json`, shipped with ECC for the
   releases it knows about;
2. `<pdk root>/ecc-configs/<tool>/<name>.json`, carried by the PDK tree
   itself, so a PDK ECC has never heard of can supply its own tool settings
   instead of every project restating them under `[config_overrides]`.

Objects merge recursively; arrays and scalars in an override replace what is
under them.
"""

from pathlib import Path
from typing import TYPE_CHECKING

from chipcompiler.data.parameter import update_parameters
from chipcompiler.utility import JsonReadError, json_read_strict

if TYPE_CHECKING:
    from chipcompiler.data.pdk import PDK

    from . import Workspace


#: Directory inside a PDK root holding that PDK's own point-tool overrides,
#: laid out as `<PDK_ROOT_CONFIG_DIR>/<tool package name>/<config name>.json`.
PDK_ROOT_CONFIG_DIR = "ecc-configs"


def _object_from(path: Path, label: str) -> dict:
    """Read a JSON object, refusing a missing, malformed or non-object file."""
    data = json_read_strict(path)
    if not isinstance(data, dict):
        raise JsonReadError(f"{label} must be an object: {path}")
    return data


def _override_paths(tool_configs_dir: Path, name: str, pdk: "PDK") -> list[Path]:
    """Candidate override files for *name*, least specific first."""
    paths: list[Path] = []
    if pdk.config_variant:
        paths.append(tool_configs_dir / "pdk" / pdk.config_variant / name)
    if pdk.root is not None:
        # tool_configs_dir is `.../tools/<tool>/configs`.
        paths.append(pdk.root / PDK_ROOT_CONFIG_DIR / tool_configs_dir.parent.name / name)
    return paths


def tool_config(tool_configs_dir: Path, name: str, pdk: "PDK") -> dict:
    """Return `defaults/<name>` deep-merged with every override that exists."""
    config = _object_from(tool_configs_dir / "defaults" / name, "default config")
    for override_path in _override_paths(tool_configs_dir, name, pdk):
        if override_path.is_file():
            config = update_parameters(_object_from(override_path, "PDK override config"), config)
    return config


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
