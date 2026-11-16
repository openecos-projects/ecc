"""Publish the physical input of post-route LEC as an independent view artifact.

LEC remains a netlist proof. This export neither changes its verdict nor becomes
a physical flow input; it provides a saved view of the design that was checked.
"""

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc.builder import build_step
from chipcompiler.tools.ecc.module import ECCToolsModule
from chipcompiler.tools.ecc.runner import create_db_engine
from chipcompiler.utility.path import require_path


def save_checked_layout(
    workspace: Workspace, step: WorkspaceStep, module: ECCToolsModule | None = None
) -> bool:
    if not step.input.def_:
        return False
    view = build_step(
        workspace,
        step.name,
        input_def=step.input.def_,
        input_verilog=None,
        tool=step.tool,
        step_directory=step.directory,
    )
    owned = module is None
    try:
        if module is None:
            module = create_db_engine(workspace, view)
        if module is None:
            raise ValueError("Cannot load the checked physical input")
        module.def_save(def_path=require_path(view.output.def_, "checked DEF"))
        if not module.geometry_snapshot_save(
            output_dir=require_path(view.output.geometry, "checked geometry"),
            thumbnail_path=view.output.image,
        ):
            raise ValueError("Geometry export failed")
        if not require_path(view.output.geometry_manifest, "checked geometry manifest").is_file():
            raise ValueError("Geometry manifest is missing")
        return True
    except Exception as error:
        workspace.logger.warning("Post-route LEC layout unavailable: %s", error)
        return False
    finally:
        if owned and module is not None:
            module.close()
