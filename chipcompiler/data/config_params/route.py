from .common import config_param

SCHEMAS = (
    config_param(
        "route.RT.-thread_number",
        "routing",
        ("RT", "-thread_number"),
        "50",
        applies="routing",
        description="Router parallel thread count.",
    ),
    config_param(
        "route.RT.-enable_timing",
        "routing",
        ("RT", "-enable_timing"),
        "0",
        applies="routing",
        description="Enable timing-driven routing.",
        choices=("0", "1"),
    ),
    config_param(
        "route.RT.-output_csv",
        "routing",
        ("RT", "-output_csv"),
        "0",
        applies="routing",
        description="Export routing metrics as CSV.",
        choices=("0", "1"),
    ),
    config_param(
        "route.RT.-output_inter_result",
        "routing",
        ("RT", "-output_inter_result"),
        "0",
        applies="routing",
        description="Export routing intermediate results.",
        choices=("0", "1"),
    ),
)
