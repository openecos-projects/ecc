"""Stage guards for description-backed inputs, before tool output is created."""

from pathlib import Path

from .manifest import Descriptor
from .validation import validate_resources

_STEP_STAGE = {
    "Synthesis": "synthesis",
    "lec": "synthesis",
    "preFloorplan": "floorplan",
    "postFloorplan": "floorplan",
    "macroPlacement": "floorplan",
    "preplace": "sizing",
    "Timing optimization": "sizing",
    "diff_sizing": "sizing",
    "diff_opt": "placement",
    "place": "placement",
    "legalization": "placement",
    "CTS": "cts",
    "route": "routing",
    "sta": "sta",
    "RCX": "extraction",
    "emir": "emir",
    "GDS": "gds",
}


def stage_diagnostics(pdk, steps, *, emir_config: dict | None = None) -> list[dict[str, str]]:
    if not pdk.description:
        return []
    descriptor = Descriptor.model_validate(pdk.description)
    validation = validate_resources(pdk.root, descriptor)
    readiness = validation["stages"]
    diagnostics = []
    stages = {_STEP_STAGE[step] for step in steps if step in _STEP_STAGE}
    for stage in sorted(stages):
        missing = readiness[stage]["missing_roles"]
        ready = readiness[stage]["resources_ready"]
        if stage == "emir" and missing == ["em"]:
            from chipcompiler.tools.ecc.emir_model import model_config, resolve_model

            from .manifest import DescriptorError

            try:
                model = resolve_model(
                    pdk, model_config(pdk) if emir_config is None else emir_config
                )
                # Resource validation still reports missing foundry EM data. An
                # explicit ECC test model can satisfy execution preflight only.
                ready = (
                    bool(model.path and Path(model.path).is_file())
                    and not validation["diagnostics"]
                )
            except DescriptorError as exc:
                diagnostics.append({"stage": stage, "message": str(exc)})
        if not ready:
            diagnostics.append(
                {"stage": stage, "message": f"missing or invalid resources: {missing}"}
            )
        if stage == "synthesis" and not descriptor.synthesis_libraries:
            diagnostics.append({"stage": stage, "message": "select synthesis_libraries"})
        if stage == "sizing":
            from chipcompiler.tools.ecc_sizer.pdk_config import vt_environment

            from .manifest import DescriptorError
            from .tool_settings import SizerSettings

            try:
                SizerSettings.model_validate(descriptor.tools.get("sizer", {}))
                vt_environment(pdk)
            except (ValueError, DescriptorError) as exc:
                diagnostics.append({"stage": stage, "message": str(exc)})
        if stage == "floorplan" and not descriptor.cells.site_core:
            diagnostics.append({"stage": stage, "message": "select cells.site_core"})
        if stage in {"cts", "extraction"}:
            backend = descriptor.tools.get("extraction", {}).get("backend_id")
            if backend not in {"ics55", "native"}:
                diagnostics.append(
                    {"stage": stage, "message": "no supported extraction backend selected"}
                )
    return diagnostics
