"""Explicit LEC-engine switch for an existing workspace.

Kept out of workspace_api.py (over the module-size guideline): the switch
is one narrow transaction over the ledger and the workspace config.
"""

from pathlib import Path

from chipcompiler.runtime.errors import RuntimeApiError


def switch_lec_engine(workspace, engine) -> tuple[str, ...]:
    """Point the workspace's LEC ledger steps at a different engine.

    Narrow mutation for cross-checking without the dual engine: the
    lec/postRouteLec ledger tools are rewritten and their
    state/subflow/checklist reset so the new engine re-evidences them on
    the next run. Per-engine artifact directories are deliberately NOT
    cleared — prior-run evidence under the previous engine survives for
    A/B comparison — so this never reuses the rerun-prep dir clearing.
    The new engine also persists to ``[flow].lec_engine`` so future
    ledger-less rebuilds agree; editing the config alone never performs
    this switch. Returns the switched step names.
    """
    from chipcompiler.data import LEC_STEP_TOOLS, LECEngineEnum, SkippableStepEnum
    from chipcompiler.runtime.workspace_api import (
        WorkspaceRuntimeApi,
        _workspace_step_from_flow,
        build_flow_for_workspace,
    )

    engine_value = LECEngineEnum.from_value(engine).value
    lec_names = {SkippableStepEnum.LEC.value, SkippableStepEnum.POST_ROUTE_LEC.value}

    # Persist the config first: a failed config save leaves the ledger
    # untouched; a failed ledger save rolls the config back, so the two
    # stores never diverge on the engine identity.
    parameters = getattr(workspace, "parameters", None)
    parameters_data = getattr(parameters, "data", None)
    previous_flow = None
    if isinstance(parameters_data, dict):
        from chipcompiler.data.workspace_config import validate_flow_config

        previous_flow = parameters_data.get("_flow")
        flow_section = dict(previous_flow or {})
        flow_section["lec_engine"] = engine_value
        parameters_data["_flow"] = validate_flow_config(flow_section)
        if getattr(parameters, "path", None) is not None and not _save_flow_parameters(parameters):
            _restore_flow_parameters(parameters, previous_flow)
            raise RuntimeApiError(
                "command_failed",
                "failed to persist [flow].lec_engine in the workspace config",
            )

    engine_flow = build_flow_for_workspace(workspace, create_step_workspaces=False)
    switched: list[str] = []
    previous_records: list[tuple[dict, dict]] = []
    for record in workspace.flow.data.get("steps", []):
        name = str(record.get("name", ""))
        if name not in lec_names or str(record.get("tool", "")) not in LEC_STEP_TOOLS:
            continue
        previous_records.append((record, dict(record)))
        record.update(
            {
                "tool": engine_value,
                "state": "Unstart",
                "runtime": "",
                "peak memory (mb)": 0,
            }
        )
        switched.append(name)

    if switched and not engine_flow.save():
        for record, previous in previous_records:
            record.clear()
            record.update(previous)
        if isinstance(parameters_data, dict):
            _restore_flow_parameters(parameters, previous_flow, persist=True)
        raise RuntimeApiError(
            "command_failed",
            f"failed to persist the flow ledger for {workspace.directory}",
        )

    for name in switched:
        workspace_step = _workspace_step_from_flow(workspace, name)
        if workspace_step is None:
            continue
        subflow_path = getattr(workspace_step.subflow, "path", None)
        if subflow_path and Path(subflow_path).is_file():
            WorkspaceRuntimeApi._reset_step_subflow(workspace_step)
        checklist_path = getattr(workspace_step.checklist, "path", None)
        if checklist_path and Path(checklist_path).is_file():
            WorkspaceRuntimeApi._reset_step_checklist(workspace_step)

    return tuple(switched)


def _save_flow_parameters(parameters) -> bool:
    from chipcompiler.data.parameter import save_parameter

    return save_parameter(parameters)


def _restore_flow_parameters(parameters, previous_flow, *, persist: bool = False) -> None:
    """Restore a pre-switch ``_flow`` (best effort on rollback)."""
    parameters_data = getattr(parameters, "data", None)
    if not isinstance(parameters_data, dict):
        return
    if previous_flow is None:
        parameters_data.pop("_flow", None)
    else:
        parameters_data["_flow"] = previous_flow
    if persist:
        _save_flow_parameters(parameters)
