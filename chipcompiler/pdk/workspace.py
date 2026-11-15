"""Project-independent rendering helpers for description-backed workspaces."""

from copy import deepcopy
from pathlib import Path

from chipcompiler.utility import json_write

from .manifest import DescriptorError
from .resolver import descriptor_for


def initialize_tool_configs(workspace) -> bool:
    descriptor = descriptor_for(workspace.pdk)
    if descriptor is None:
        return False
    configs = descriptor.tools.get("configs", {})
    unknown = set(configs) - set(workspace.config)
    if unknown:
        raise DescriptorError(
            "unknown_tool_config", f"unknown tool config targets: {sorted(unknown)}"
        )
    for key, path in workspace.config.items():
        if key == "dir" or path.suffix != ".json" or path.exists():
            continue
        structural = {
            "db": {"INPUT": {}, "LayerSettings": {}},
            "CTS": {"max_fanout": 32},
            "route": {"RT": {}},
            "dreamplace": {"num_threads": 1},
        }
        config = deepcopy(configs.get(key, structural.get(key, {})))
        if not isinstance(config, dict):
            raise DescriptorError("invalid_tool_config", f"tool config must be an object: {key}")
        if not json_write(path, config):
            raise OSError(f"cannot write tool config: {path}")
    macro = workspace.config.get("macro_location")
    if macro is not None and not macro.exists():
        macro.write_text("# Macro placement commands are generated from design inputs.\n")
    return True


def default_floorplan(pdk) -> dict | None:
    descriptor = descriptor_for(pdk)
    if descriptor is None:
        return None
    return deepcopy(descriptor.tools.get("configs", {}).get("Floorplan", {"macro_placer": {}}))


def persist_description(workspace, home: Path) -> None:
    if not workspace.pdk.description:
        return
    path = home / "ecc-pdk.json"
    if not json_write(path, workspace.pdk.description):
        raise OSError(f"cannot persist PDK description: {path}")
    workspace.parameters.data["pdk_config"] = str(path)
    from .context import write_context
    from .manifest import Descriptor

    write_context(
        workspace.pdk.root,
        Descriptor.model_validate(workspace.pdk.description),
        home / "ecc-pdk-context.json",
    )
