from copy import deepcopy

from .common import config_param

_CORE_PDN: dict[str, list[dict[str, object]]] = {
    "stripe": [
        {
            "routing_layer_name": "MET4",
            "width_micron": 1.0,
            "pitch_micron": 16.0,
            "offset_micron": 0.5,
        },
        {
            "routing_layer_name": "MET5",
            "width_micron": 1.0,
            "pitch_micron": 16.0,
            "offset_micron": 0.5,
        },
    ],
    "connect_layers": [
        {"bottom_routing_layer_name": "MET1", "top_routing_layer_name": "MET4"},
        {"bottom_routing_layer_name": "MET4", "top_routing_layer_name": "MET5"},
    ],
}

_CX55_CHIP_PDN: dict[str, list[dict[str, object]]] = {
    "stripe": [
        {
            "routing_layer_name": "T4M2",
            "width_micron": 6.0,
            "pitch_micron": 16.0,
            "offset_micron": 0.5,
        },
        {
            "routing_layer_name": "RDL",
            "width_micron": 35.0,
            "pitch_micron": 90.0,
            "offset_micron": 50.0,
        },
    ],
    "connect_layers": [
        {"bottom_routing_layer_name": "MET5", "top_routing_layer_name": "T4M2"},
        {"bottom_routing_layer_name": "T4M2", "top_routing_layer_name": "RDL"},
    ],
}


def pdn_defaults(pdk: str | None, io_mode: object) -> dict[str, list[dict[str, object]]]:
    """Core mesh defaults, extended for CX55 pad-based chips (MPW or assembled MPC)."""
    defaults = deepcopy(_CORE_PDN)
    if pdk and pdk.casefold() == "ics55" and io_mode == "io_cell":
        for name, extension in _CX55_CHIP_PDN.items():
            defaults[name].extend(deepcopy(extension))
    return defaults


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
        "core7",
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
        ["MET3", "MET4"],
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
        "floorplan.pdn_generator.global_connect",
        "floorplan",
        ("pdn_generator", "global_connect"),
        [
            {"net_name": "VDD", "instance_pin_name": "VDD", "is_power": True},
            {"net_name": "VSS", "instance_pin_name": "VSS", "is_power": False},
        ],
        applies="pre_floorplan",
        description="Global power and ground net-to-instance-pin connection declarations.",
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.rail",
        "floorplan",
        ("pdn_generator", "rail"),
        [{"routing_layer_name": "MET1", "width_micron": 0.16}],
        applies="pre_floorplan",
        description="Standard-cell row power-rail layers and widths in micrometers.",
        type="json",
    ),
    config_param(
        "floorplan.pdn_generator.stripe",
        "floorplan",
        ("pdn_generator", "stripe"),
        _CORE_PDN["stripe"],
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
        _CORE_PDN["connect_layers"],
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
        "FILLTAPH7R",
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
        "FILLTAPH7R",
        applies="pre_floorplan",
        description="Endcap cell placed at the left edge of each standard-cell row.",
    ),
    config_param(
        "floorplan.phy_placer.side_endcap.right_cell_name",
        "floorplan",
        ("phy_placer", "side_endcap", "right_cell_name"),
        "FILLTAPH7R",
        applies="pre_floorplan",
        description="Endcap cell placed at the right edge of each standard-cell row.",
    ),
    config_param(
        "floorplan.phy_placer.edge_endcap.top_cell_name_list",
        "floorplan",
        ("phy_placer", "edge_endcap", "top_cell_name_list"),
        ["FILLCAP4H7R", "FILLCAP8H7R", "FILLCAP16H7R", "FILLCAP32H7R", "FILLER2H7R", "FILLER1H7R"],
        applies="pre_floorplan",
        description="Candidate endcap cells for the die top edge, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.edge_endcap.bottom_cell_name_list",
        "floorplan",
        ("phy_placer", "edge_endcap", "bottom_cell_name_list"),
        ["FILLCAP4H7R", "FILLCAP8H7R", "FILLCAP16H7R", "FILLCAP32H7R", "FILLER2H7R", "FILLER1H7R"],
        applies="pre_floorplan",
        description="Candidate endcap cells for the die bottom edge, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.boundary_tap.top_cell_name_list",
        "floorplan",
        ("phy_placer", "boundary_tap", "top_cell_name_list"),
        ["FILLCAP4H7R", "FILLCAP8H7R", "FILLCAP16H7R", "FILLCAP32H7R", "FILLER2H7R", "FILLER1H7R"],
        applies="pre_floorplan",
        description="Candidate tap cells for the die top boundary, selected by width.",
    ),
    config_param(
        "floorplan.phy_placer.boundary_tap.bottom_cell_name_list",
        "floorplan",
        ("phy_placer", "boundary_tap", "bottom_cell_name_list"),
        ["FILLCAP4H7R", "FILLCAP8H7R", "FILLCAP16H7R", "FILLCAP32H7R", "FILLER2H7R", "FILLER1H7R"],
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
