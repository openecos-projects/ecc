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
    return sorted(rows, key=lambda row: (row.get("status") not in {"passed", "success"}, -(row.get("qor_score") or float("-inf"))))


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
        results.append({"id": candidate["id"], "workspace": str(workspace), "parameters": candidate["parameters"], "status": "passed" if completed.returncode == 0 else "failed", "exit_code": completed.returncode})
    payload = {"schema_version": SCHEMA_VERSION, "results": results}
    dump_json(sweep_result(project, name), payload)
    return payload
