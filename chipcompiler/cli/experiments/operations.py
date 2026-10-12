from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


def project_path(value: str | None) -> Path:
    path = Path(value or os.getcwd()).expanduser().resolve()
    if path.is_file():
        path = path.parent
    for candidate in (path, *path.parents):
        if (candidate / "project.json").exists() or (candidate / "ecc.toml").exists():
            return candidate
    return path


def workspace_path(project: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (project / value).resolve()


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def safe_relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def export_package(project: Path, workspace: Path, output: Path) -> dict[str, Any]:
    if not workspace.is_dir():
        raise ValueError(f"workspace does not exist: {workspace}")
    files: list[Path] = []
    roots = [project / "project.json", project / "ecc.toml"]
    for relative in ("home", "config", "reports", "results"):
        candidate = workspace / relative
        if candidate.exists():
            roots.append(candidate)
    roots.extend(workspace.glob("*.json"))
    seen: set[Path] = set()
    for root in roots:
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            files.extend(item for item in root.rglob("*") if item.is_file())
    files = sorted(path for path in files if not any(part in {".git", "__pycache__"} for part in path.parts))
    staging = output.parent / f".{output.stem}.staging-{os.getpid()}"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    entries = []
    try:
        for source in files:
            relative = safe_relative(project, source)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            entries.append({"path": relative, "size": target.stat().st_size, "sha256": digest})
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "kind": "ecc-reproducible-export",
            "project": str(project),
            "workspace": str(workspace),
            "created_at": int(time.time()),
            "files": entries,
        }
        dump_json(staging / "manifest.json", manifest)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as archive:
            archive.add(staging, arcname=".")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"status": "success", "package": str(output), "file_count": len(entries)}


def read_package(package: Path) -> tuple[tarfile.TarFile, dict[str, Any]]:
    archive = tarfile.open(package, "r:gz")
    try:
        member = archive.getmember("./manifest.json")
    except KeyError:
        archive.close()
        raise ValueError("package does not contain manifest.json") from None
    manifest = json.load(archive.extractfile(member))
    return archive, manifest


def verify_package(package: Path) -> dict[str, Any]:
    archive, manifest = read_package(package)
    errors: list[str] = []
    try:
        names = {member.name for member in archive.getmembers()}
        for entry in manifest.get("files", []):
            name = f"./{entry['path']}"
            if name not in names:
                errors.append(f"missing: {entry['path']}")
                continue
            member = archive.getmember(name)
            digest = hashlib.sha256(archive.extractfile(member).read()).hexdigest()
            if digest != entry.get("sha256"):
                errors.append(f"checksum: {entry['path']}")
        for member in archive.getmembers():
            if Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                errors.append(f"unsafe path: {member.name}")
    finally:
        archive.close()
    return {"status": "pass" if not errors else "fail", "package": str(package), "errors": errors}


def parse_parameters(values: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"parameter must be KEY=VALUE[,VALUE]: {value}")
        key, raw = value.split("=", 1)
        choices = [item for item in raw.split(",") if item]
        if not key or not choices:
            raise ValueError(f"parameter must have a key and values: {value}")
        result[key] = choices
    if not result:
        raise ValueError("at least one --param is required")
    return result


def create_sweep(project: Path, name: str, parameters: dict[str, list[str]]) -> dict[str, Any]:
    root = project / "experiments" / name
    if root.exists():
        raise ValueError(f"sweep already exists: {name}")
    keys = sorted(parameters)
    candidates = [
        {"id": f"candidate_{index:04d}", "parameters": dict(zip(keys, values))}
        for index, values in enumerate(itertools.product(*(parameters[key] for key in keys)), 1)
    ]
    payload = {"schema_version": SCHEMA_VERSION, "name": name, "parameters": parameters, "candidates": candidates}
    dump_json(root / "sweep.json", payload)
    return payload


def sweep_result(project: Path, name: str) -> Path:
    return project / "experiments" / name / "results.json"


def compare_sweep(project: Path, name: str) -> list[dict[str, Any]]:
    payload = load_json(sweep_result(project, name), {"results": []})
    rows = payload.get("results", [])
    order = {"passed": 0, "success": 0, "blocked": 1, "failed": 2, "unknown": 3}
    return sorted(rows, key=lambda row: (order.get(row.get("status", "unknown"), 3), -(row.get("qor_score") if isinstance(row.get("qor_score"), (int, float)) else float("-inf"))))


def _json_command(project: Path, workspace: Path, command: str) -> tuple[int, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "chipcompiler.cli.main", *command.split(), "--project", str(project), "--workspace", str(workspace), "--json"],
        capture_output=True, text=True, check=False,
    )
    try:
        return completed.returncode, json.loads(completed.stdout)
    except json.JSONDecodeError:
        return completed.returncode, None


def _first_number(value: Any, keys: set[str]) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys and isinstance(child, (int, float)):
                return float(child)
            result = _first_number(child, keys)
            if result is not None:
                return result
    elif isinstance(value, list):
        for child in value:
            result = _first_number(child, keys)
            if result is not None:
                return result
    return None


def collect_candidate_evidence(project: Path, workspace: Path, exit_code: int) -> dict[str, Any]:
    flow = load_json(workspace / "home" / "flow.json", {}) or {}
    status_code, status_payload = _json_command(project, workspace, "status")
    signoff_code, _ = _json_command(project, workspace, "signoff check")
    steps = flow.get("steps", []) if isinstance(flow, dict) else []
    if not steps and isinstance(status_payload, dict):
        steps = status_payload.get("steps", [])
    step_statuses = [{"name": step.get("name"), "status": step.get("status", "unknown"), "checklist": step.get("checklist_status", "unknown")} for step in steps if isinstance(step, dict)]
    blocked = any(step["status"] == "blocked" or step["checklist"] == "blocked" for step in step_statuses)
    failed = exit_code != 0 or signoff_code not in {0, 7}
    status = "blocked" if blocked else "failed" if failed else "passed" if step_statuses or status_code == 0 else "unknown"
    qor_score = None
    for report in workspace.rglob("*.json"):
        qor_score = _first_number(load_json(report), {"qor_score", "score", "ppa_score"})
        if qor_score is not None:
            break
    return {"status": status, "step_statuses": step_statuses, "qor_score": qor_score, "signoff_exit_code": signoff_code, "workspace_status_exit_code": status_code}


def run_sweep(project: Path, name: str, max_candidates: int | None) -> dict[str, Any]:
    plan = load_json(project / "experiments" / name / "sweep.json")
    if not plan:
        raise ValueError(f"sweep does not exist: {name}")
    candidates = plan["candidates"][:max_candidates]
    results = []
    for candidate in candidates:
        workspace = project / "experiments" / name / "workspaces" / candidate["id"]
        command = [sys.executable, "-m", "chipcompiler.cli.main", "run", "--project", str(project), "--workspace", str(workspace)]
        for key, value in candidate["parameters"].items():
            command.extend(["--set", f"{key}={value}"])
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        evidence = collect_candidate_evidence(project, workspace, completed.returncode)
        results.append({"id": candidate["id"], "workspace": str(workspace), "parameters": candidate["parameters"], "exit_code": completed.returncode, **evidence})
    payload = {"schema_version": SCHEMA_VERSION, "results": results}
    dump_json(sweep_result(project, name), payload)
    return payload
