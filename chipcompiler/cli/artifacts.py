import os

from chipcompiler.cli.output import disclosure_cmd

KNOWN_ROLES = {"config", "input", "output", "data", "feature", "report", "log", "script", "analysis"}


def _role_from_dirname(dirname: str) -> str:
    return dirname if dirname in KNOWN_ROLES else "unknown"


def discover_artifacts(run_dir: str, step_token: str | None = None,
                       project: str | None = None,
                       run_id: str | None = None,
                       project_dir: str | None = None) -> tuple[list[dict], int]:
    from chipcompiler.cli.inspect import discover_step_dirs
    from chipcompiler.cli.output import format_line

    base_dir = project_dir or os.path.dirname(os.path.dirname(run_dir))
    step_dirs = discover_step_dirs(run_dir)

    if step_token is not None:
        if step_token not in step_dirs:
            return [{"kind": "error", "step": step_token,
                      "status": "unknown_step"}], 1
        tokens = [step_token]
    else:
        tokens = sorted(step_dirs.keys())

    artifacts = []
    for token in tokens:
        step_path = step_dirs[token]
        for entry in sorted(os.listdir(step_path)):
            subdir = os.path.join(step_path, entry)
            if not os.path.isdir(subdir):
                continue
            role = _role_from_dirname(entry)
            for fname in sorted(os.listdir(subdir)):
                fpath = os.path.join(subdir, fname)
                if os.path.isfile(fpath):
                    artifacts.append({
                        "kind": "artifact",
                        "step": token,
                        "role": role,
                        "run": run_id or "default",
                        "path": os.path.relpath(fpath, base_dir),
                        "exists": True,
                        "inspect_cmd": disclosure_cmd(f"ecc artifacts {token} --json", project, run_id),
                    })

    if not artifacts:
        return [], 0

    return artifacts, 0


def build_artifacts_lines(run_dir: str, step_token: str | None = None,
                          project: str | None = None,
                          run_id: str | None = None,
                          project_dir: str | None = None) -> tuple[list[str], int]:
    from chipcompiler.cli.output import format_line

    artifacts, rc = discover_artifacts(run_dir, step_token, project, run_id, project_dir)
    if rc != 0:
        if artifacts and artifacts[0].get("status") == "unknown_step":
            s = artifacts[0]["step"]
            return [format_line(
                step=s,
                status="unknown_step",
                status_cmd=disclosure_cmd("ecc status", project, run_id),
            )], 1
        return [], rc

    if not artifacts:
        if step_token is not None:
            return [format_line(
                step=step_token,
                artifacts_status="none",
                status_cmd=disclosure_cmd("ecc status", project, run_id),
                log=disclosure_cmd(f"ecc log {step_token} --errors", project, run_id),
            )], 0
        return [format_line(
            artifacts_status="none",
            workspace=run_dir,
            status_cmd=disclosure_cmd("ecc status", project, run_id),
        )], 0

    lines = []
    for a in artifacts:
        line_fields = {
            "artifact": os.path.basename(a["path"]),
            "step": a["step"],
            "role": a["role"],
            "path": a["path"],
            "inspect": disclosure_cmd(f"ecc artifacts {a['step']} --json", project, run_id),
        }
        if a["role"] == "analysis":
            line_fields["metrics"] = disclosure_cmd(f"ecc metrics {a['step']}", project, run_id)
        if a["role"] == "log":
            line_fields["inspect"] = disclosure_cmd(f"ecc log {a['step']} --errors", project, run_id)
        if a["role"] in ("output", "report", "analysis", "log"):
            line_fields["config"] = disclosure_cmd(f"ecc config {a['step']} --resolved", project, run_id)
        lines.append(format_line(**line_fields))
    return lines, 0


def build_artifacts_json(run_dir: str, step_token: str | None = None,
                         project: str | None = None,
                         run_id: str | None = None,
                         project_dir: str | None = None) -> tuple[dict, int]:
    artifacts, rc = discover_artifacts(run_dir, step_token, project, run_id, project_dir)
    if rc != 0:
        if artifacts and artifacts[0].get("status") == "unknown_step":
            return {"status": "unknown_step", "step": artifacts[0]["step"]}, 1
        return {}, rc

    if not artifacts:
        if step_token is not None:
            return {"artifacts_status": "none", "step": step_token}, 0
        return {"artifacts_status": "none"}, 0

    return {"artifacts": artifacts}, 0


def build_artifacts_jsonl(run_dir: str, step_token: str | None = None,
                          project: str | None = None,
                          run_id: str | None = None,
                          project_dir: str | None = None) -> tuple[list[dict], int]:
    artifacts, rc = discover_artifacts(run_dir, step_token, project, run_id, project_dir)
    if rc != 0:
        return artifacts, rc

    if not artifacts:
        if step_token is not None:
            return [{"artifacts_status": "none", "step": step_token}], 0
        return [{"artifacts_status": "none"}], 0

    return artifacts, 0
