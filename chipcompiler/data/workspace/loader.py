"""Hydrate a Workspace from committed files without mixing migration policy."""

from pathlib import Path
from typing import Any

from chipcompiler.utility import Logger, create_logger, json_read

from ..parameter import load_parameter
from ..pdk import get_pdk
from ..workspace_config import (
    legacy_parameters_fallback,
    migrate_legacy_parameters,
)
from ..workspace_config import (
    workspace_config_path as workspace_config_toml_path,
)


def load_workspace(directory: str | Path, *, read_only: bool = False) -> Any:
    from . import (
        Workspace,
        _persisted_golden_verilog,
        build_workspace_config_paths,
        log_parameters,
        log_workspace,
        migrate_workspace_config_filenames,
    )

    workspace_dir = Path(directory).expanduser().resolve()
    origin_dir = workspace_dir / "origin"
    home_dir = workspace_dir / "home"
    if not workspace_dir.exists():
        return None

    if not read_only:
        migrate_legacy_parameters(workspace_dir)

    workspace = Workspace()
    workspace.directory = workspace_dir
    if not read_only:
        migrate_workspace_config_filenames(workspace_dir)
    workspace.config = build_workspace_config_paths(workspace)

    config_path = workspace_config_toml_path(workspace_dir)
    legacy_path = home_dir / "parameters.json"
    if config_path.is_symlink():
        from chipcompiler.data.workspace_config import WorkspaceConfigError

        raise WorkspaceConfigError(f"workspace config is a symlink: {config_path}")
    parameters = load_parameter(config_path)
    if len(parameters.data) <= 0 and not config_path.exists() and legacy_path.exists():
        fallback = legacy_parameters_fallback(workspace_dir)
        if fallback:
            parameters.data = fallback
    if len(parameters.data) <= 0:
        return None

    workspace.parameters = parameters
    pdk = get_pdk(
        pdk_name=parameters.data.get("pdk", ""),
        pdk_root=parameters.data.get("pdk_root", ""),
        pdk_config=parameters.data.get("pdk_config", ""),
        validate=not read_only,
    )
    sdc_path = list(origin_dir.rglob("*.sdc"))
    if sdc_path:
        pdk.sdc = sdc_path[0]
    spef_path = list(origin_dir.rglob("*.spef"))
    if spef_path:
        pdk.spef = spef_path[0]

    db_json = json_read(workspace.config.get("db", ""))
    if db_json.get("INPUT", {}).get("tech_lef_path", "") != "":
        pdk.tech = Path(db_json["INPUT"]["tech_lef_path"])
    if db_json.get("INPUT", {}).get("lef_paths", []) != []:
        pdk.lefs = [Path(path) for path in db_json["INPUT"]["lef_paths"]]
    if db_json.get("INPUT", {}).get("lib_path", []) != []:
        pdk.libs = [Path(path) for path in db_json["INPUT"]["lib_path"]]
    workspace.pdk = pdk

    workspace.design.name = parameters.data.get("design", "")
    workspace.design.top_module = parameters.data.get("top_module", "")
    def_path = list(origin_dir.rglob("*.def"))
    def_gz_path = list(origin_dir.rglob("*.def.gz"))
    if def_path:
        workspace.design.origin_def = def_path[0]
    if def_gz_path:
        workspace.design.origin_def = def_gz_path[0]

    golden, golden_declared = _persisted_golden_verilog(workspace_dir)
    if golden is None and not golden_declared:
        golden_paths = list(origin_dir.rglob("golden_*.v")) + list(
            origin_dir.rglob("golden_*.v.gz")
        )
        golden = golden_paths[0] if golden_paths else None

    verilog_path = [path for path in origin_dir.rglob("*.v") if path != golden]
    verilog_gz_path = [path for path in origin_dir.rglob("*.v.gz") if path != golden]
    if verilog_path:
        workspace.design.origin_verilog = verilog_path[0]
    if verilog_gz_path:
        workspace.design.origin_verilog = verilog_gz_path[0]
    if golden is not None:
        workspace.design.golden_verilog = golden

    filelist_path = origin_dir / "filelist"
    if filelist_path.exists():
        workspace.design.input_filelist = filelist_path

    workspace.flow.path = home_dir / "flow.json"
    if read_only:
        workspace.home.path = home_dir / "home.json"
        home_data = json_read(workspace.home.path)
        workspace.home.data = home_data if isinstance(home_data, dict) else {}
        workspace.logger = Logger(name=parameters.data["design"])
    else:
        home_dir.mkdir(parents=True, exist_ok=True)
        workspace.config["dir"].mkdir(parents=True, exist_ok=True)
        workspace.home.init(path=home_dir / "home.json")
        workspace.home.set_flow(workspace.flow.path)
        workspace.home.set_checklist(home_dir / "checklist.json")
        workspace.home.set_parameters(workspace.parameters.path)
        workspace.logger = create_logger(
            name=parameters.data["design"], log_dir=workspace_dir / "log"
        )
        log_workspace(workspace)
        log_parameters(workspace)

    return workspace
