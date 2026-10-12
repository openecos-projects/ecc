"""Engine package — lazy public exports to avoid import cycles.

Importing ``chipcompiler.runtime.signoff.catalog`` (checklist SoT) must not pull
``EngineDB`` / tool modules; those load only when first accessed by name.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "EngineDB",
    "EngineFlow",
    "ExecutionPlan",
    "ExecutionResult",
    "StepRunResult",
    "SignoffPackageCollector",
    "SignoffPackageOptions",
    "WorkspaceLifecycleError",
    "apply_workspace_bindings",
    "apply_workspace_parameters",
    "assess_execution_readiness",
    "create_workspace_from_spec",
    "describe_workspace_spec",
    "describe_workspace_binding_requirement",
    "execute",
    "read_step_configuration",
    "read_step_configuration_from_directory",
    "read_workspace_configuration",
    "read_workspace_configuration_from_directory",
    "reset_workspace_flow",
    "update_workspace_from_spec",
    "update_workspace_step_configuration",
    "update_workspace_configuration",
    "validate_workspace_spec",
]

_EXPORTS: dict[str, tuple[str, str]] = {
    "EngineDB": (".db", "EngineDB"),
    "EngineFlow": (".flow", "EngineFlow"),
    "ExecutionPlan": (".execution", "ExecutionPlan"),
    "ExecutionResult": (".execution", "ExecutionResult"),
    "execute": (".execution", "execute"),
    "StepRunResult": (".rerun", "StepRunResult"),
    "SignoffPackageCollector": (".signoff", "SignoffPackageCollector"),
    "SignoffPackageOptions": (".signoff", "SignoffPackageOptions"),
    "WorkspaceLifecycleError": (".workspace_lifecycle", "WorkspaceLifecycleError"),
    "apply_workspace_bindings": (".workspace_lifecycle", "apply_workspace_bindings"),
    "assess_execution_readiness": (
        ".workspace_lifecycle",
        "assess_execution_readiness",
    ),
    "create_workspace_from_spec": (
        ".workspace_lifecycle",
        "create_workspace_from_spec",
    ),
    "describe_workspace_binding_requirement": (
        ".workspace_lifecycle",
        "describe_workspace_binding_requirement",
    ),
    "update_workspace_from_spec": (
        ".workspace_lifecycle",
        "update_workspace_from_spec",
    ),
    "describe_workspace_spec": (".workspace_spec", "describe_workspace_spec"),
    "validate_workspace_spec": (".workspace_spec", "validate_workspace_spec"),
    "apply_workspace_parameters": (
        ".workspace_configuration",
        "apply_workspace_parameters",
    ),
    "read_step_configuration": (".workspace_configuration", "read_step_configuration"),
    "read_step_configuration_from_directory": (
        ".workspace_configuration",
        "read_step_configuration_from_directory",
    ),
    "read_workspace_configuration": (
        ".workspace_configuration",
        "read_workspace_configuration",
    ),
    "read_workspace_configuration_from_directory": (
        ".workspace_configuration",
        "read_workspace_configuration_from_directory",
    ),
    "update_workspace_configuration": (
        ".workspace_configuration",
        "update_workspace_configuration",
    ),
    "update_workspace_step_configuration": (
        ".workspace_configuration",
        "update_workspace_step_configuration",
    ),
    "reset_workspace_flow": (".workspace_reset", "reset_workspace_flow"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    from importlib import import_module

    value = getattr(import_module(module_name, __name__), attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
