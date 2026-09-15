"""Read-only inspection and manifest registration for existing workspaces."""

import os
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path


class WorkspaceRegistrationError(ValueError):
    """An existing directory cannot be registered as a managed workspace."""

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class ExistingWorkspaceMetadata:
    flow_config: dict[str, str]
    status: str
    parameter_patch: dict


def is_ecc_workspace_directory(path: str) -> bool:
    """Return whether *path* has an unlinked ECC flow/config boundary."""
    if not os.path.isdir(path) or os.path.islink(path):
        return False
    home = os.path.join(path, "home")
    flow_json = os.path.join(home, "flow.json")
    params_toml = os.path.join(home, "params.toml")
    return (
        not os.path.islink(home)
        and not os.path.islink(flow_json)
        and not os.path.islink(params_toml)
        and os.path.isfile(flow_json)
        and os.path.isfile(params_toml)
    )


def inspect_existing_workspace(
    path: str, cfg=None, *, base_parameters: dict | None = None
) -> ExistingWorkspaceMetadata:
    """Inspect an existing workspace without opening or modifying it."""
    if not is_ecc_workspace_directory(path):
        raise WorkspaceRegistrationError(
            "workspace_not_importable",
            "directory does not contain an ECC home/flow.json and home/params.toml",
        )

    from chipcompiler.cli.inspection.discovery import get_run_status, read_flow_json
    from chipcompiler.data.workspace_config import flow_range_of, load_workspace_config

    try:
        parameters = load_workspace_config(path)
        flow_range = flow_range_of(parameters.get("_flow", {}))
    except Exception as exc:
        raise WorkspaceRegistrationError("workspace_not_importable", str(exc)) from exc
    if flow_range is None:
        raise WorkspaceRegistrationError(
            "workspace_not_importable", "workspace has no persisted flow target"
        )

    flow_data = read_flow_json(path)
    if not isinstance(flow_data, dict):
        raise WorkspaceRegistrationError(
            "workspace_not_importable", "workspace flow.json is missing or malformed"
        )

    if cfg is not None:
        workspace_design = str(parameters.get("design") or "").strip()
        workspace_pdk = str(parameters.get("pdk") or "").strip()
        if workspace_design and cfg.design_name and workspace_design != cfg.design_name:
            raise WorkspaceRegistrationError(
                "workspace_not_importable",
                f"workspace design {workspace_design!r} does not match project design "
                f"{cfg.design_name!r}",
            )
        if workspace_pdk and cfg.pdk_name and workspace_pdk != cfg.pdk_name:
            raise WorkspaceRegistrationError(
                "workspace_not_importable",
                f"workspace PDK {workspace_pdk!r} does not match project PDK {cfg.pdk_name!r}",
            )

    observed = get_run_status(flow_data)
    status = observed if observed in ("success", "failed") else "not_started"
    parameter_patch = {}
    for key, value in parameters.items():
        if key in {
            "_flow",
            "pdk",
            "pdk_root",
            "pdk_config",
            "design",
            "top_module",
            "clock",
            "config_overrides",
            "workspace_param_overrides",
        }:
            continue
        previous = (base_parameters or {}).get(key)
        if previous != value:
            parameter_patch[key] = {
                "from": deepcopy(previous),
                "to": deepcopy(value),
            }
    return ExistingWorkspaceMetadata(
        flow_config={"start_step": flow_range[0], "end_step": flow_range[1]},
        status=status,
        parameter_patch=parameter_patch,
    )


def register_existing_workspace(
    project_dir: str,
    *,
    cfg,
    pdk_root: str,
    workspace_id: str,
    workspace_path: str,
    project_lock_held: bool = False,
) -> tuple[str, ExistingWorkspaceMetadata]:
    """Inspect and atomically register an existing workspace.

    Callers already dispatching under the project lock can opt out of taking
    it twice. The workspace is inspected once before any lock and again while
    locked so an import never binds metadata read from a replaced directory.
    """
    from chipcompiler.cli.project import migrate_fs
    from chipcompiler.engine.reconcile import _workspace_lock
    from chipcompiler.project.manifest import base_design_from_config
    from chipcompiler.project.manifest_write import pre_register_workspace

    base_parameters = base_design_from_config(cfg, pdk_root).get("parameters", {})
    inspect_existing_workspace(workspace_path, cfg, base_parameters=base_parameters)
    project_lock = (
        nullcontext()
        if project_lock_held
        else migrate_fs.project_migrate_lock(project_dir, exclusive=False)
    )
    with project_lock, _workspace_lock(Path(workspace_path)):
        metadata = inspect_existing_workspace(
            workspace_path,
            cfg,
            base_parameters=base_parameters,
        )
        outcome = pre_register_workspace(
            project_dir,
            cfg=cfg,
            pdk_root=pdk_root,
            workspace_id=workspace_id,
            workspace_path=workspace_path,
            flow_config=metadata.flow_config,
            status=metadata.status,
            parameter_patch=metadata.parameter_patch,
        )
    return outcome, metadata
