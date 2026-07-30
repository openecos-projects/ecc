import shlex


def disclosure_cmd(command: str, project: str | None = None, run_id: str | None = None) -> str:
    parts = [command]
    if project:
        parts.append(f"--project {shlex.quote(project)}")
    if run_id is not None:
        parts.append(f"--run-id {shlex.quote(run_id)}")
    return " ".join(parts)


def normalize_step_name(internal: str) -> str:
    mapping = {
        "Synthesis": "synthesis",
        "Floorplan": "floorplan",
        "fixFanout": "fixfanout",
        "place": "placement",
        "CTS": "cts",
        "legalization": "legalization",
        "route": "routing",
        "drc": "drc",
        "filler": "filler",
    }
    return mapping.get(internal, internal.lower())


def normalize_state(internal: str) -> str:
    mapping = {
        "Success": "success",
        "Incomplete": "incomplete",
        "Unstart": "unstart",
        "Ongoing": "ongoing",
        "Pending": "pending",
        "Invalid": "invalid",
    }
    return mapping.get(internal, internal.lower())
