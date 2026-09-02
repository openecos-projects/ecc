"""CLI-managed PDK content paths stored in ``[pdk.overrides]``."""

from .common import ParamSchema


def _pdk_path(param: str, default: object, type: str, description: str) -> ParamSchema:
    return ParamSchema(
        param=f"pdk.{param}",
        group="pdk",
        name=param,
        type=type,
        default=default,
        applies="pdk",
        description=description,
        pdk_target=param,
    )


SCHEMAS = (
    _pdk_path(
        "tech",
        "",
        "str",
        "Technology LEF path, resolved relative to pdk.root when relative.",
    ),
    _pdk_path(
        "lefs",
        [],
        "list[str]",
        "Standard-cell LEF paths, resolved relative to pdk.root when relative.",
    ),
    _pdk_path(
        "libs",
        [],
        "list[str]",
        "Standard-cell Liberty timing-library paths, resolved relative to pdk.root when relative.",
    ),
    _pdk_path(
        "mapping_file",
        "",
        "str",
        "PDK layer-mapping file path, resolved relative to pdk.root when relative.",
    ),
    _pdk_path(
        "sdc",
        "",
        "str",
        "PDK SDC constraints path, resolved relative to pdk.root when relative.",
    ),
    _pdk_path(
        "spef",
        "",
        "str",
        "PDK SPEF path, resolved relative to pdk.root when relative.",
    ),
)
