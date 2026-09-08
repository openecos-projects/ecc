import shutil
import tempfile
from pathlib import Path
from typing import Any

from chipcompiler.cli.project.params import build_backend_overrides, resolve_parameters
from chipcompiler.data import PDK, create_workspace
from chipcompiler.engine.workspace_spec import validate_workspace_spec
from chipcompiler.rtl2gds import get_flow_builders


class WorkspaceLifecycleError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def create_workspace_from_spec(
    target_directory: str | Path,
    spec: object,
    bindings: object,
    command_id: str = "",
):
    del command_id
    target = Path(target_directory).expanduser().resolve()
    if target.exists():
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
    backend_parameters = build_backend_overrides(parameters)
    backend_parameters.update(
        {
            "design": resolved["design"]["name"],
            "top_module": resolved["design"]["topModule"],
            "clock": resolved["design"].get("clockPort", ""),
        }
    )
    flow_steps = get_flow_builders()[resolved["flow"]["flowId"]]()
    flow_config = {
        "start_step": str(getattr(flow_steps[0][0], "value", flow_steps[0][0])),
        "end_step": str(getattr(flow_steps[-1][0], "value", flow_steps[-1][0])),
    }
    pdk, pdk_root, pdk_overrides = _bound_pdk(
        resolved["pdk"], _string_keyed_dict(binding_map["pdk"])
    )

    generated_filelist: str | None = None
    if len(rtl_paths) > 1:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", suffix=".f", delete=False
        ) as handle:
            handle.write("\n".join(rtl_paths) + "\n")
            generated_filelist = handle.name

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
            pdk=pdk,
            pdk_root=pdk_root,
            pdk_overrides=pdk_overrides,
            parameters=backend_parameters,
            flow_config=flow_config,
        )
        if workspace is None:
            raise WorkspaceLifecycleError(
                "workspace_create_failed", f"Workspace creation failed: {target}"
            )
        return workspace
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise
    finally:
        if generated_filelist is not None:
            Path(generated_filelist).unlink(missing_ok=True)


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
