from .common import config_param

SCHEMAS = (
    config_param(
        "rcx.thread_num",
        "rcx",
        ("thread_num",),
        64,
        applies="rcx",
        description="Parasitic-extraction parallel thread count.",
        range=(1, 256),
    ),
)
