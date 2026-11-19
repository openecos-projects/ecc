"""Parameters of the legalization step's DreamPlace config.

Legalization runs DreamPlace geometry-only (``run_modes.MODE_FLAGS``) and
resolves its own ``<step dir>/config/dreamplace_ecc.json``. These parameters
set fields that the placement parameters (``place.*``) also set, but only in
the legalization step's config, so placement keeps its own values. Unset,
legalization reads the workspace baseline value.

``detailed_place_flag`` is not settable: legalization forces it off so
detailed placement does not undo the repaired hold timing.
"""

from .common import ConfigTarget, ParamSchema, PdkVariant
from .dreamplace import DREAMPLACE_PARAMETER_DESCRIPTIONS


def _legalization(param: str, default: object, type: str, **kwargs) -> ParamSchema:
    return ParamSchema(
        param=f"legalization.{param}",
        group="legalization",
        name=param,
        type=type,
        default=default,
        applies="legalization",
        description=DREAMPLACE_PARAMETER_DESCRIPTIONS[param],
        config_target=ConfigTarget("dreamplace", (param,)),
        **kwargs,
    )


SCHEMAS = (
    _legalization(
        "cell_padding_x",
        200,
        "int",
        range=(0, 10000),
        unit="dbu",
        example="0",
        pdk_variants={"sg13g2": PdkVariant(0)},
    ),
    _legalization("bndry_padding_x", 0, "int", range=(0, None), unit="dbu"),
    _legalization("bndry_padding_y", 0, "int", range=(0, None), unit="dbu"),
    _legalization("num_threads", 8, "int", range=(1, None)),
    _legalization("deterministic_flag", 1, "int", range=(0, 1)),
)
