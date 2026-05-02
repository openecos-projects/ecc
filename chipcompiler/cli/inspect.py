import json
import os
import re

from chipcompiler.cli.output import (
    disclosure_cmd,
    normalize_metric_key,
    normalize_state,
    normalize_step_name,
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
        return data if isinstance(data, dict) else None
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
    for step in steps:
        state = normalize_state(step.get("state", ""))
        if state == "ongoing":
            return "ongoing"
        if state in ("incomplete", "invalid"):
            return "failed"
    all_success = all(normalize_state(s.get("state", "")) == "success" for s in steps)
    if all_success:
        return "success"
    all_unstart = all(normalize_state(s.get("state", "")) == "unstart" for s in steps)
    return "unstart" if all_unstart else "failed"


def build_status_lines(run_dir: str, project: str | None = None,
                       run_id: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    flow_data = read_flow_json(run_dir)
    if flow_data is None:
        line = format_line(
            run=run_id or "default",
            status="missing",
            workspace=run_dir,
            run_cmd=disclosure_cmd("ecc run", project),
        )
        return [line], 1

    if flow_data is CORRUPT_FLOW_JSON:
        line = format_line(
            run=run_id or "default",
            status="corrupt",
            workspace=run_dir,
            status_cmd=disclosure_cmd("ecc status", project, run_id),
            log=disclosure_cmd("ecc log", project, run_id),
        )
        return [line], 1

    run_status = get_run_status(flow_data)
    lines = []

    lines.append(format_line(
        run=run_id or "default",
        status=run_status,
        workspace=run_dir,
        status_cmd=disclosure_cmd("ecc status", project, run_id),
        metrics=disclosure_cmd("ecc metrics", project, run_id),
        log=disclosure_cmd("ecc log", project, run_id),
    ))

    for step in _safe_steps(flow_data):
        step_token = normalize_step_name(step.get("name", ""))
        lines.append(format_line(
            step=step_token,
            tool=step.get("tool", ""),
            status=normalize_state(step.get("state", "")),
            runtime=step.get("runtime", "") or None,
            metrics=disclosure_cmd(f"ecc metrics {step_token}", project, run_id),
            log=disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
        ))

    return lines, 0


def build_status_json(run_dir: str, run_id: str | None = None) -> tuple[dict, int]:
    flow_data = read_flow_json(run_dir)
    display_run = run_id or "default"
    if flow_data is None:
        return {"run": display_run, "status": "missing", "workspace": run_dir}, 1

    if flow_data is CORRUPT_FLOW_JSON:
        return {"run": display_run, "status": "corrupt", "workspace": run_dir}, 1

    run_status = get_run_status(flow_data)
    steps = []
    for step in _safe_steps(flow_data):
        steps.append({
            "step": normalize_step_name(step.get("name", "")),
            "tool": step.get("tool", ""),
            "status": normalize_state(step.get("state", "")),
            "runtime": step.get("runtime", ""),
        })

    return {"run": display_run, "status": run_status, "workspace": run_dir, "steps": steps}, 0


def build_status_jsonl(run_dir: str, run_id: str | None = None) -> tuple[list[dict], int]:
    flow_data = read_flow_json(run_dir)
    display_run = run_id or "default"
    if flow_data is None:
        return [{"kind": "run", "run": display_run, "status": "missing", "workspace": run_dir}], 1

    if flow_data is CORRUPT_FLOW_JSON:
        return [{"kind": "run", "run": display_run, "status": "corrupt", "workspace": run_dir}], 1

    run_status = get_run_status(flow_data)
    objects = [{"kind": "run", "run": display_run, "status": run_status, "workspace": run_dir}]

    for step in _safe_steps(flow_data):
        objects.append({
            "kind": "step",
            "step": normalize_step_name(step.get("name", "")),
            "tool": step.get("tool", ""),
            "status": normalize_state(step.get("state", "")),
            "runtime": step.get("runtime", ""),
        })

    return objects, 0


ERROR_PATTERNS = re.compile(r"(error|failed|traceback)", re.IGNORECASE)
_CLEAN_SUMMARY = re.compile(r"^\s*\d+\s+(error|failed)|^no\s+(error|failed)", re.IGNORECASE)


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
        with open(path) as f:
            return f.read().splitlines()
    except OSError:
        return []


def build_log_lines(run_dir: str, step_token: str | None, errors_only: bool,
                    project: str | None = None,
                    run_id: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    if step_token is None:
        lines = []

        global_logs = discover_logs(run_dir)
        for lf in global_logs:
            lines.append(format_line(
                log=os.path.relpath(lf, run_dir),
                inspect=disclosure_cmd("ecc log", project, run_id),
            ))

        step_dirs = discover_step_dirs(run_dir)
        for token in sorted(step_dirs):
            step_logs = discover_logs(run_dir, token)
            for lf in step_logs:
                lines.append(format_line(
                    step=token,
                    log=os.path.relpath(lf, run_dir),
                    inspect=disclosure_cmd(f"ecc log {token} --errors", project, run_id),
                ))

        if not lines:
            return [format_line(
                log_status="no_logs",
                workspace=run_dir,
                run=disclosure_cmd("ecc run", project),
            )], 0

        return lines, 0

    step_dirs = discover_step_dirs(run_dir)
    if step_token not in step_dirs:
        return [format_line(
            step=step_token,
            status="unknown_step",
            inspect=disclosure_cmd("ecc status", project, run_id),
        )], 1

    log_files = discover_logs(run_dir, step_token)
    if not log_files:
        return [format_line(
            step=step_token,
            log_status="missing",
            log=disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
        )], 1

    matched_lines = []
    for lf in log_files:
        raw = read_log_file(lf)
        filtered = filter_errors(raw) if errors_only else raw
        for line in filtered:
            matched_lines.append((lf, line))

    if not matched_lines:
        return [format_line(
            step=step_token,
            log_status="no_matching_lines",
            log=disclosure_cmd(f"ecc log {step_token}", project, run_id),
        )], 0

    result = []
    for lf, line in matched_lines:
        result.append(format_line(
            step=step_token,
            source=os.path.relpath(lf, run_dir),
            line=line,
            log=disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
        ))
    return result, 0


def build_log_jsonl(run_dir: str, step_token: str | None, errors_only: bool,
                    project: str | None = None,
                    run_id: str | None = None) -> tuple[list[dict], int]:
    if step_token is None:
        objects = []
        for lf in discover_logs(run_dir):
            objects.append({"log": os.path.relpath(lf, run_dir)})
        step_dirs = discover_step_dirs(run_dir)
        for token in sorted(step_dirs):
            for lf in discover_logs(run_dir, token):
                objects.append({"step": token, "log": os.path.relpath(lf, run_dir)})
        if not objects:
            return [{"log_status": "no_logs", "workspace": run_dir}], 0
        return objects, 0

    step_dirs = discover_step_dirs(run_dir)
    if step_token not in step_dirs:
        return [{"step": step_token, "status": "unknown_step"}], 1

    log_files = discover_logs(run_dir, step_token)
    if not log_files:
        return [{"step": step_token, "log_status": "missing"}], 1

    objects = []
    for lf in log_files:
        raw = read_log_file(lf)
        lines = filter_errors(raw) if errors_only else raw
        for line in lines:
            objects.append({
                "step": step_token,
                "source": os.path.relpath(lf, run_dir),
                "line": line,
            })

    return objects, 0


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


def build_metrics_lines(run_dir: str, step_token: str | None = None,
                        project: str | None = None,
                        run_id: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    metrics_files = discover_metrics(run_dir, step_token)
    if not metrics_files:
        if step_token is not None:
            step_dirs = discover_step_dirs(run_dir)
            if step_token in step_dirs:
                return [format_line(
                    metric_step=step_token,
                    status="missing",
                    path=os.path.relpath(
                        os.path.join(step_dirs[step_token], "analysis",
                                     f"{_internal_from_token(step_token)}_metrics.json"),
                        run_dir,
                    ),
                    log=disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
                )], 1
            return [format_line(
                step=step_token,
                status="unknown_step",
                inspect=disclosure_cmd("ecc status", project, run_id),
            )], 1
        return [format_line(
            metrics_status="none",
            workspace=run_dir,
            status_cmd=disclosure_cmd("ecc status", project, run_id),
        )], 0

    lines = []
    has_corrupt = False
    for token, path in sorted(metrics_files.items()):
        data = read_metrics(path)
        if data is None:
            has_corrupt = True
            lines.append(format_line(
                metric_step=token,
                status="corrupt",
                path=os.path.relpath(path, run_dir),
                log=disclosure_cmd(f"ecc log {token} --errors", project, run_id),
            ))
            continue
        for raw_key, value in data.items():
            norm_key = normalize_metric_key(raw_key)
            lines.append(format_line(
                metric=norm_key,
                step=token,
                value=value,
                source=os.path.relpath(path, run_dir),
                inspect=disclosure_cmd(f"ecc metrics {token} --json", project, run_id),
            ))
    return lines, 1 if has_corrupt else 0


def _collect_metrics(run_dir: str, step_token: str | None,
                     project: str | None,
                     run_id: str | None = None) -> tuple[list[dict], int]:
    err = _check_requested_step(run_dir, step_token, project, run_id)
    if err is not None:
        return [err], 1

    metrics_files = discover_metrics(run_dir, step_token)
    items = []
    for token, path in sorted(metrics_files.items()):
        data = read_metrics(path)
        if data is None:
            return [{"status": "corrupt", "metric_step": token,
                     "log_cmd": disclosure_cmd(f"ecc log {token} --errors", project, run_id)}], 1
        for raw_key, value in data.items():
            items.append({
                "metric": normalize_metric_key(raw_key),
                "step": token,
                "value": value,
                "source": os.path.relpath(path, run_dir),
            })
    return items, 0


def build_metrics_json(run_dir: str, step_token: str | None = None,
                       project: str | None = None,
                       run_id: str | None = None) -> tuple[dict, int]:
    items, rc = _collect_metrics(run_dir, step_token, project, run_id)
    if rc != 0:
        return items[0], 1
    return {"metrics": items}, 0


def build_metrics_jsonl(run_dir: str, step_token: str | None = None,
                        project: str | None = None,
                        run_id: str | None = None) -> tuple[list[dict], int]:
    return _collect_metrics(run_dir, step_token, project, run_id)


def _check_requested_step(run_dir: str, step_token: str | None,
                          project: str | None = None,
                          run_id: str | None = None) -> dict | None:
    if step_token is None:
        return None
    step_dirs = discover_step_dirs(run_dir)
    if step_token not in step_dirs:
        return {"status": "unknown_step", "step": step_token}
    metrics = discover_metrics(run_dir, step_token)
    if not metrics:
        return {
            "status": "missing",
            "metric_step": step_token,
            "log_cmd": disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
        }
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
