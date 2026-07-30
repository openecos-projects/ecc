import json
import os

from chipcompiler.cli.core.output import (
    normalize_state,
    normalize_step_name,
)


def resolve_run_dir(project_dir: str, run_id: str | None = None) -> tuple[str, str | None]:
    if not run_id:
        return os.path.join(project_dir, "runs", "default"), run_id

    if run_id == "default":
        return os.path.join(project_dir, "runs", "default"), "default"

    if os.path.isabs(run_id):
        return run_id, run_id

    if os.sep in run_id or "/" in run_id:
        return os.path.join(project_dir, run_id), run_id

    return os.path.join(project_dir, "runs", run_id), run_id


CORRUPT_FLOW_JSON = "CORRUPT"


def read_flow_json(run_dir: str) -> dict | str | None:
    path = os.path.join(run_dir, "home", "flow.json")
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else CORRUPT_FLOW_JSON
    except (json.JSONDecodeError, OSError):
        return CORRUPT_FLOW_JSON


def _safe_steps(flow_data: dict) -> list[dict]:
    steps = flow_data.get("steps", [])
    if not isinstance(steps, list):
        return []
    return [s for s in steps if isinstance(s, dict)]


def get_run_status(flow_data: dict) -> str:
    steps = _safe_steps(flow_data)
    if not steps:
        return "unstart"
    states = {normalize_state(s.get("state", "")) for s in steps}
    if states & {"ongoing", "pending"}:
        return "ongoing"
    if states & {"incomplete", "invalid"}:
        return "failed"
    if states == {"success"}:
        return "success"
    if states == {"unstart"}:
        return "unstart"
    return "failed"


def discover_step_dirs(run_dir: str) -> dict[str, str]:
    result = {}
    if not os.path.isdir(run_dir):
        return result
    for entry in os.listdir(run_dir):
        full = os.path.join(run_dir, entry)
        if not os.path.isdir(full):
            continue
        name = step_dir_step_name(full)
        if name is None:
            continue
        token = normalize_step_name(name)
        result[token] = full
    return result


def step_dir_step_name(step_path: str) -> str | None:
    entry = os.path.basename(step_path)
    if "_" not in entry:
        return None
    return entry.rpartition("_")[0]


def step_dir_tool(step_path: str) -> str | None:
    entry = os.path.basename(step_path)
    if "_" not in entry:
        return None
    return entry.rpartition("_")[2]


def get_flow_step_names(run_dir: str) -> set[str]:
    flow_data = read_flow_json(run_dir)
    if not isinstance(flow_data, dict):
        return set()
    return {normalize_step_name(s.get("name", "")) for s in _safe_steps(flow_data) if s.get("name")}


def _list_files(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, f))
    )


def discover_logs(run_dir: str, step_token: str | None = None) -> list[str]:
    if step_token is None:
        return _list_files(os.path.join(run_dir, "log"))

    step_dirs = discover_step_dirs(run_dir)
    if step_token not in step_dirs:
        return []

    return _list_files(os.path.join(step_dirs[step_token], "log"))


def read_log_file(path: str) -> list[str]:
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def listing_step_order(run_dir: str) -> list[str]:
    """Return step tokens in flow.json order, with undiscovered extras alphabetically after."""
    step_dirs = discover_step_dirs(run_dir)
    if not step_dirs:
        return []

    flow_data = read_flow_json(run_dir)
    if isinstance(flow_data, dict):
        flow_tokens = [
            normalize_step_name(s.get("name", "")) for s in _safe_steps(flow_data) if s.get("name")
        ]
        flow_set = set(flow_tokens)
        result = [t for t in flow_tokens if t in step_dirs]
        result.extend(sorted(t for t in step_dirs if t not in flow_set))
        return result

    return sorted(step_dirs)
