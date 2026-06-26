#!/usr/bin/env python
# -*- encoding: utf-8 -*-

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from .parameter import (
    Parameters,
    get_parameters, 
    save_parameter, 
    load_parameter,
    update_parameters
)

from .home import HomeData

from .pdk import get_pdk, PDK
from .step import StepEnum
from chipcompiler.utility import Logger, create_logger, dict_to_str
from chipcompiler.utility.filelist import parse_filelist, resolve_path, parse_incdir_directives

@dataclass
class OriginDesign:
    """
    Dataclass for original design information
    """
    name : str = "" # design name
    top_module : str = "" # top module name
    origin_def : Path | None = None # original def file path
    origin_verilog : Path | None = None # original verilog file path
    input_filelist : Path | None = None # input filelist for synthesis
    
@dataclass
class Flow:
    """
    Dataclass for design flow
    """
    path : Path | None = None # flow file path
    data : dict = field(default_factory=dict) # flow steps
    
@dataclass
class Workspace:
    """
    Dataclass for workspace information
    """
    directory : Path | None = None # workspace directory
    design : OriginDesign = field(default_factory=OriginDesign) # original design info
    pdk : PDK = field(default_factory=PDK) # pdk information
    parameters : Parameters = field(default_factory=Parameters) # design parameters
    flow : Flow = field(default_factory=Flow) # design flow for this workspace
    home : HomeData = field(default_factory=HomeData) # home data for this workspace
    config : dict[str, Path] = field(default_factory=dict) # workspace-level config paths
    
    # logger
    logger : Logger = field(default_factory=Logger) # logger for this workspace
    
@dataclass
class WorkspaceStep:
    """
    Dataclass for workspace step path information, describe all the info for this task step.
    """
    # step basic info
    name : str = "" # step name
    directory : Path | None = None # step working directory

    # eda tool info
    tool : str = "" # eda tool name
    version : str = "" # eda tool version

    # Paths for this step
    input : dict = field(default_factory=dict) # input path about this step
    output : dict = field(default_factory=dict) # output path about this step
    data : dict = field(default_factory=dict) # data path about this step
    feature : dict = field(default_factory=dict) # features path about this step
    report : dict = field(default_factory=dict) # report path about this step
    log : dict = field(default_factory=dict) # log path about this step
    script : dict = field(default_factory=dict) # script path about this step
    analysis : dict = field(default_factory=dict) # analysis path about this step
    subflow : dict = field(default_factory=dict) # sub flow for this step
    checklist : dict = field(default_factory=dict) # checklist for this step

    # step result info
    result : dict = field(default_factory=dict) # result info about this step
    
def log_workspace_step(step : WorkspaceStep, logger : Logger):
    logger.log_section(f"step {step.name} info")
    logger.info(f"step name         : {step.name}")
    logger.info(f"step eda          : {step.tool}")
    logger.info(f"step eda version  : {step.version}")
    logger.info(f"step subworkspace : {step.directory}")
    
    logger.info("\ninput - \n%s", dict_to_str(step.input))
    logger.info("\noutput - \n%s", dict_to_str(step.output))
    logger.info("\ndata - \n%s", dict_to_str(step.data))
    logger.info("\nfeature - \n%s", dict_to_str(step.feature))
    logger.info("\nreport - \n%s", dict_to_str(step.report))
    logger.info("\nlog - \n%s", dict_to_str(step.log))
    logger.info("\nscript - \n%s", dict_to_str(step.script))
    logger.info("\nanalysis - \n%s", dict_to_str(step.analysis))
    logger.info("\nsubflow - \n%s", dict_to_str(step.subflow))
    logger.info("\nchecklist - \n%s", dict_to_str(step.checklist))
    logger.log_separator()


def build_workspace_config_paths(workspace: Workspace) -> dict[str, Path]:
    """Build workspace-level config file paths."""
    workspace_dir = Path(workspace.directory) if workspace.directory is not None else Path("")
    config_dir = workspace_dir / "config"
    return {
        "dir": config_dir,
        "flow": config_dir / "flow_config.json",
        "db": config_dir / "db_default_config.json",
        f"{StepEnum.CTS.value}": config_dir / "cts_default_config.json",
        f"{StepEnum.DRC.value}": config_dir / "drc_default_config.json",
        f"{StepEnum.FLOORPLAN.value}": config_dir / "fp_default_config.json",
        f"{StepEnum.NETLIST_OPT.value}": config_dir / "no_default_config_fixfanout.json",
        f"{StepEnum.PLACEMENT.value}": config_dir / "pl_default_config.json",
        f"{StepEnum.PNP.value}": config_dir / "pnp_default_config.json",
        f"{StepEnum.ROUTING.value}": config_dir / "rt_default_config.json",
        f"{StepEnum.TIMING_OPT_DRV.value}": config_dir / "to_default_config_drv.json",
        f"{StepEnum.TIMING_OPT_HOLD.value}": config_dir / "to_default_config_hold.json",
        f"{StepEnum.TIMING_OPT_SETUP.value}": config_dir / "to_default_config_setup.json",
        f"{StepEnum.LEGALIZATION.value}": config_dir / "pl_default_config.json",
        f"{StepEnum.FILLER.value}": config_dir / "pl_default_config.json",
        f"{StepEnum.RCX.value}": config_dir / "rcx.json",
        f"{StepEnum.STA.value}": config_dir / "sta.json",
        "dreamplace": config_dir / "dreamplace.json",
    }


@dataclass(frozen=True)
class WorkspaceConfigParameterMapping:
    parameter_key: str
    config_key: str
    json_path: tuple[str, ...]
    to_config: Callable[[Any], Any] | None = None
    to_parameter: Callable[[Any], Any] | None = None


def _flag_to_int(value: Any) -> int:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "on"}:
            return 1
        if normalized in {"false", "no", "off", ""}:
            return 0
        try:
            return int(float(normalized))
        except ValueError:
            return 1
    return int(bool(value))


PARAMETER_CONFIG_FIELD_MAPPINGS = (
    WorkspaceConfigParameterMapping(
        "Max fanout",
        StepEnum.NETLIST_OPT.value,
        ("max_fanout",),
    ),
    WorkspaceConfigParameterMapping(
        "Global right padding",
        StepEnum.PLACEMENT.value,
        ("PL", "GP", "global_right_padding"),
    ),
    WorkspaceConfigParameterMapping(
        "Bottom layer",
        "db",
        ("LayerSettings", "routing_layer_1st"),
    ),
    WorkspaceConfigParameterMapping(
        "Bottom layer",
        StepEnum.ROUTING.value,
        ("RT", "-bottom_routing_layer"),
    ),
    WorkspaceConfigParameterMapping(
        "Top layer",
        StepEnum.ROUTING.value,
        ("RT", "-top_routing_layer"),
    ),
    WorkspaceConfigParameterMapping(
        "Target density",
        "dreamplace",
        ("target_density",),
    ),
    WorkspaceConfigParameterMapping(
        "Target overflow",
        "dreamplace",
        ("stop_overflow",),
    ),
    WorkspaceConfigParameterMapping(
        "Cell padding x",
        "dreamplace",
        ("cell_padding_x",),
    ),
    WorkspaceConfigParameterMapping(
        "Routability opt flag",
        "dreamplace",
        ("routability_opt_flag",),
        to_config=_flag_to_int,
        to_parameter=_flag_to_int,
    ),
)


_MISSING = object()


def _get_nested_value(data: dict, path: tuple[str, ...]):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _set_nested_value(data: dict, path: tuple[str, ...], value) -> None:
    current = data
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def _mapping_config_path(workspace: Workspace, mapping: WorkspaceConfigParameterMapping) -> Path | str:
    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)
    return workspace.config.get(mapping.config_key, "")


def _reload_workspace_parameters(workspace: Workspace) -> None:
    if workspace.parameters.path:
        parameter_path = Path(workspace.parameters.path)
        if parameter_path.exists():
            workspace.parameters = load_parameter(parameter_path)


def _apply_parameter_mappings_to_workspace_config(workspace: Workspace) -> None:
    from chipcompiler.utility import json_read, json_write

    configs: dict[str, dict] = {}
    for mapping in PARAMETER_CONFIG_FIELD_MAPPINGS:
        if mapping.parameter_key not in workspace.parameters.data:
            continue

        path = _mapping_config_path(workspace, mapping)
        if not path:
            continue

        config = configs.setdefault(path, json_read(path))
        value = workspace.parameters.data[mapping.parameter_key]
        if mapping.to_config is not None:
            value = mapping.to_config(value)
        _set_nested_value(config, mapping.json_path, value)

    for path, config in configs.items():
        json_write(path, config)


def _ensure_writable(path: str):
    import os
    import stat

    try:
        os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR | stat.S_IXUSR)
    except OSError:
        pass

    for root, dirs, files in os.walk(path):
        for name in dirs:
            target = os.path.join(root, name)
            try:
                os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR | stat.S_IXUSR)
            except OSError:
                pass
        for name in files:
            target = os.path.join(root, name)
            try:
                os.chmod(target, os.stat(target).st_mode | stat.S_IWUSR)
            except OSError:
                pass


def _copy_missing_files(src_dir: str, dst_dir: str):
    import os
    import shutil

    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        src = os.path.join(src_dir, name)
        dst = os.path.join(dst_dir, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)


def _rcx_temperature_key(temperature) -> str:
    try:
        numeric = float(temperature)
        return str(int(numeric)) if numeric.is_integer() else f"{numeric:.12g}"
    except (TypeError, ValueError):
        return str(temperature)


def _rcx_temperature_token(temperature) -> str:
    return _rcx_temperature_key(temperature).replace(".", "p").replace("-", "m") + "C"


def init_workspace_config(workspace: Workspace) -> None:
    """Create workspace-level configs, then refresh parameter/PDK-derived fields."""
    import shutil

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    config_dir = workspace.config["dir"]
    root_dir = Path(__file__).resolve().parent.parent
    ecc_config_dir = root_dir / "tools" / "ecc" / "configs"
    dreamplace_config = root_dir / "tools" / "ecc_dreamplace" / "configs" / "dreamplace.json"

    _copy_missing_files(ecc_config_dir, config_dir)
    if not workspace.config["dreamplace"].exists():
        shutil.copy2(dreamplace_config, workspace.config["dreamplace"])
    _ensure_writable(config_dir)

    refresh_workspace_config(workspace)


def refresh_workspace_config(workspace: Workspace) -> None:
    """Reload parameters.json and refresh workspace configs derived from parameters/PDK."""
    import os

    from chipcompiler.tools.ecc_dreamplace.parameter_overrides import apply_parameter_overrides
    from chipcompiler.utility import json_read, json_write

    _reload_workspace_parameters(workspace)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    flow = json_read(workspace.config["flow"])
    flow["ConfigPath"]["idb_path"] = str(workspace.config["db"])
    flow["ConfigPath"]["ifp_path"] = str(workspace.config[f"{StepEnum.FLOORPLAN.value}"])
    flow["ConfigPath"]["ipl_path"] = str(workspace.config[f"{StepEnum.PLACEMENT.value}"])
    flow["ConfigPath"]["irt_path"] = str(workspace.config[f"{StepEnum.ROUTING.value}"])
    flow["ConfigPath"]["idrc_path"] = str(workspace.config[f"{StepEnum.DRC.value}"])
    flow["ConfigPath"]["icts_path"] = str(workspace.config[f"{StepEnum.CTS.value}"])
    flow["ConfigPath"]["ito_path"] = str(workspace.config[f"{StepEnum.TIMING_OPT_DRV.value}"])
    flow["ConfigPath"]["ipnp_path"] = str(workspace.config[f"{StepEnum.PNP.value}"])
    json_write(workspace.config["flow"], flow)

    db = json_read(workspace.config["db"])
    db["INPUT"]["tech_lef_path"] = str(workspace.pdk.tech or "")
    db["INPUT"]["lef_paths"] = [str(path) for path in workspace.pdk.lefs]
    db["INPUT"]["lib_path"] = [str(path) for path in workspace.pdk.libs]
    db["INPUT"]["sdc_path"] = str(workspace.pdk.sdc or "")
    db["INPUT"]["spef"] = str(workspace.pdk.spef or "")
    db["LayerSettings"]["routing_layer_1st"] = workspace.parameters.data.get("Bottom layer", "")
    json_write(workspace.config["db"], db)

    fixfanout = json_read(workspace.config[f"{StepEnum.NETLIST_OPT.value}"])
    fixfanout["insert_buffer"] = workspace.pdk.buffers[0] if len(workspace.pdk.buffers) > 0 else ""
    fixfanout["max_fanout"] = workspace.parameters.data.get("Max fanout", 32)
    json_write(workspace.config[f"{StepEnum.NETLIST_OPT.value}"], fixfanout)

    placement = json_read(workspace.config[f"{StepEnum.PLACEMENT.value}"])
    placement["PL"]["BUFFER"]["buffer_type"] = workspace.pdk.buffers
    placement["PL"]["Filler"]["first_iter"] = workspace.pdk.fillers
    placement["PL"]["Filler"]["second_iter"] = workspace.pdk.fillers
    placement["PL"]["GP"]["global_right_padding"] = workspace.parameters.data.get(
        "Global right padding", 0
    )
    json_write(workspace.config[f"{StepEnum.PLACEMENT.value}"], placement)

    cts = json_read(workspace.config[f"{StepEnum.CTS.value}"])
    cts["buffer_type"] = workspace.pdk.buffers
    json_write(workspace.config[f"{StepEnum.CTS.value}"], cts)

    drv = json_read(workspace.config[f"{StepEnum.TIMING_OPT_DRV.value}"])
    drv["DRV_insert_buffers"] = workspace.pdk.buffers
    json_write(workspace.config[f"{StepEnum.TIMING_OPT_DRV.value}"], drv)

    hold = json_read(workspace.config[f"{StepEnum.TIMING_OPT_HOLD.value}"])
    hold["hold_insert_buffers"] = workspace.pdk.buffers
    json_write(workspace.config[f"{StepEnum.TIMING_OPT_HOLD.value}"], hold)

    setup = json_read(workspace.config[f"{StepEnum.TIMING_OPT_SETUP.value}"])
    setup["setup_insert_buffers"] = workspace.pdk.buffers
    json_write(workspace.config[f"{StepEnum.TIMING_OPT_SETUP.value}"], setup)

    router = json_read(workspace.config[f"{StepEnum.ROUTING.value}"])
    router["RT"]["-bottom_routing_layer"] = workspace.parameters.data.get("Bottom layer", "")
    router["RT"]["-top_routing_layer"] = workspace.parameters.data.get("Top layer", "")
    json_write(workspace.config[f"{StepEnum.ROUTING.value}"], router)

    _apply_parameter_mappings_to_workspace_config(workspace)

    # rcx = json_read(workspace.config[f"{StepEnum.RCX.value}"])
    # rcx["pdk"] = "ics55" if workspace.pdk.name == "ics55" else ""
    # rcx["mapping_file"] = workspace.pdk.mapping_file
    # corners = deepcopy(workspace.pdk.corners)
    # rcx["corners"] = corners
    # json_write(workspace.config[f"{StepEnum.RCX.value}"], rcx)

    sta = json_read(workspace.config[f"{StepEnum.STA.value}"])
    pdk_root = str(workspace.pdk.root or "").rstrip(os.sep)
    for liberty in sta.get("liberty", []):
        liberty["path"] = [
            path
            if path == pdk_root or path.startswith(f"{pdk_root}{os.sep}")
            else str((workspace.pdk.root or Path("")) / path.lstrip(os.sep))
            for path in liberty.get("path", [])
        ]

    json_write(workspace.config[f"{StepEnum.STA.value}"], sta)

    dreamplace = json_read(workspace.config["dreamplace"])
    dreamplace["lef_input"] = [
        str(path) for path in [workspace.pdk.tech, *workspace.pdk.lefs] if path
    ]
    dreamplace["base_design_name"] = workspace.design.name
    dreamplace = apply_parameter_overrides(dreamplace, workspace.parameters.data)
    json_write(workspace.config["dreamplace"], dreamplace)


def sync_workspace_config_to_parameters(workspace: Workspace, config_path: str | Path) -> bool:
    """Sync managed fields from one workspace config file back into parameters.json."""
    from chipcompiler.utility import json_read

    _reload_workspace_parameters(workspace)

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    resolved_config_path = Path(config_path).expanduser().resolve()
    changed = False
    for mapping in PARAMETER_CONFIG_FIELD_MAPPINGS:
        mapped_path = _mapping_config_path(workspace, mapping)
        if not mapped_path or Path(mapped_path).expanduser().resolve() != resolved_config_path:
            continue

        config = json_read(mapped_path)
        value = _get_nested_value(config, mapping.json_path)
        if value is _MISSING:
            continue

        if mapping.to_parameter is not None:
            value = mapping.to_parameter(value)

        if workspace.parameters.data.get(mapping.parameter_key) != value:
            workspace.parameters.data[mapping.parameter_key] = value
            changed = True

    if changed:
        save_parameter(workspace.parameters)

    return changed


def _path_is_within(path: str | Path, directory: str | Path) -> bool:
    try:
        return Path(path).resolve().is_relative_to(Path(directory).resolve())
    except OSError:
        return False


def _reset_workspace_checklist(workspace: Workspace) -> None:
    from chipcompiler.utility import json_write

    checklist_path = workspace.home.data.get("checklist", "")
    if not checklist_path:
        checklist_path = Path(workspace.directory) / "home" / "checklist.json"
    json_write(
        checklist_path,
        {
            "path": str(checklist_path),
            "checklist": [],
        },
    )


def _reset_workspace_runtime_parameters(workspace: Workspace) -> None:
    from copy import deepcopy

    current_data = workspace.parameters.data or {}
    pdk_name = str(current_data.get("PDK", "")).lower()
    template_parameters = get_parameters(pdk_name)
    template_data = deepcopy(template_parameters.data)

    die_template = template_data.get("Die")
    if isinstance(die_template, dict) and isinstance(current_data.get("Die"), dict):
        current_data["Die"] = deepcopy(die_template)

    core_template = template_data.get("Core")
    if isinstance(core_template, dict) and isinstance(current_data.get("Core"), dict):
        current_core = current_data["Core"]
        current_data["Core"] = {
            **deepcopy(core_template),
            "Utilitization": current_core.get("Utilitization", core_template.get("Utilitization")),
            "Margin": deepcopy(current_core.get("Margin", core_template.get("Margin"))),
            "Aspect ratio": current_core.get("Aspect ratio", core_template.get("Aspect ratio")),
        }

    save_parameter(workspace.parameters)


def prepare_workspace_for_rerun(workspace: Workspace, engine_flow) -> None:
    """Delete old run artifacts and restore runtime files before a full-flow rerun."""
    import shutil

    workspace_root = Path(workspace.directory).resolve()
    step_directories = []
    for workspace_step in getattr(engine_flow, "workspace_steps", []):
        step_directory = getattr(workspace_step, "directory", "")
        if not step_directory:
            continue
        resolved_step_directory = Path(step_directory).resolve()
        if (
            resolved_step_directory == workspace_root
            or not _path_is_within(resolved_step_directory, workspace_root)
        ):
            raise ValueError(f"refusing to delete step directory outside workspace: {step_directory}")
        step_directories.append(resolved_step_directory)

    for step_directory in sorted(set(step_directories), key=lambda path: len(str(path)), reverse=True):
        if not step_directory.exists():
            continue
        if step_directory.is_symlink() or step_directory.is_file():
            step_directory.unlink()
        else:
            shutil.rmtree(step_directory)

    if hasattr(engine_flow, "clear_states"):
        engine_flow.clear_states()

    workspace.home.reset()
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(workspace_root / "home" / "checklist.json")
    workspace.home.set_parameters(workspace.parameters.path)
    _reset_workspace_checklist(workspace)
    _reset_workspace_runtime_parameters(workspace)

    refresh_workspace_config(workspace)

    if hasattr(engine_flow, "engine_db"):
        engine_flow.engine_db = None
    if hasattr(engine_flow, "workspace_steps"):
        engine_flow.workspace_steps.clear()
    if hasattr(engine_flow, "create_step_workspaces"):
        engine_flow.create_step_workspaces()


def update_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    """Update only step-dependent workspace config fields."""
    from chipcompiler.utility import json_read, json_write

    if not workspace.config:
        workspace.config = build_workspace_config_paths(workspace)

    def _path_value(value) -> str:
        return str(value) if value else ""

    db = json_read(workspace.config["db"])
    db["INPUT"]["def_path"] = _path_value(step.input.get("def", ""))
    db["INPUT"]["verilog_path"] = _path_value(step.input.get("verilog", ""))
    db["OUTPUT"]["output_dir_path"] = _path_value(step.output.get("dir", ""))
    json_write(workspace.config["db"], db)

    if step.name == StepEnum.ROUTING.value:
        router = json_read(workspace.config[f"{StepEnum.ROUTING.value}"])
        router["RT"]["-temp_directory_path"] = _path_value(
            step.data.get(f"{StepEnum.ROUTING.value}", "")
        )
        json_write(workspace.config[f"{StepEnum.ROUTING.value}"], router)

    if step.name == StepEnum.RCX.value:
        rcx = json_read(workspace.config[f"{StepEnum.RCX.value}"])
        rcx_output_dir = _path_value(step.output.get("dir", ""))
        rcx["output"] = rcx_output_dir
        for corner in rcx.get("corners", []):
            corner_name = corner.get("name", "")
            if corner_name:
                temperatures = corner.get("temperature", [25]) or [25]
                corner["spef_file"] = [
                    {
                        _rcx_temperature_key(temperature): (
                            f"{rcx_output_dir}/"
                            f"{workspace.design.name}_{corner_name}_"
                            f"{_rcx_temperature_token(temperature)}.spef"
                        )
                    }
                    for temperature in temperatures
                ]
        json_write(workspace.config[f"{StepEnum.RCX.value}"], rcx)
    

def copy_filelist_with_sources(input_filelist: str, workspace_dir: str, logger=None) -> str:
    """
    Copy filelist and all referenced source files + include directories to workspace/origin/.

    Maintains the original directory structure of source files relative to the filelist location.
    Supports +incdir directives with smart deduplication.

    Args:
        input_filelist: Path to the filelist file
        workspace_dir: Target workspace directory
        logger: Optional logger instance for logging operations

    Returns:
        Path to the copied filelist in workspace/origin/

    Raises:
        FileNotFoundError: If filelist file doesn't exist
        IOError: If file copy operations fail

    Example:
        >>> new_filelist_path = copy_filelist_with_sources(
        ...     "/project/design.f",
        ...     "/workspace/gcd"
        ... )
        >>> print(new_filelist_path)
        '/workspace/gcd/origin/design.f'
    """
    import os
    import shutil

    origin_dir = os.path.join(workspace_dir, "origin")
    os.makedirs(origin_dir, exist_ok=True)

    filelist_dir = os.path.dirname(os.path.abspath(input_filelist))
    copied_files = set()
    stats = {'copied': 0, 'missing': 0, 'incdir_copied': 0, 'incdir_skipped': 0}

    # Copy files listed in filelist
    try:
        source_files = parse_filelist(input_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to parse filelist {input_filelist}: {e}")
        raise

    for src_path in source_files:
        abs_src = resolve_path(src_path, filelist_dir)

        if not os.path.exists(abs_src):
            if logger:
                logger.warning(f"File not found (skipping): {abs_src}")
            stats['missing'] += 1
            continue

        rel_path = os.path.basename(src_path) if os.path.isabs(src_path) else src_path

        if rel_path in copied_files:
            if logger:
                logger.debug(f"Skipping duplicate: {rel_path}")
            continue

        if _copy_file_safely(abs_src, os.path.join(origin_dir, rel_path), logger, src_path):
            copied_files.add(rel_path)
            stats['copied'] += 1

    # Copy +incdir directories
    try:
        incdir_paths = parse_incdir_directives(input_filelist)
    except Exception as e:
        if logger:
            logger.warning(f"Failed to parse +incdir directives: {e}")
        incdir_paths = []

    for incdir_path in incdir_paths:
        abs_incdir = resolve_path(incdir_path, filelist_dir)

        if not os.path.exists(abs_incdir):
            if logger:
                logger.warning(f"Include directory not found: {abs_incdir}")
            continue

        if not os.path.isdir(abs_incdir):
            if logger:
                logger.warning(f"Include path is not a directory: {abs_incdir}")
            continue

        for root, dirs, files in os.walk(abs_incdir):
            for filename in files:
                src_file = os.path.join(root, filename)
                rel_from_filelist = os.path.relpath(src_file, filelist_dir)

                if rel_from_filelist in copied_files:
                    stats['incdir_skipped'] += 1
                    if logger:
                        logger.debug(f"Skipping duplicate from +incdir: {rel_from_filelist}")
                    continue

                dst_file = os.path.join(origin_dir, rel_from_filelist)
                if _copy_file_safely(src_file, dst_file, logger, f"+incdir/{src_file}"):
                    copied_files.add(rel_from_filelist)
                    stats['incdir_copied'] += 1

    # Copy filelist file itself
    new_filelist = os.path.join(origin_dir, os.path.basename(input_filelist))
    try:
        shutil.copy2(input_filelist, new_filelist)
    except Exception as e:
        if logger:
            logger.error(f"Failed to copy filelist: {e}")
        raise

    if logger:
        logger.info(
            f"Copied filelist and sources: "
            f"{stats['copied']} files from filelist, "
            f"{stats['incdir_copied']} files from +incdir, "
            f"{stats['missing']} missing, "
            f"{stats['incdir_skipped']} duplicates skipped"
        )

    return new_filelist


def _copy_file_safely(src: str, dst: str, logger, context: str) -> bool:
    """Copy a file with error handling and logging."""
    import os
    import shutil

    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        if logger:
            logger.debug(f"Copied: {src} -> {dst}")
        return True
    except Exception as e:
        if logger:
            logger.error(f"Error copying {context}: {e}")
        return False

                     
def create_workspace(directory : str | Path,
                     origin_def : str | Path,
                     origin_verilog : str | Path,
                     pdk : PDK | str,
                     parameters : Parameters | dict,
                     input_filelist : str | Path = "",
                     pdk_root : str | Path = "",
                     pdk_json : str | Path = "") -> Workspace:
    """
    Create a workspace for chip design flow.

    Args:
        directory: Workspace directory path
        origin_def: Original DEF file path (for physical design)
        origin_verilog: Original verilog file path (RTL or synthesized netlist)
        pdk: PDK information (LEF, Liberty, SDC, etc.)
        parameters: Design parameters (clock, frequency, etc.)
        input_filelist: Optional filelist for synthesis (SystemVerilog sources)

    Returns:
        Workspace instance with all paths configured

    Note:
        - origin_verilog can be either RTL (requires SYNTHESIS step) or
          pre-synthesized netlist (skips SYNTHESIS)
        - input_filelist takes priority over origin_verilog for synthesis when both exist
        - All input files are copied to workspace/origin/ directory
    """
    # create workspace directory
    import shutil

    workspace_dir = Path(directory).expanduser().resolve()
    origin_dir = workspace_dir / "origin"
    home_dir = workspace_dir / "home"
    log_dir = workspace_dir / "log"
    try:
        workspace_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        return None
    
    # create workspace instance
    workspace = Workspace()
    
    # pdk 
    if isinstance(pdk, PDK):
        workspace.pdk = pdk
        
    if isinstance(pdk, str):
        workspace.pdk = get_pdk(pdk_name=pdk, pdk_root=pdk_root, pdk_config=pdk_json)
    
    #update config
    if isinstance(parameters, Parameters):
        workspace.design.name = parameters.data["Design"]
        workspace.design.top_module = parameters.data["Top module"]         
        workspace.parameters = parameters
    
    if isinstance(parameters, dict):
        # format parameters
        pdk_name = workspace.pdk.name or (pdk if isinstance(pdk, str) else "")
        workspace.parameters = get_parameters(pdk_name)
        update_parameters(parameters_src=parameters,
                          parameters_target=workspace.parameters.data)
        
        workspace.design.name = workspace.parameters.data["Design"]
        workspace.design.top_module = workspace.parameters.data["Top module"]         
    
    # update path
    workspace.directory = workspace_dir
    workspace.config = build_workspace_config_paths(workspace)
    
    # create logger first (needed for copy operations)
    log_dir.mkdir(parents=True, exist_ok=True)
    workspace.logger = create_logger(name=workspace.parameters.data["Design"],
                                     log_dir=log_dir)

    # update orign files to workspace origin folder
    origin_dir.mkdir(parents=True, exist_ok=True)
    workspace.config["dir"].mkdir(parents=True, exist_ok=True)
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

    # Copy filelist and all referenced source files
    input_filelist_path = Path(input_filelist) if input_filelist else None
    if input_filelist_path and input_filelist_path.exists():
        try:
            # Use new copy_filelist_with_sources to copy filelist + all RTL files
            workspace.design.input_filelist = Path(copy_filelist_with_sources(
                input_filelist=str(input_filelist_path),
                workspace_dir=str(workspace_dir),
                logger=workspace.logger
            ))
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

    init_workspace_config(workspace)

    # set home data
    home_dir.mkdir(parents=True, exist_ok=True)
    workspace.flow.path = home_dir / "flow.json"
    workspace.parameters.path = home_dir / "parameters.json"
    workspace.home.init(path=home_dir / "home.json")
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(home_dir / "checklist.json")
    workspace.home.set_parameters(workspace.parameters.path)
    
    if workspace.pdk.root:
        workspace.parameters.data["PDK Root"] = str(workspace.pdk.root)
    if pdk_json:
        pdk_config_path = os.path.abspath(f"{directory}/home/pdk.json")
        shutil.copy(pdk_json, pdk_config_path)
        workspace.parameters.data["PDK Config"] = pdk_config_path

    # save parameter
    save_parameter(workspace.parameters)
    
    log_workspace(workspace)
    log_parameters(workspace)
     
    return workspace

def load_workspace(directory : str | Path) -> Workspace:
    workspace_dir = Path(directory).expanduser().resolve()
    origin_dir = workspace_dir / "origin"
    home_dir = workspace_dir / "home"
    if not workspace_dir.exists():
        return None
    
    # create workspace instance
    workspace = Workspace()
    workspace.directory = workspace_dir
    workspace.config = build_workspace_config_paths(workspace)

    parameters = load_parameter(home_dir / "parameters.json")
    if len(parameters.data)<=0:
        return None
    
    workspace.parameters = parameters
    
    pdk = get_pdk(
        pdk_name=parameters.data.get("PDK", ""),
        pdk_root=parameters.data.get("PDK Root", ""),
        pdk_config=parameters.data.get("PDK Config", ""),
    )
    sdc_path = list(origin_dir.rglob("*.sdc"))
    if len(sdc_path) > 0:
        pdk.sdc = sdc_path[0]
    spef_path = list(origin_dir.rglob("*.spef"))
    if len(spef_path) > 0:
        pdk.spef = spef_path[0]
        
    # update lef and lib paths based on config
    from chipcompiler.utility import json_read
    db_json = json_read(workspace.config.get("db", ""))
    if db_json.get("INPUT", {}).get("tech_lef_path", "") != "":
        pdk.tech = Path(db_json.get("INPUT", {}).get("tech_lef_path", ""))
    if db_json.get("INPUT", {}).get("lef_paths", []) != []:
        pdk.lefs = [Path(path) for path in db_json.get("INPUT", {}).get("lef_paths", [])]
    if db_json.get("INPUT", {}).get("lib_path", []) != []:
        pdk.libs = [Path(path) for path in db_json.get("INPUT", {}).get("lib_path", [])]
    workspace.pdk = pdk
    
    #update config
    workspace.design.name = parameters.data.get("Design", "")
    workspace.design.top_module = parameters.data.get("Top module", "")  
    def_path = list(origin_dir.rglob("*.def"))
    def_gz_path = list(origin_dir.rglob("*.def.gz"))
    if len(def_path) > 0:
        workspace.design.origin_def = def_path[0]
    if len(def_gz_path) > 0:
        workspace.design.origin_def = def_gz_path[0]
        
    verilog_path = list(origin_dir.rglob("*.v"))
    verilog_gz_path = list(origin_dir.rglob("*.v.gz"))
    if len(verilog_path) > 0:
        workspace.design.origin_verilog = verilog_path[0]
    if len(verilog_gz_path) > 0:
        workspace.design.origin_verilog = verilog_gz_path[0]
    
    filelist_path = origin_dir / "filelist"
    if filelist_path.exists():
        workspace.design.input_filelist = filelist_path
        
    # set home data
    home_dir.mkdir(parents=True, exist_ok=True)
    workspace.config["dir"].mkdir(parents=True, exist_ok=True)
    workspace.flow.path = home_dir / "flow.json"
    workspace.home.init(path=home_dir / "home.json")
    workspace.home.set_flow(workspace.flow.path)
    workspace.home.set_checklist(home_dir / "checklist.json")
    workspace.home.set_parameters(workspace.parameters.path)
    
    # create logger first (needed for copy operations)
    workspace.logger = create_logger(name=parameters.data["Design"],
                                     log_dir=workspace_dir / "log")
    
    log_workspace(workspace)
    log_parameters(workspace)

    return workspace

def log_workspace(workspace : Workspace):
    def format_string(text : str, len=20) -> str:
        return text.ljust(len, " ")
    
    workspace.logger.log_section("workspace info") 
    workspace.logger.info("workspace      : %s", workspace.directory)
    workspace.logger.info("config         : %s", workspace.config.get("dir", ""))
    workspace.logger.info("PDK            : %s", workspace.pdk.name)
    workspace.logger.info("design         : %s", workspace.design.name)
    workspace.logger.info("top module     : %s", workspace.design.top_module)
    workspace.logger.info("origin def     : %s", workspace.design.origin_def)
    workspace.logger.info("origin verilog : %s", workspace.design.origin_verilog)
    workspace.logger.info("input filelist : %s", workspace.design.input_filelist)
    workspace.logger.info("sdc            : %s", workspace.pdk.sdc)
    workspace.logger.info("spef           : %s", workspace.pdk.spef)
    
def log_parameters(workspace : Workspace):       
    workspace.logger.log_section("parameters info") 
    workspace.logger.info("parameters     : %s", workspace.parameters.path)
    workspace.logger.info("\n%s", dict_to_str(workspace.parameters.data))
    
def log_flow(workspace : Workspace):
    def format_string(text : str, len=20) -> str:
        return text.ljust(len, " ")
        
    workspace.logger.log_section("flow info")
    workspace.logger.info("flow           : %s", workspace.flow.path)
    workspace.logger.info("%s | %s | %s | %s", 
                              format_string("name"),
                              format_string("tool"),
                              format_string("state"),
                              format_string("runtime"))
    for step in workspace.flow.data.get("steps", []):
        workspace.logger.info("%s | %s | %s | %s", 
                              format_string(step.get("name", "")),
                              format_string(step.get("tool", "")),
                              format_string(step.get("state", "")),
                              format_string(step.get("runtime", "")))

def create_default_sdc(workspace : Workspace):
    """
    Create SDC file based on PDK and workspace parameters.
    """
    sdc_content = []
    sdc_content.append("# Auto-generated SDC file\n")
    sdc_content.append("\n")
    sdc_content.append("set clk_name {} \n".format(workspace.parameters.data.get("Clock", "")))
    sdc_content.append("set clk_port_name {}\n".format(workspace.parameters.data.get("Clock", "")))
    sdc_content.append("set clk_freq_mhz {}\n".format(workspace.parameters.data.get("Frequency max [MHz]", 100)))
    sdc_content.append("set clk_period [expr 1000.0 / $clk_freq_mhz]\n")
    sdc_content.append("set clk_io_pct 0.2\n")
    sdc_content.append("set clk_port [get_ports $clk_port_name]\n")
    sdc_content.append("create_clock -name $clk_name -period $clk_period $clk_port\n")
    
    with open(workspace.pdk.sdc, 'w') as file:
        file.writelines(sdc_content)
