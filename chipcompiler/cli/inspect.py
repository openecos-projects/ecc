import json
import os
import re

from chipcompiler.cli.output import (
    normalize_step_name,
    normalize_state,
)


def resolve_run_dir(project_dir: str, run_id: str | None = None) -> tuple[str, str | None]:
    if not run_id:
        return os.path.join(project_dir, "runs", "default"), None

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


ERROR_PATTERNS = re.compile(r"(error|failed|traceback)", re.IGNORECASE)
_CLEAN_SUMMARY = re.compile(r"^\s*0\s+(error|failed|warning)|^no\s+(error|failed|warning)", re.IGNORECASE)


def filter_errors(lines: list[str]) -> list[str]:
    result = []
    for line in lines:
        if ERROR_PATTERNS.search(line) and not _CLEAN_SUMMARY.search(line):
            result.append(line)
    return result


def discover_step_dirs(run_dir: str) -> dict[str, str]:
    result = {}
    if not os.path.isdir(run_dir):
        return result
    for entry in os.listdir(run_dir):
        full = os.path.join(run_dir, entry)
        if os.path.isdir(full) and "_" in entry:
            name, _, tool = entry.partition("_")
            token = normalize_step_name(name)
            result[token] = full
    return result


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


def discover_metrics(run_dir: str, step_token: str | None = None) -> dict[str, str]:
    step_dirs = discover_step_dirs(run_dir)
    result = {}

    if step_token is not None:
        if step_token not in step_dirs:
            return {}
        tokens = [step_token]
    else:
        tokens = list(step_dirs.keys())

    for token in tokens:
        analysis_dir = os.path.join(step_dirs[token], "analysis")
        if not os.path.isdir(analysis_dir):
            continue
        for f in os.listdir(analysis_dir):
            if f.endswith("_metrics.json"):
                result[token] = os.path.join(analysis_dir, f)
                break

    return result


def read_metrics(path: str) -> dict | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _internal_from_token(token: str) -> str:
    reverse = {
        "synthesis": "Synthesis",
        "floorplan": "Floorplan",
        "fixfanout": "fixFanout",
        "placement": "place",
        "cts": "CTS",
        "legalization": "legalization",
        "routing": "route",
        "drc": "drc",
        "filler": "filler",
    }
    return reverse.get(token, token)


def listing_step_order(run_dir: str) -> list[str]:
    """Return step tokens in flow.json order, with undiscovered extras alphabetically after."""
    step_dirs = discover_step_dirs(run_dir)
    if not step_dirs:
        return []

    flow_data = read_flow_json(run_dir)
    if isinstance(flow_data, dict):
        flow_tokens = [
            normalize_step_name(s.get("name", ""))
            for s in _safe_steps(flow_data)
            if s.get("name")
        ]
        flow_set = set(flow_tokens)
        result = [t for t in flow_tokens if t in step_dirs]
        result.extend(sorted(t for t in step_dirs if t not in flow_set))
        return result

    return sorted(step_dirs)
