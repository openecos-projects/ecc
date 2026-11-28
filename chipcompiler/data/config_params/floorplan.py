from pathlib import Path

from chipcompiler.data.pdk import PDK, get_pdk

from .common import config_param


def pdn_defaults(pdk: PDK | str | None, io_mode: object) -> dict[str, list[dict[str, object]]]:
    """Read the versioned core/chip mesh, preserving PDK-carried overrides."""
    from chipcompiler.data.workspace.tool_configs import tool_config

    profile = pdk if isinstance(pdk, PDK) else get_pdk(pdk or "", validate=False)
    configs = Path(__file__).resolve().parents[2] / "tools" / "ecc" / "configs"
    config = tool_config(
        configs, "floorplan_ecc.json", profile, mode="io_cell" if io_mode == "io_cell" else ""
    )
    return {name: config["pdn_generator"][name] for name in ("stripe", "connect_layers")}


SCHEMAS = (
    config_param(
        "floorplan.die_builder.die_size.width_micron",
        "floorplan",
        ("die_builder", "die_size", "width_micron"),
        100.1,
        applies="pre_floorplan",
        description="Die width in micrometers when die_builder.mode is die_size.",
    ),
    config_param(
        "floorplan.die_builder.die_size.height_micron",
        "floorplan",
        ("die_builder", "die_size", "height_micron"),
        246.6,
        applies="pre_floorplan",
        description="Die height in micrometers when die_builder.mode is die_size.",
    ),
    config_param(
        "floorplan.die_builder.mode",
        "floorplan",
        ("die_builder", "mode"),
        "die_util",
        applies="pre_floorplan",
        description=(
            "Floorplan sizing mode: derive area from utilization or use explicit die dimensions."
        ),
        choices=("die_util", "die_size"),
    ),
    config_param(
        "floorplan.die_builder.site_name",
        "floorplan",
        ("die_builder", "site_name"),
        "",
        applies="pre_floorplan",
        description="PDK site name for standard-cell placement rows.",
    ),
    config_param(
        "floorplan.ifp.thread_number",
        "floorplan",
        ("ifp", "thread_number"),
        16,
        applies="pre_floorplan",
        description="Number of parallel threads used by the iFP floorplan engine.",
        range=(1, 256),
    ),
    config_param(
        "floorplan.io_placer.mode",
        "floorplan",
        ("io_placer", "mode"),
        "auto",
        applies="pre_floorplan",
        description=(
            "IO placement mode: auto/file places IO pins; io_cell automatically places pad cells."
        ),
        choices=("auto", "file", "io_cell"),
    ),
    config_param(
        "floorplan.io_placer.io_cell.definition_file_path",
        "floorplan",
        ("io_placer", "io_cell", "definition_file_path"),
        "",
        applies="pre_floorplan",
        description=(
            "IO cell definition JSON required in io_cell mode. Use an absolute path; "
            "native iFP resolves relative paths against the generated floorplan config directory."
        ),
    ),
    config_param(
        "floorplan.io_placer.io_cell.power.target_group_spacing",
        "floorplan",
        ("io_placer", "io_cell", "power", "target_group_spacing"),
        1000.0,
        applies="pre_floorplan",
        description="Target spacing between IO power groups in micrometers; must be positive.",
    ),
    config_param(
        "floorplan.io_placer.io_cell.auto_resize.enable",
        "floorplan",
        ("io_placer", "io_cell", "auto_resize", "enable"),
        default=True,
        applies="pre_floorplan",
        description="Allow iFP to enlarge the die when the IO cell ring does not fit.",
    ),
    config_param(
        "floorplan.io_placer.io_layer_list",
        "floorplan",
        ("io_placer", "io_layer_list"),
        [],
        applies="pre_floorplan",
        description="Metal layers allowed for IO pin placement.",
    ),
    config_param(
        "floorplan.macro_placer.macro_placement_halo",
        "floorplan",
        ("macro_placer", "macro_placement_halo"),
        3.0,
        applies="pre_floorplan",
        description=(
            "Placement halo around macros in micrometers where standard cells cannot be placed."
        ),
    ),
    config_param(
        "floorplan.macro_placer.macro_routing_halo",
        "floorplan",
        ("macro_placer", "macro_routing_halo"),
        3.0,
        applies="pre_floorplan",
        description="Routing halo around macros in micrometers where routing is prohibited.",
    ),
    config_param(
        "floorplan.pdn_generator.core_power_net",
        "floorplan",
        ("pdn_generator", "core_power_net"),
        "",
        applies="pre_floorplan",
        description=(
            "Core POWER net for rails and stripes; required when multiple power domains exist."
        ),
    ),
    config_param(
        "floorplan.pdn_generator.core_ground_net",
        "floorplan",
        ("pdn_generator", "core_ground_net"),
        "",
        applies="pre_floorplan",
        description=(
            "Core GROUND net for rails and stripes; required when multiple ground domains exist."
        ),
    ),
    config_param(
        "floorplan.pdn_generator.io_core_connect",
        "floorplan",
        ("pdn_generator", "io_core_connect"),
        {"enable": False},
        applies="pre_floorplan",
        description=(
            "IO-to-core power connection options. Set enable and fail_on_unresolved to true "
            "for pad-based designs; omitted nets/layers follow the core supplies and stripes."
        ),
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.global_connect",
        "floorplan",
        ("pdn_generator", "global_connect"),
        [
            {"net_name": "VDD", "instance_pin_name": "VDD", "is_power": True},
            {"net_name": "VSS", "instance_pin_name": "VSS", "is_power": False},
        ],
        applies="pre_floorplan",
        description=(
            "Global power and ground net-to-instance-pin connection declarations. "
            "ICS55 v2 adds VNW/VPW well-tie connections via its PDK override."
        ),
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.rail",
        "floorplan",
        ("pdn_generator", "rail"),
        [],
        applies="pre_floorplan",
        description="Standard-cell row power-rail layers and widths in micrometers.",
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.stripe",
        "floorplan",
        ("pdn_generator", "stripe"),
        [],
        applies="pre_floorplan",
        description=(
            "Power-stripe layers, widths, pitches, and offsets in micrometers. "
            "ICS55 io_cell mode adds T4M2/RDL by default; an explicit list replaces the default."
        ),
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.connect_layers",
        "floorplan",
        ("pdn_generator", "connect_layers"),
        [],
        applies="pre_floorplan",
        description=(
            "Routing-layer pairs connected by power-distribution vias. "
            "ICS55 io_cell mode extends MET5 through T4M2 to RDL by default."
        ),
        type="json",
    ),
    config_param(
        "floorplan.phy_placer.well_tap.cell_name",
        "floorplan",
        ("phy_placer", "well_tap", "cell_name"),
        "",
        applies="pre_floorplan",
        description="PDK well-tap cell inserted into standard-cell rows.",
    ),
    config_param(
        "floorplan.phy_placer.well_tap.distance_micron",
        "floorplan",
        ("phy_placer", "well_tap", "distance_micron"),
        58.0,
        applies="pre_floorplan",
        description="Well-tap insertion pitch in micrometers.",
    ),
    config_param(
        "floorplan.phy_placer.side_endcap.left_cell_name",
        "floorplan",
        ("phy_placer", "side_endcap", "left_cell_name"),
        "",
        applies="pre_floorplan",
        description="Endcap cell placed at the left edge of each standard-cell row.",
    ),
    config_param(
        "floorplan.phy_placer.side_endcap.right_cell_name",
        "floorplan",
        ("phy_placer", "side_endcap", "right_cell_name"),
        "",
        applies="pre_floorplan",
        description="Endcap cell placed at the right edge of each standard-cell row.",
    ),
    config_param(
        "floorplan.phy_placer.edge_endcap.top_cell_name_list",
        "floorplan",
        ("phy_placer", "edge_endcap", "top_cell_name_list"),
        [],
        applies="pre_floorplan",
        description="Candidate endcap cells for the die top edge, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.edge_endcap.bottom_cell_name_list",
        "floorplan",
        ("phy_placer", "edge_endcap", "bottom_cell_name_list"),
        [],
        applies="pre_floorplan",
        description="Candidate endcap cells for the die bottom edge, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.boundary_tap.top_cell_name_list",
        "floorplan",
        ("phy_placer", "boundary_tap", "top_cell_name_list"),
        [],
        applies="pre_floorplan",
        description="Candidate tap cells for the die top boundary, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.boundary_tap.bottom_cell_name_list",
        "floorplan",
        ("phy_placer", "boundary_tap", "bottom_cell_name_list"),
        [],
        applies="pre_floorplan",
        description="Candidate tap cells for the die bottom boundary, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.boundary_tap.rule_micron",
        "floorplan",
        ("phy_placer", "boundary_tap", "rule_micron"),
        30.0,
        applies="pre_floorplan",
        description="Rule distance for boundary-tap insertion in micrometers.",
    ),
)
