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
