#!/usr/bin/env python
import os
from pathlib import Path

from chipcompiler.data import StepMetrics, Workspace, WorkspaceStep, log_workspace_step
from chipcompiler.tools.registry import load_tool


def load_eda_module(eda_tool: str, *, check_dependency: bool = True):
    """Compatibility name for :func:`chipcompiler.tools.registry.load_tool`."""
    return load_tool(eda_tool, check_dependency=check_dependency)


def create_step(
    workspace: Workspace,
    step: str,
    eda: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None = None,
    output_def: Path | None = None,
    output_verilog: Path | None = None,
    output_gds: Path | None = None,
    *,
    initialize_config: bool = False,
    check_dependency: bool = True,
) -> WorkspaceStep | None:
    """
    Create and return an EDA tool instance based on the given step and eda tool name.
    """
    # Unselected optional tools only need a path-only step to preserve the
    # positional input chain; importing them can trigger expensive native
    # builds before the selected-step dependency check even runs.
    if not check_dependency and eda in _DEFERRED_EDA_TOOLS:
        return _build_deferred_step(
            workspace,
            step,
            eda,
            input_def,
            input_verilog,
            input_db,
            output_def,
            output_verilog,
            output_gds,
        )

    # check eda tool exist
    eda_module = load_tool(eda, check_dependency=check_dependency and eda != "sizer")
    if eda_module is None or not hasattr(eda_module, "build_step"):
        return None

    # build step
    workspace_step = eda_module.build_step(
        workspace=workspace,
        step_name=step,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
    )

    # build step sub workspace
    eda_module.build_step_space(workspace_step)

    if initialize_config:
        eda_module.build_step_config(workspace, workspace_step)

    return workspace_step


# Optional tools whose unselected steps are built deferred (no EDA package
# import). Each tool owns a dependency-free deferred builder in its builder
# module; this set only names them.
_DEFERRED_EDA_TOOLS = frozenset({"dreamplace", "sizer"})


def _build_deferred_step(
    workspace: Workspace,
    step_name: str,
    eda: str,
    input_def: Path | None,
    input_verilog: Path | None,
    input_db: Path | str | None,
    output_def: Path | None,
    output_verilog: Path | None,
    output_gds: Path | None,
) -> WorkspaceStep:
    """Build an unselected optional step without importing its EDA package.

    Existing-workspace reruns still need a complete positional chain so the
    selected step receives the persisted predecessor outputs. The core ECC
    builder supplies that path-only representation; no directories or config
    files are initialized for the deferred step.
    """
    from chipcompiler.tools.ecc import builder as ecc_builder

    if eda == "sizer":
        # The sizer builder module owns its step shape; importing it is safe
        # (rosettakit is imported lazily inside its functions).
        from chipcompiler.tools.ecc_sizer.builder import deferred_step

        return deferred_step(
            workspace,
            step_name,
            input_def,
            input_verilog,
            input_db,
            output_def,
            output_verilog,
        )

    return ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool=eda,
    )


def run_step(workspace: Workspace, step: WorkspaceStep, ecc_module=None) -> bool:
    """
    Run the given step using the provided EDA engine.
    """
    # check eda tool exist
    eda_module = load_tool(step.tool, check_dependency=step.tool != "sizer")
    if eda_module is None:
        return False

    # update config
    eda_module.build_step_config(workspace, step)

    log_workspace_step(step, workspace.logger)

    return eda_module.run_step(workspace=workspace, step=step, ecc_module=ecc_module)


def save_layout_image(workspace: Workspace, step: WorkspaceStep) -> bool:
    """
    Save the layout image for the given step.
    """
    image = step.output.image
    if image is not None and os.path.exists(image) and os.path.getsize(image) > 0:
        # Geometry snapshots already render the thumbnail; keep it.
        return True

    # check eda tool exist
    eda_module = load_tool("klayout")
    if eda_module is None:
        return False

    from chipcompiler.tools.klayout_tool.runner import save_gds_image

    return save_gds_image(workspace=workspace, step=step)


def build_step_metrics(workspace: Workspace, step: WorkspaceStep) -> StepMetrics | None:
    """
    build step metrics
    """
    eda_module = load_tool(step.tool, check_dependency=step.tool != "sizer")
    build_metrics = getattr(eda_module, "build_step_metrics", None)
    if build_metrics is None:
        return None

    metrics = build_metrics(workspace=workspace, step=step)

    return metrics
