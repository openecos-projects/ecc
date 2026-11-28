"""Projection of workspace-level output controls into ``home/flow.json``."""

from copy import deepcopy

from .document import FlowDocument

OPTIONS_KEY = "options"
GEOMETRY_KEY = "geometry"
SNAPSHOT_KEY = "snapshot"
CLOCK_TREE_KEY = "clock_tree"


def geometry_snapshot_requested(workspace) -> bool:
    """Return the snapshot control, retaining capture for existing workspaces."""
    from chipcompiler.data.parameter_schema import lookup_schema
    from chipcompiler.data.workspace.parameters import workspace_param_value

    schema = lookup_schema("geometry.snapshot")
    assert schema is not None
    return workspace_param_value(workspace, schema) is True


def clock_tree_requested(workspace) -> bool:
    """Clock-tree visualization is opt-in and requires geometry snapshots."""
    from chipcompiler.data.parameter_schema import lookup_schema
    from chipcompiler.data.workspace.parameters import workspace_param_value

    schema = lookup_schema("geometry.clock_tree")
    if schema is None:
        return False
    value = workspace_param_value(workspace, schema)
    return value is True and geometry_snapshot_requested(workspace)


def sync_flow_options_projection(workspace, *, persist: bool = False) -> bool:
    """Write the effective output controls into the in-memory flow document.

    Unknown option fields are retained so the ledger remains a forward-compatible
    extension surface. Returns whether the in-memory document changed.
    """
    flow = getattr(workspace, "flow", None)
    if flow is None:
        return False
    steps = getattr(flow, "steps", None)
    if callable(steps):
        steps()
    data = getattr(flow, "data", None)
    if not isinstance(data, dict):
        data = FlowDocument()
        flow.data = data

    options = data.get(OPTIONS_KEY)
    options = {} if not isinstance(options, dict) else deepcopy(options)
    geometry = options.get(GEOMETRY_KEY)
    geometry = {} if not isinstance(geometry, dict) else deepcopy(geometry)
    geometry[SNAPSHOT_KEY] = geometry_snapshot_requested(workspace)
    geometry[CLOCK_TREE_KEY] = clock_tree_requested(workspace)
    options[GEOMETRY_KEY] = geometry
    changed = data.get(OPTIONS_KEY) != options
    data[OPTIONS_KEY] = options

    if persist and changed:
        from .ledger import save_ledger

        if not save_ledger(flow):
            raise OSError("Failed to persist flow options projection")
    return changed
