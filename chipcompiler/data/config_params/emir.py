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
)
