from .common import config_param

SCHEMAS = (
    config_param(
        "emir.technology_file_path",
        "emir",
        ("technology_file_path",),
        "",
        applies="emir",
        description="Absolute path to the EMIR process technology file; required for analysis.",
    ),
    config_param(
        "emir.ploc_file_path",
        "emir",
        ("ploc_file_path",),
        "",
        applies="emir",
        description=(
            "Absolute path to an external PLOC supply-location file; "
            "empty uses the upstream post-floorplan output."
        ),
    ),
    config_param(
        "emir.supply_ground_pins",
        "emir",
        ("supply_ground_pins",),
        {},
        applies="emir",
        description=(
            "Power-pin to return-ground-pin mapping, used only when Liberty omits the return. "
            "Confirm these connections against the chip power plan."
        ),
    ),
)
