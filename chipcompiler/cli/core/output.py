import shlex


def disclosure_cmd(command: str, project: str | None = None, workspace: str | None = None) -> str:
    parts = [command]
    if project:
        parts.append(f"--project {shlex.quote(project)}")
    if workspace is not None:
        parts.append(f"--workspace {shlex.quote(workspace)}")
    return " ".join(parts)


def flow_step_status(state: str) -> str:
    """The CLI status of a flow step run state, e.g. ``Success`` -> ``success``."""
    return state.lower()
