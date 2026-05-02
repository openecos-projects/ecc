import os

from chipcompiler.cli.output import disclosure_cmd


def _has_investigation_files(step_path: str) -> bool:
    for role in ("output", "report", "analysis"):
        role_dir = os.path.join(step_path, role)
        if os.path.isdir(role_dir):
            if any(os.path.isfile(os.path.join(role_dir, f)) for f in os.listdir(role_dir)):
                return True
    return False


def _count_log_errors(run_dir: str, step_token: str) -> int:
    from chipcompiler.cli.inspect import discover_logs, filter_errors, read_log_file
    logs = discover_logs(run_dir, step_token)
    count = 0
    for lf in logs:
        raw = read_log_file(lf)
        count += len(filter_errors(raw))
    return count


def _has_metrics(run_dir: str, step_token: str) -> bool:
    from chipcompiler.cli.inspect import discover_metrics
    return bool(discover_metrics(run_dir, step_token))


def _has_config_files(step_path: str) -> bool:
    config_dir = os.path.join(step_path, "config")
    if not os.path.isdir(config_dir):
        return False
    return any(os.path.isfile(os.path.join(config_dir, f)) for f in os.listdir(config_dir))


def _make_issue(issue: str, severity: str, run: str,
                step: str | None = None,
                status: str | None = None,
                count: int | None = None,
                project: str | None = None,
                run_id: str | None = None) -> dict:
    obj = {
        "kind": "issue",
        "issue": issue,
        "severity": severity,
        "run": run,
    }
    if step:
        obj["step"] = step
    if status:
        obj["status"] = status
    if count is not None:
        obj["count"] = count

    cmd_kwargs = {"project": project, "run_id": run_id}
    if issue in ("missing_run", "invalid_flow_json"):
        obj["evidence"] = disclosure_cmd("ecc status", **cmd_kwargs)
        obj["run_cmd"] = disclosure_cmd("ecc run", project=project)
    elif issue == "log_errors":
        obj["evidence"] = disclosure_cmd(f"ecc log {step} --errors", **cmd_kwargs)
        obj["artifacts"] = disclosure_cmd(f"ecc artifacts {step}", **cmd_kwargs)
    elif issue == "missing_metrics":
        obj["evidence"] = disclosure_cmd(f"ecc metrics {step} --json", **cmd_kwargs)
        obj["log"] = disclosure_cmd(f"ecc log {step} --errors", **cmd_kwargs)
    elif issue == "missing_artifacts":
        obj["evidence"] = disclosure_cmd(f"ecc artifacts {step}", **cmd_kwargs)
        obj["config"] = disclosure_cmd(f"ecc config {step} --resolved", **cmd_kwargs)
    elif issue == "config_unavailable":
        obj["evidence"] = disclosure_cmd(f"ecc config {step} --resolved", **cmd_kwargs)
        obj["artifacts"] = disclosure_cmd(f"ecc artifacts {step}", **cmd_kwargs)
    elif step:
        obj["evidence"] = disclosure_cmd("ecc status", **cmd_kwargs)
        obj["log"] = disclosure_cmd(f"ecc log {step} --errors", **cmd_kwargs)
        obj["artifacts"] = disclosure_cmd(f"ecc artifacts {step}", **cmd_kwargs)
        obj["config"] = disclosure_cmd(f"ecc config {step} --resolved", **cmd_kwargs)

    return obj


def build_diagnose_issues(run_dir: str, step_token: str | None = None,
                          project: str | None = None,
                          run_id: str | None = None) -> tuple[list[dict], int]:
    from chipcompiler.cli.inspect import (
        CORRUPT_FLOW_JSON,
        discover_step_dirs,
        read_flow_json,
        _safe_steps,
    )
    from chipcompiler.cli.output import normalize_state, normalize_step_name

    display_run = run_id or "default"
    issues = []

    flow_data = read_flow_json(run_dir)

    if flow_data is None:
        issues.append(_make_issue("missing_run", "error", display_run,
                                  project=project, run_id=run_id))
        return issues, 1

    if flow_data is CORRUPT_FLOW_JSON:
        issues.append(_make_issue("invalid_flow_json", "error", display_run,
                                  project=project, run_id=run_id))
        return issues, 1

    steps = _safe_steps(flow_data)
    step_dirs = discover_step_dirs(run_dir)

    flow_tokens = {normalize_step_name(s.get("name", "")) for s in steps}
    known_tokens = flow_tokens | set(step_dirs.keys())

    if step_token is not None:
        if step_token not in known_tokens:
            issues.append(_make_issue("unknown_step", "error", display_run,
                                      step=step_token, project=project, run_id=run_id))
            return issues, 1
    for s in steps:
        token = normalize_step_name(s.get("name", ""))
        if step_token is not None and token != step_token:
            continue
        state = normalize_state(s.get("state", ""))

        if state in ("incomplete", "invalid"):
            issues.append(_make_issue("failed_step", "error", display_run,
                                      step=token, status=state,
                                      project=project, run_id=run_id))
        elif state == "pending":
            issues.append(_make_issue("pending_step", "warning", display_run,
                                      step=token, status=state,
                                      project=project, run_id=run_id))
        elif state == "ongoing":
            issues.append(_make_issue("ongoing_step", "warning", display_run,
                                      step=token, status=state,
                                      project=project, run_id=run_id))
        elif state == "unstart":
            issues.append(_make_issue("unstarted_step", "info", display_run,
                                      step=token, status=state,
                                      project=project, run_id=run_id))

        if token in step_dirs:
            error_count = _count_log_errors(run_dir, token)
            if error_count > 0:
                issues.append(_make_issue("log_errors", "error", display_run,
                                          step=token, count=error_count,
                                          project=project, run_id=run_id))

            if not _has_metrics(run_dir, token):
                issues.append(_make_issue("missing_metrics", "warning", display_run,
                                          step=token, project=project, run_id=run_id))

            if not _has_investigation_files(step_dirs[token]):
                issues.append(_make_issue("missing_artifacts", "warning", display_run,
                                          step=token, project=project, run_id=run_id))

            if not _has_config_files(step_dirs[token]):
                issues.append(_make_issue("config_unavailable", "info", display_run,
                                          step=token, project=project, run_id=run_id))
        else:
            issues.append(_make_issue("missing_metrics", "warning", display_run,
                                      step=token, project=project, run_id=run_id))
            issues.append(_make_issue("missing_artifacts", "warning", display_run,
                                      step=token, project=project, run_id=run_id))
            issues.append(_make_issue("config_unavailable", "info", display_run,
                                      step=token, project=project, run_id=run_id))

    return issues, 0


def _exit_code(issues: list[dict]) -> int:
    for issue in issues:
        if issue.get("severity") == "error":
            return 1
    return 0


def build_diagnose_lines(run_dir: str, step_token: str | None = None,
                         project: str | None = None,
                         run_id: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    issues, rc = build_diagnose_issues(run_dir, step_token, project, run_id)

    if not issues:
        display_run = run_id or "default"
        return [format_line(
            status="clean",
            run=display_run,
            status_cmd=disclosure_cmd("ecc status", project, run_id),
            artifacts=disclosure_cmd("ecc artifacts", project, run_id),
            config=disclosure_cmd("ecc config --resolved", project, run_id),
        )], 0

    lines = []
    text_keys = ("issue", "severity", "run", "step", "status", "count",
                 "evidence", "log", "artifacts", "config", "run_cmd")
    for issue in issues:
        fields = {k: issue[k] for k in text_keys if k in issue}
        lines.append(format_line(**fields))

    return lines, _exit_code(issues)


def _clean_object(run_id, project, run_id_val):
    return {
        "status": "clean",
        "run": run_id or "default",
        "status_cmd": disclosure_cmd("ecc status", project, run_id_val),
        "artifacts": disclosure_cmd("ecc artifacts", project, run_id_val),
        "config": disclosure_cmd("ecc config --resolved", project, run_id_val),
    }


def build_diagnose_json(run_dir: str, step_token: str | None = None,
                        project: str | None = None,
                        run_id: str | None = None) -> tuple[dict, int]:
    issues, _ = build_diagnose_issues(run_dir, step_token, project, run_id)
    if not issues:
        return _clean_object(run_id, project, run_id), 0
    return {"issues": issues}, _exit_code(issues)


def build_diagnose_jsonl(run_dir: str, step_token: str | None = None,
                         project: str | None = None,
                         run_id: str | None = None) -> tuple[list[dict], int]:
    issues, _ = build_diagnose_issues(run_dir, step_token, project, run_id)
    if not issues:
        return [_clean_object(run_id, project, run_id)], 0
    return issues, _exit_code(issues)
