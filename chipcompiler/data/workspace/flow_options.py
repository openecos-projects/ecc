"""Projection of workspace-level output controls into ``home/flow.json``."""

from copy import deepcopy

from .flow_types import FlowDocument

OPTIONS_KEY = "options"
GEOMETRY_KEY = "geometry"
CLOCK_TREE_KEY = "clock_tree"


def clock_tree_requested(workspace) -> bool:
    """Return the validated Workspace parameter, defaulting old workspaces to false."""
    from chipcompiler.data.parameter_schema import lookup_schema
    from chipcompiler.data.workspace_parameters import workspace_param_value

    schema = lookup_schema("geometry.clock_tree")
    if schema is None:
        return False
    value = workspace_param_value(workspace, schema)
    return value is True


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
    if not isinstance(options, dict):
        options = {}
    else:
        options = deepcopy(options)
    geometry = options.get(GEOMETRY_KEY)
    if not isinstance(geometry, dict):
        geometry = {}
    else:
        geometry = deepcopy(geometry)
    desired = clock_tree_requested(workspace)
    changed = geometry.get(CLOCK_TREE_KEY) is not desired
    geometry[CLOCK_TREE_KEY] = desired
    options[GEOMETRY_KEY] = geometry
    changed = changed or data.get(OPTIONS_KEY) != options
    data[OPTIONS_KEY] = options

    if persist and changed:
        from .flow_ledger import save_ledger

        if not save_ledger(flow):
            raise OSError("Failed to persist flow options projection")
    return changed
