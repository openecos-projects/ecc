from .common import ParamSchema

SCHEMAS = (
    ParamSchema(
        param="macro.manual_placement",
        group="macro",
        name="manual_placement",
        type="bool",
        default=False,
        applies="floorplan",
        maps_to={"macro": "manual_placement"},
        description=(
            "Require manual hard-macro placement. When true, macroPlacement stops "
            "unless macro.placements and config/macro_location.tcl contain placements; "
            "when false, an empty placement set uses DreamPlace."
        ),
        example="true",
    ),
    ParamSchema(
        param="macro.placements",
        group="macro",
        name="placements",
        type="json",
        default=[],
        applies="macro",
        maps_to={"macro": "placements"},
        description=(
            "Manual hard-macro placements rendered into config/macro_location.tcl. "
            "Each entry is {instance, x, y, orientation} with micron coordinates; "
            "instances are committed fixed. When set, macroPlacement skips DreamPlace."
        ),
        example='[{"instance": "u0", "x": 10.0, "y": 20.0, "orientation": "R0"}]',
    ),
)
