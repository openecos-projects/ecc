from .common import config_param

SCHEMAS = (
    config_param(
        "filler.-min_filler_width",
        "filler",
        ("-min_filler_width",),
        1,
        applies="filler",
        description="Minimum filler-cell width used during filler insertion.",
        range=(1, 1000),
    ),
)
