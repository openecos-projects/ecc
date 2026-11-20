from .common import config_param

SCHEMAS = (
    config_param(
        "emir.synthetic_model",
        "emir",
        ("synthetic_model",),
        "",
        applies="emir",
        description="Explicit test fixture selection; ics55 is synthetic and NOT FOR SIGNOFF.",
        choices=("", "ics55"),
    ),
    config_param(
        "emir.technology_file_path",
        "emir",
        ("technology_file_path",),
        "",
        applies="emir",
        description="Absolute path to the EMIR process technology file; required for analysis.",
    ),
)
