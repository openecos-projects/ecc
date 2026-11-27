"""Publish the optional final layout view independently of Harden deliverables."""

from chipcompiler.data import EccStep, Workspace
from chipcompiler.tools.ecc.module import ECCToolsModule


def save_harden_layout(workspace: Workspace, step: EccStep, ecc_module: ECCToolsModule) -> None:
    manifest = step.output.geometry_manifest
    if manifest is None or step.output.geometry is None:
        return
    try:
        # Do not present an earlier run's view if this export fails.
        manifest.unlink(missing_ok=True)
        if step.output.image is not None:
            step.output.image.unlink(missing_ok=True)
        saved = ecc_module.geometry_snapshot_save(
            output_dir=step.output.geometry, thumbnail_path=step.output.image
        )
        if not saved or not manifest.is_file():
            raise RuntimeError("geometry snapshot was not published")
    except Exception as error:
        workspace.logger.warning("Harden layout view unavailable: %s", error)
