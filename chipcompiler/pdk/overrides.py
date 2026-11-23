"""Protect technology inputs while retaining workspace optimization knobs."""

from .manifest import DescriptorError

_PROTECTED = {
    "db": ("INPUT.tech_lef_path", "INPUT.lef_paths", "INPUT.lib_path"),
    "cts": ("buffer_type",),
    "sta": ("STA.-cell_catalog",),
    "rcx": ("mapping_file", "pdk", "corners"),
    "emir": ("technology_file_path",),
    "floorplan": ("die_builder.site_name", "phy_placer", "pdn"),
    "dreamplace": (
        "lef_input",
        "lib_input",
        "openroad_vt_config",
        "buffering_fixed_buffer_master",
        "buffering_candidate_drive_strength_table",
    ),
    "sizer": ("hold_stage.global_routing_rc", "hold_stage.placement_wire_rc"),
}


def check_config_overrides(workspace) -> None:
    if not workspace.pdk.description:
        return
    nested = workspace.parameters.data.get("dreamplace", {})
    defaults = workspace.pdk.description.get("tools", {}).get("configs", {}).get("dreamplace", {})
    for key in _PROTECTED["dreamplace"]:
        if key in nested and nested[key] != defaults.get(key):
            raise DescriptorError(
                "project_pdk_immutable", f"dreamplace.{key} belongs to the PDK profile"
            )
    overrides = workspace.parameters.data.get("config_overrides", {})
    for target, patch in overrides.items():
        for protected in _PROTECTED.get(target.casefold(), ()):
            value = patch
            for part in protected.split("."):
                if not isinstance(value, dict) or part not in value:
                    break
                value = value[part]
            else:
                raise DescriptorError(
                    "project_pdk_immutable",
                    f"{target}.{protected} belongs to the PDK profile; "
                    "copy the project to change it",
                )
