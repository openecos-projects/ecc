"""CLI-managed PDK content paths stored in ``[pdk.overrides]``."""

from .common import ParamSchema


def _pdk_path(param: str, default: object, type: str) -> ParamSchema:
    return ParamSchema(
        param=f"pdk.{param}",
        group="pdk",
        name=param,
        type=type,
        default=default,
        applies="pdk",
        description=f"PDK {param.replace('_', ' ')} override",
        pdk_target=param,
    )


SCHEMAS = (
    _pdk_path("tech", "", "str"),
    _pdk_path("lefs", [], "list[str]"),
    _pdk_path("libs", [], "list[str]"),
    _pdk_path("mapping_file", "", "str"),
    _pdk_path("sdc", "", "str"),
    _pdk_path("spef", "", "str"),
)
