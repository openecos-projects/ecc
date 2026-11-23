"""Project-independent rendering helpers for description-backed workspaces."""

import json
from copy import deepcopy
from pathlib import Path

from chipcompiler.utility import json_write

from .manifest import DescriptorError
from .resolver import descriptor_for


def bundled_tool_configs(profile_id, description) -> dict:
    """Expand point-tool defaults and release overrides when resolving an installation."""
    tools = Path(__file__).resolve().parents[1] / "tools"
    configs = {}
    names = {"cts": "CTS", "rcx": "RCX", "floorplan": "Floorplan", "routing": "route"}
    for owner in ("ecc", "ecc_dreamplace", "ecc_sizer"):
        directory = tools / owner / "configs"
        for default in sorted((directory / "defaults").glob("*_ecc.json")):
            key = default.stem.removesuffix("_ecc")
            override = directory / "pdk" / profile_id / default.name
            config = json.loads(default.read_bytes())
            if override.exists():
                patch = json.loads(override.read_bytes())
                if key == "sta":
                    for corner in patch.get("liberty", []):
                        corner["path"] = [
                            "/" + description.resources[resource].path
                            for resource in corner.pop("libraries")
                        ]
                config = _merge_config(config, patch)
            configs[names.get(key, key)] = config
    return configs


def initialize_tool_configs(workspace) -> bool:
    descriptor = descriptor_for(workspace.pdk)
    if descriptor is None:
        return False
    declared = descriptor.tools.get("configs", {})
    aliases = {"route": "routing"}
    configs = {
        aliases.get(str(key).casefold(), str(key).casefold()): value
        for key, value in declared.items()
    }
    unknown = set(configs) - set(workspace.config)
    if unknown:
        raise DescriptorError(
            "unknown_tool_config", f"unknown tool config targets: {sorted(unknown)}"
        )
    for key, path in workspace.config.items():
        if key == "dir" or path.suffix != ".json":
            continue
        config = deepcopy(configs.get(key, {}))
        if path.is_file() and config:
            from chipcompiler.utility import json_read

            existing = json_read(path)
            if isinstance(existing, dict):
                config = _merge_config(existing, config)
        if not isinstance(config, dict):
            raise DescriptorError("invalid_tool_config", f"tool config must be an object: {key}")
        if config and not json_write(path, config):
            raise OSError(f"cannot write tool config: {path}")
    macro = workspace.config.get("macro_location")
    if macro is not None and not macro.exists():
        macro.write_text("# Macro placement commands are generated from design inputs.\n")
    return True


def _merge_config(base: dict, overlay: dict) -> dict:
    merged = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


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
