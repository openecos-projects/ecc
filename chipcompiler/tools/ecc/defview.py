"""Defview step: read the PDK LEFs plus the design DEF and export geometry.

The step performs no physical-design operation; it exists so a DEF-only
workspace can be opened in Chip Viewer through the regular flow machinery
(the engine resolves the first step's DEF input from the workspace origin).
"""

from chipcompiler.data import EccStep, StepEnum, Workspace
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.runner import get_eda_instance


def run_defview(
    workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule | None = None
) -> bool:
    """Load LEF+DEF inputs and write the step's geometry snapshot."""
    ecc_module = get_eda_instance(workspace=workspace, step=step, ecc_module=ecc_module)

    if ecc_module is None:
        workspace.logger.error(
            "defview failed to load design inputs; a readable DEF input is required"
        )
        return False

    ecc_module.def_save(def_path=step.output.def_ or "")

    if not ecc_module.geometry_snapshot_save(
        output_dir=step.output.geometry or "", thumbnail_path=step.output.image
    ):
        workspace.logger.error("defview failed to write geometry snapshot")
        return False

    geometry_manifest = step.output.geometry_manifest
    if geometry_manifest is None or not geometry_manifest.is_file():
        workspace.logger.error(
            "defview geometry snapshot manifest is missing: %s", geometry_manifest
        )
        return False

    workspace.logger.info("defview geometry snapshot saved to %s", step.output.geometry)
    return True
