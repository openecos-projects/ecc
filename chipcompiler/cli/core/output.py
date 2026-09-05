import shlex


def disclosure_cmd(command: str, project: str | None = None, workspace: str | None = None) -> str:
    parts = [command]
    if project:
        parts.append(f"--project {shlex.quote(project)}")
    if workspace is not None:
        parts.append(f"--workspace {shlex.quote(workspace)}")
    return " ".join(parts)


def normalize_step_name(internal: str) -> str:
    mapping = {
        "Synthesis": "synthesis",
        "Floorplan": "floorplan",
        "place": "placement",
        "CTS": "cts",
        "legalization": "legalization",
        "Timing optimization": "timing_optimization",
        "timing optimization": "timing_optimization",
        "route": "routing",
        "drc": "drc",
        "filler": "filler",
        "postRouteLec": "postroutelec",
    }
    return mapping.get(internal, internal.lower())


def normalize_state(internal: str) -> str:
    mapping = {
        "Success": "success",
        "Warning": "warning",
        "Incomplete": "incomplete",
        "Unstart": "unstart",
        "Ongoing": "ongoing",
        "Pending": "pending",
        "Invalid": "invalid",
    }
    return mapping.get(internal, internal.lower())
