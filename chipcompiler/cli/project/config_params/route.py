from .common import config_param

SCHEMAS = (
    config_param(
        "route.RT.-thread_number",
        "routing",
        ("RT", "-thread_number"),
        "50",
        applies="routing",
    ),
    config_param(
        "route.RT.-enable_timing",
        "routing",
        ("RT", "-enable_timing"),
        "0",
        applies="routing",
        choices=("0", "1"),
    ),
    config_param(
        "route.RT.-output_csv",
        "routing",
        ("RT", "-output_csv"),
        "0",
        applies="routing",
        choices=("0", "1"),
    ),
    config_param(
        "route.RT.-output_inter_result",
        "routing",
        ("RT", "-output_inter_result"),
        "0",
        applies="routing",
        choices=("0", "1"),
    ),
)
