import ctypes
import errno
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from chipcompiler.data import PDK, create_workspace, get_pdk, load_workspace
from chipcompiler.data.parameter_schema import (
    build_backend_overrides,
    build_config_overrides,
    resolve_parameters,
)
from chipcompiler.data.workspace.config_overrides import CONFIG_OVERRIDES_KEY
from chipcompiler.engine.snapshot import create_engineering_snapshot
from chipcompiler.engine.workspace_spec import validate_workspace_spec
from chipcompiler.rtl2gds import get_flow_builders


class WorkspaceLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def describe_workspace_binding_requirement(
    workspace_directory: str | Path,
) -> dict[str, Any]:
    workspace = _load_committed_workspace(Path(workspace_directory).expanduser().resolve())
    return {
        "familyId": workspace.pdk.name,
        "version": workspace.pdk.version or "unversioned",
        "mode": "manual" if workspace.parameters.data.get("pdk_config") else "default",
    }


def assess_execution_readiness(
    workspace_directory: str | Path,
    bindings: object | None,
) -> dict[str, Any]:
    try:
        workspace = _load_committed_workspace(Path(workspace_directory).expanduser().resolve())
    except (OSError, ValueError, WorkspaceLifecycleError):
        return {"ready": False, "code": "workspace_invalid"}
    binding_map = _string_keyed_dict(bindings)
    pdk_binding = _string_keyed_dict(binding_map.get("pdk"))
    root = pdk_binding.get("root")
    if not isinstance(root, str) or not Path(root).is_dir():
        return {"ready": False, "code": "pdk_binding_missing"}
    try:
        if workspace.parameters.data.get("pdk_config"):
            if workspace.pdk.root is None or Path(root).resolve() != workspace.pdk.root.resolve():
                return {"ready": False, "code": "pdk_binding_mismatch"}
            workspace.pdk.validate()
        else:
            get_pdk(workspace.pdk.name, pdk_root=root).validate()
    except (OSError, ValueError):
        return {"ready": False, "code": "pdk_binding_mismatch"}
    return {"ready": True}


def apply_workspace_bindings(workspace, bindings: object) -> None:
    binding_map = _string_keyed_dict(bindings)
    pdk_binding = _string_keyed_dict(binding_map.get("pdk"))
    root = pdk_binding.get("root")
    if not isinstance(root, str) or not Path(root).is_dir():
        raise WorkspaceLifecycleError("pdk_binding_missing", "PDK binding root is required")
    sdc, spef = workspace.pdk.sdc, workspace.pdk.spef
    if workspace.parameters.data.get("pdk_config"):
        if workspace.pdk.root is None or Path(root).resolve() != workspace.pdk.root.resolve():
            raise WorkspaceLifecycleError("pdk_binding_mismatch", "PDK binding root does not match")
        workspace.pdk.validate()
    else:
        workspace.pdk = get_pdk(workspace.pdk.name, pdk_root=root)
    workspace.pdk.sdc, workspace.pdk.spef = sdc, spef
    from chipcompiler.data import refresh_workspace_config

    refresh_workspace_config(workspace)


def create_workspace_from_spec(
    target_directory: str | Path,
    spec: object,
    bindings: object,
    command_id: str = "",
):
    """Create a Workspace Spec target while serializing sibling creators."""
    from chipcompiler.engine.reconcile import _workspace_lock

    target = Path(target_directory).expanduser().resolve()
    with _workspace_lock(target):
        return _create_workspace_from_spec(target, spec, bindings, command_id)


def _create_workspace_from_spec(
    target_directory: str | Path,
    spec: object,
    bindings: object,
    command_id: str = "",
):
    target = Path(target_directory).expanduser().resolve()
    fingerprint = _workspace_command_fingerprint("create", spec, bindings)
    if target.exists():
        if command_id and _command_retry_matches(target, command_id, fingerprint):
            return _load_committed_workspace(target)
        raise WorkspaceLifecycleError("workspace_exists", f"Workspace already exists: {target}")
    validation = validate_workspace_spec(spec, bindings)
    issues = validation["issues"]
    if issues:
        raise WorkspaceLifecycleError(
            "workspace_spec_invalid",
            "Workspace Spec validation failed",
            {"issues": issues},
        )
    resolved = validation["resolvedWorkspaceSpec"]
    binding_map = _string_keyed_dict(bindings)
    input_bindings = _string_keyed_dict(binding_map.get("inputs"))
    input_paths = {
        item["role"]: str(input_bindings[item["inputId"]]) for item in resolved["inputs"]
    }
    rtl_paths = [
        str(input_bindings[item["inputId"]]) for item in resolved["inputs"] if item["role"] == "rtl"
    ]
    parameters, errors = resolve_parameters(toml_overrides=resolved["parameters"])
    if errors:
        raise WorkspaceLifecycleError(
            "workspace_spec_invalid",
            "Workspace parameters are invalid",
            {"issues": errors},
        )
    backend_parameters = build_backend_overrides(parameters, include_defaults=True)
    config_overrides = build_config_overrides(parameters)
    if config_overrides:
        backend_parameters[CONFIG_OVERRIDES_KEY] = config_overrides
    backend_parameters.update(
        {
            "design": resolved["design"]["name"],
            "top_module": resolved["design"]["topModule"],
            "clock": resolved["design"].get("clockPort", ""),
        }
    )
    flow_steps = get_flow_builders()[resolved["flow"]["flowId"]]()
    flow_start = resolved["flow"].get("fromStepId")
    flow_end = resolved["flow"].get("throughStepId")
    flow_config = {
        "start_step": flow_start or str(getattr(flow_steps[0][0], "value", flow_steps[0][0])),
        "end_step": flow_end or str(getattr(flow_steps[-1][0], "value", flow_steps[-1][0])),
    }
    pdk, pdk_root, pdk_overrides = _bound_pdk(
        resolved["pdk"], _string_keyed_dict(binding_map["pdk"])
    )

    generated_filelist: str | None = None
    generated_pdk_config: str | None = None
    if len(rtl_paths) > 1:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".f", delete=False
        ) as handle:
            handle.write("\n".join(rtl_paths) + "\n")
            generated_filelist = handle.name
    if isinstance(pdk, PDK):
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".json", delete=False
        ) as handle:
            json.dump(_pdk_config(pdk), handle)
            generated_pdk_config = handle.name

    try:
        workspace = create_workspace(
            directory=target,
            origin_def=input_paths.get("def", ""),
            origin_verilog=(
                input_paths.get("netlist", "") or (rtl_paths[0] if len(rtl_paths) == 1 else "")
            ),
            input_filelist=input_paths.get("filelist", "") or generated_filelist or "",
            golden_verilog=input_paths.get("goldenNetlist", ""),
            sdc=input_paths.get("sdc", ""),
            spef=input_paths.get("spef", ""),
            pdk=pdk.name if isinstance(pdk, PDK) else pdk,
            pdk_root=pdk_root,
            pdk_json=generated_pdk_config or "",
            pdk_overrides=pdk_overrides,
            parameters=backend_parameters,
            flow_config=flow_config,
        )
        if workspace is None:
            raise WorkspaceLifecycleError(
                "workspace_create_failed", f"Workspace creation failed: {target}"
            )
        workspace.parameters.data["_input_mode"] = resolved["inputMode"]
        from chipcompiler.data import save_parameter

        if not save_parameter(workspace.parameters):
            raise OSError(f"Failed to persist input mode: {workspace.parameters.path}")
        snapshot = create_engineering_snapshot(workspace)
        _write_workspace_command(
            target,
            command_id,
            fingerprint,
            snapshot["workspaceId"],
            snapshot["workspaceRevision"],
        )
        return workspace
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if generated_filelist is not None:
            Path(generated_filelist).unlink(missing_ok=True)
        if generated_pdk_config is not None:
            Path(generated_pdk_config).unlink(missing_ok=True)


def update_workspace_from_spec(
    target_directory: str | Path,
    expected_workspace_revision: int,
    spec: object,
    bindings: object,
    command_id: str = "",
):
    target = Path(target_directory).expanduser().resolve()
    if not target.is_dir():
        raise WorkspaceLifecycleError("workspace_missing", f"Workspace not found: {target}")
    from chipcompiler.engine.reconcile import _workspace_lock

    with _workspace_lock(target):
        return _update_workspace_from_spec(
            target, expected_workspace_revision, spec, bindings, command_id
        )


def _update_workspace_from_spec(
    target_directory: str | Path,
    expected_workspace_revision: int,
    spec: object,
    bindings: object,
    command_id: str = "",
):
    from chipcompiler.engine.snapshot import (
        EngineeringSnapshotError,
        ensure_engineering_snapshot,
        read_engineering_snapshot,
    )

    target = Path(target_directory).expanduser().resolve()
    fingerprint = _workspace_command_fingerprint(
        "update", spec, bindings, expected_workspace_revision
    )
    if command_id and _command_retry_matches(target, command_id, fingerprint):
        return _load_committed_workspace(target)
    current = _load_committed_workspace(target)
    snapshot_path = target / "home" / "engineering-snapshot.json"
    try:
        snapshot = read_engineering_snapshot(current)
    except EngineeringSnapshotError as exc:
        if snapshot_path.exists() or snapshot_path.is_symlink():
            raise WorkspaceLifecycleError(
                "workspace_invalid", "Invalid Engineering Snapshot"
            ) from exc
        if expected_workspace_revision != 1:
            raise WorkspaceLifecycleError(
                "revision_conflict",
                "Workspace Revision does not match",
                {
                    "expectedWorkspaceRevision": expected_workspace_revision,
                    "actualWorkspaceRevision": 1,
                },
            ) from exc
        snapshot = ensure_engineering_snapshot(current)
    if snapshot["workspaceRevision"] != expected_workspace_revision:
        raise WorkspaceLifecycleError(
            "revision_conflict",
            "Workspace Revision does not match",
            {
                "expectedWorkspaceRevision": expected_workspace_revision,
                "actualWorkspaceRevision": snapshot["workspaceRevision"],
            },
        )

    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    staging.rmdir()
    try:
        staged = create_workspace_from_spec(staging, spec, bindings)
        create_engineering_snapshot(
            staged,
            workspace_id=snapshot["workspaceId"],
            workspace_revision=snapshot["workspaceRevision"] + 1,
            cause="workspace.updated",
        )
        _copy_workspace_commands(target, staging)
        _write_workspace_command(
            staging,
            command_id,
            fingerprint,
            snapshot["workspaceId"],
            snapshot["workspaceRevision"] + 1,
        )
        _rewrite_workspace_paths(staging, target)
        _exchange_directories(target, staging)
        try:
            return _load_committed_workspace(target)
        except Exception:
            _exchange_directories(target, staging)
            raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _pdk_config(pdk: PDK) -> dict[str, Any]:
    return {
        "name": pdk.name,
        "version": pdk.version,
        "root": str(pdk.root or ""),
        "tech": str(pdk.tech or ""),
        "lefs": [str(path) for path in pdk.lefs],
        "libs": [str(path) for path in pdk.libs],
        "mapping_file": str(pdk.mapping_file or ""),
        "dont_use": pdk.dont_use,
        "abc_load": pdk.abc_load,
    }


def _bound_pdk(spec: dict, binding: dict) -> tuple[PDK | str, str, dict | None]:
    root = Path(str(binding["root"]))
    overrides = spec.get("overrides", {})
    if spec["mode"] != "manual":
        return (
            spec["familyId"],
            str(root),
            {
                **({"dont_use": overrides["dont_use"]} if "dont_use" in overrides else {}),
                **({"abc_load": overrides["abc_load"]} if "abc_load" in overrides else {}),
            },
        )
    files = binding.get("files", {})
    by_role: dict[str, list[Path]] = {}
    for item in spec.get("files", []):
        by_role.setdefault(item["role"], []).append(Path(str(files[item["fileId"]])))
    return (
        PDK(
            name=spec["familyId"],
            version=spec.get("version", ""),
            root=root,
            tech=by_role["tech"][0],
            lefs=by_role.get("lef", []),
            libs=by_role.get("liberty", []),
            mapping_file=(by_role.get("mapping") or [None])[0],
            dont_use=overrides.get("dont_use", []),
            abc_load=float(overrides.get("abc_load", 0.015)),
        ),
        "",
        None,
    )


def _string_keyed_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _load_committed_workspace(path: Path):
    workspace = load_workspace(path)
    if workspace is None:
        raise WorkspaceLifecycleError("workspace_invalid", f"Workspace cannot be opened: {path}")
    return workspace


def _workspace_command_fingerprint(
    kind: str,
    spec: object,
    bindings: object,
    expected_revision: int | None = None,
) -> str:
    payload = json.dumps(
        {
            "kind": kind,
            "spec": spec,
            "bindings": bindings,
            "expectedWorkspaceRevision": expected_revision,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _workspace_commands(path: Path) -> dict[str, Any]:
    command_path = path / "home" / "workspace-commands.json"
    try:
        payload = json.loads(command_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schemaVersion": 1, "commands": {}}
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("commands"), dict):
        raise WorkspaceLifecycleError("workspace_invalid", "Invalid Workspace command ledger")
    return payload


def _command_retry_matches(path: Path, command_id: str, fingerprint: str) -> bool:
    record = _workspace_commands(path)["commands"].get(command_id)
    if record is None:
        return False
    if not isinstance(record, dict) or record.get("fingerprint") != fingerprint:
        raise WorkspaceLifecycleError(
            "idempotency_conflict", f"command id reused with different input: {command_id}"
        )
    return True


def _write_workspace_command(
    path: Path,
    command_id: str,
    fingerprint: str,
    workspace_id: str,
    workspace_revision: int,
) -> None:
    if not command_id:
        return
    from chipcompiler.utility import json_write

    payload = _workspace_commands(path)
    payload["commands"][command_id] = {
        "fingerprint": fingerprint,
        "result": {
            "workspaceId": workspace_id,
            "workspaceRevision": workspace_revision,
        },
    }
    if not json_write(path / "home" / "workspace-commands.json", payload):
        raise OSError("Failed to persist Workspace command ledger")


def _copy_workspace_commands(source: Path, destination: Path) -> None:
    source_path = source / "home" / "workspace-commands.json"
    if source_path.is_file():
        shutil.copy2(source_path, destination / "home" / "workspace-commands.json")


def _rewrite_workspace_paths(source_root: Path, target_root: Path) -> None:
    from chipcompiler.utility import json_write

    source = str(source_root)
    target = str(target_root)
    for path in source_root.rglob("*.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rewritten = _replace_string_prefix(value, source, target)
        if rewritten != value and not json_write(path, rewritten):
            raise OSError(f"Failed to rewrite staged Workspace path: {path}")


def _replace_string_prefix(value: Any, source: str, target: str) -> Any:
    if isinstance(value, str):
        return target + value[len(source) :] if value.startswith(source) else value
    if isinstance(value, list):
        return [_replace_string_prefix(item, source, target) for item in value]
    if isinstance(value, dict):
        return {key: _replace_string_prefix(item, source, target) for key, item in value.items()}
    return value


def _exchange_directories(left: Path, right: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if os.name != "posix" or renameat2 is None:
        raise OSError(errno.ENOTSUP, "atomic Workspace Update is unavailable")
    if renameat2(-100, os.fsencode(left), -100, os.fsencode(right), 2) == 0:
        return
    error = ctypes.get_errno()
    raise OSError(error, os.strerror(error))
