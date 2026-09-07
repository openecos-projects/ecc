"""Persist external design inputs into a new workspace.

Copies the declared origin inputs (DEF, RTL or netlist, optional golden
netlist, filelist with referenced sources, SDC, and SPEF) into
``origin/`` and rebases the workspace's design fields onto the copied
files. Extracted from create_workspace so the workspace package root
stays focused on the workspace model.
"""

import shutil
from pathlib import Path

from .filelist_copy import copy_filelist_with_sources
from .sdc import create_default_sdc


def persist_origin_inputs(
    workspace,
    origin_dir: Path,
    workspace_dir: Path,
    *,
    origin_def,
    origin_verilog,
    input_filelist,
    golden_verilog,
) -> None:
    """Copy every declared input into origin/ and rebind design paths."""
    origin_def_path = Path(origin_def) if origin_def else None
    if origin_def_path and origin_def_path.exists():
        target = origin_dir / origin_def_path.name
        shutil.copy(origin_def_path, target)
        workspace.design.origin_def = target
    else:
        workspace.design.origin_def = origin_dir / f"{workspace.design.name}.def"

    origin_verilog_path = Path(origin_verilog) if origin_verilog else None
    if origin_verilog_path and origin_verilog_path.exists():
        target = origin_dir / origin_verilog_path.name
        shutil.copy(origin_verilog_path, target)
        workspace.design.origin_verilog = target
    else:
        workspace.design.origin_verilog = origin_dir / f"{workspace.design.name}.v"

    golden_verilog_path = Path(golden_verilog) if golden_verilog else None
    if golden_verilog_path and golden_verilog_path.exists():
        target = origin_dir / f"golden_{golden_verilog_path.name}"
        if target == workspace.design.origin_verilog or target.exists():
            # The generated golden name collides with the primary netlist
            # (or another input): copying would silently overwrite a real
            # input and could make LEC compare a file with itself.
            raise ValueError(f"golden netlist name collides with an existing input: {target}")
        shutil.copy(golden_verilog_path, target)
        workspace.design.golden_verilog = target

    # Copy filelist and all referenced source files
    input_filelist_path = Path(input_filelist) if input_filelist else None
    if input_filelist_path and input_filelist_path.exists():
        try:
            # Use new copy_filelist_with_sources to copy filelist + all RTL files
            workspace.design.input_filelist = Path(
                copy_filelist_with_sources(
                    input_filelist=str(input_filelist_path),
                    workspace_dir=str(workspace_dir),
                    logger=workspace.logger,
                )
            )
        except Exception as e:
            workspace.logger.error(f"Failed to copy filelist sources: {e}")
            workspace.logger.warning("Falling back to copying only filelist file")
            # Fallback: copy only filelist file (backward compatibility)
            target = origin_dir / input_filelist_path.name
            shutil.copy(input_filelist_path, target)
            workspace.design.input_filelist = target

    if workspace.pdk.sdc and workspace.pdk.sdc.exists():
        sdc_target = origin_dir / workspace.pdk.sdc.name
        shutil.copy(workspace.pdk.sdc, sdc_target)
        workspace.pdk.sdc = sdc_target
    else:
        # create default sdc file
        workspace.pdk.sdc = origin_dir / f"{workspace.design.name}.sdc"
        create_default_sdc(workspace)

    if workspace.pdk.spef and workspace.pdk.spef.exists():
        spef_target = origin_dir / workspace.pdk.spef.name
        shutil.copy(workspace.pdk.spef, spef_target)
        workspace.pdk.spef = spef_target
